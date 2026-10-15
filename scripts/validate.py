#!/usr/bin/env python3
"""Validate every call in calls/ against the schema and the immutability rules.

Exit code 1 (and a non-empty ERROR list) blocks the deploy. Every message is
`ERROR <file>: <field>: <what is wrong>` so the author can fix it from the log.

Usage:
  python scripts/validate.py                 # validate calls/*.md (skips _example.md)
  python scripts/validate.py --check-examples   # also validate _*.md, without git checks
  python scripts/validate.py --no-git           # skip the first-commit, append-only and deletion checks
  python scripts/validate.py --root /path/to/ledger
"""
from __future__ import annotations

import argparse
import datetime as dt
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import ledgerlib as L  # noqa: E402


def check_schema(call: L.Call, all_ids: set[str], root: pathlib.Path, today: dt.date) -> tuple[list[str], list[str]]:
    """Field-level checks that need no git. Returns (errors, warnings)."""
    m = call.meta
    errs: list[str] = []
    warns: list[str] = []

    def err(field: str, msg: str) -> None:
        errs.append(f"{field}: {msg}")

    for f in L.REQUIRED:
        if f not in m or m[f] in (None, "", []):
            err(f, "required field is missing or empty")
    for f in m:
        if f not in L.KNOWN_FIELDS:
            warns.append(f"{f}: unknown field, ignored by the build")

    # id and title
    cid = str(m.get("id", "")).strip()
    if cid and not L.ID_RE.match(cid):
        err("id", "must look like FCB-YYYY-NNN")
    if cid and cid != call.id and not call.is_example:
        err("id", f"'{cid}' does not match the filename '{call.path.name}'")
    title = m.get("title")
    if title is not None:
        if not isinstance(title, str) or "\n" in title.strip():
            err("title", "must be one line of text")
        elif len(title.split()) > 12:
            err("title", f"{len(title.split())} words; the limit is 12")
    if "claim" in m and not isinstance(m["claim"], str):
        err("claim", "must be text")
    if "resolution_rule" in m and not isinstance(m["resolution_rule"], str):
        err("resolution_rule", "must be text")
    if "changes_my_mind" in m and not isinstance(m["changes_my_mind"], str):
        err("changes_my_mind", "must be text")

    # dates
    made_on = resolves_on = None
    if "made_on" in m:
        if L.is_date(m["made_on"]):
            made_on = L.to_date(m["made_on"])
        else:
            err("made_on", "must be a date, YYYY-MM-DD")
    if "resolves_on" in m:
        if L.is_date(m["resolves_on"]):
            resolves_on = L.to_date(m["resolves_on"])
        else:
            err("resolves_on", "must be a date, YYYY-MM-DD")
    if made_on and resolves_on and resolves_on <= made_on:
        err("resolves_on", "must be after made_on")

    # confidence
    conf = m.get("confidence")
    if conf is not None:
        if not isinstance(conf, int) or isinstance(conf, bool):
            err("confidence", "must be a whole number (percent), not text or a decimal")
        elif not (5 <= conf <= 95) or conf % 5 != 0:
            err("confidence", "must be between 5 and 95 in steps of 5")

    # lists of mappings
    def check_list(field: str, lo: int, hi: int | None, keys: tuple[str, ...]) -> None:
        v = m.get(field)
        if v is None:
            return
        if not isinstance(v, list) or not all(isinstance(x, dict) for x in v):
            err(field, f"must be a list of items with {', '.join(keys)}")
            return
        if len(v) < lo or (hi is not None and len(v) > hi):
            rng = f"{lo}" if hi == lo else (f"{lo}-{hi}" if hi else f"at least {lo}")
            err(field, f"needs {rng} items, has {len(v)}")
        for i, item in enumerate(v, 1):
            for k in keys:
                if not str(item.get(k, "")).strip():
                    err(field, f"item {i} is missing '{k}'")

    check_list("consensus_at_time", 1, 3, ("url", "summary"))
    check_list("leading_indicators", 2, 3, ("what", "cadence"))
    check_list("implies_for", 1, None, ("who", "decision"))
    for i, item in enumerate(m.get("consensus_at_time") or [], 1):
        if isinstance(item, dict) and not str(item.get("url", "")).startswith(("http://", "https://")):
            err("consensus_at_time", f"item {i} url must start with http:// or https://")

    # thesis
    thesis = m.get("thesis")
    if thesis is not None:
        if not isinstance(thesis, str) or not thesis.strip():
            err("thesis", "must be the slug of a file in theses/")
        elif not (root / "theses" / f"{thesis.strip()}.md").exists():
            warns.append(f"thesis: theses/{thesis.strip()}.md does not exist yet (the thesis page is v1.1)")

    # service
    if "service" in m and m["service"] is not None and not isinstance(m["service"], str):
        err("service", "must be text")

    # status
    status = call.status
    if status and status not in L.STATUSES:
        err("status", f"'{status}' is not one of {', '.join(L.STATUSES)}")

    # updates
    updates = m.get("updates")
    n_ind = len(m.get("leading_indicators") or []) if isinstance(m.get("leading_indicators"), list) else 0
    if updates is not None:
        if not isinstance(updates, list) or not all(isinstance(u, dict) for u in updates):
            err("updates", "must be a list of items with date and note")
        else:
            last = None
            for i, u in enumerate(updates, 1):
                if not L.is_date(u.get("date")):
                    err("updates", f"item {i} needs a date, YYYY-MM-DD")
                    continue
                d = L.to_date(u["date"])
                if last is not None and d > last:
                    err("updates", f"item {i} is dated after item {i - 1}; the list is newest first")
                last = d
                if not str(u.get("note", "")).strip():
                    err("updates", f"item {i} needs a note")
                if "url" in u and u["url"] and not str(u["url"]).startswith(("http://", "https://")):
                    err("updates", f"item {i} url must start with http:// or https://")
                ind = u.get("indicator")
                if ind is not None and (not isinstance(ind, int) or isinstance(ind, bool) or not (1 <= ind <= max(n_ind, 1))):
                    err("updates", f"item {i} indicator must be a number from 1 to {n_ind}")

    # supersedes
    sup = m.get("supersedes")
    if sup is not None:
        sup = str(sup).strip()
        if not L.ID_RE.match(sup):
            err("supersedes", "must be a call id like FCB-YYYY-NNN")
        elif sup == call.id:
            err("supersedes", "a call cannot supersede itself")
        elif sup not in all_ids:
            err("supersedes", f"{sup} is not in calls/")

    # resolution fields
    if status in L.RESOLVED_STATUSES:
        for f in L.SET_ONCE:
            v = m.get(f)
            missing = (not v) if isinstance(v, dict) else (v is None or not str(v).strip())
            if missing:
                err(f, f"required once status is {status}")
        result = L.score_result(m)
        expected = L.RESULT_FOR_STATUS[status]
        if result is not None and result != expected:
            err("score", f"result must be {expected} when status is {status}, got {result}")
        if isinstance(conf, int) and result in ("YES", "NO"):
            given = L.score_brier(m)
            want = L.brier_contribution(conf, result)
            if given is not None and abs(given - want) > 1e-6:
                err("score", f"brier contribution should be {want} for confidence {conf} and {result}")
        if status in ("resolved_yes", "resolved_no") and resolves_on and today < resolves_on:
            err("status", f"cannot be {status} before resolves_on ({resolves_on.isoformat()}); "
                          "use void or retracted to close early")
    elif status in L.LIVE_STATUSES:
        for f in L.SET_ONCE:
            if m.get(f) not in (None, "", []):
                err(f, "must stay empty until the call is resolved")

    return errs, warns


def check_git(call: L.Call, root: pathlib.Path) -> tuple[list[str], list[str]]:
    """Immutability checks against the file's own history. Returns (errors, warnings)."""
    errs: list[str] = []
    warns: list[str] = []
    if not L.is_tracked(root, call.rel):
        warns.append("not committed yet; first-commit and append-only checks start after the first commit")
        return errs, warns

    hist = L.history(root, call.rel)
    if not hist:
        warns.append("no history found; first-commit checks skipped")
        return errs, warns
    first_sha, first_date = hist[0]
    short = first_sha[:7]

    # made_on must equal the first commit's date
    date_mismatch = False
    if L.is_date(call.meta.get("made_on")) and L.to_date(call.meta["made_on"]).isoformat() != first_date:
        date_mismatch = True
        errs.append(f"made_on: is {L.to_date(call.meta['made_on'])}, but the file was first committed on "
                    f"{first_date} ({short}); the commit date wins")

    # frozen fields must equal their first-commit values
    first_text = L.file_at(root, first_sha, call.rel)
    try:
        first_meta, _, _ = L.split_front_matter(first_text or "")
    except ValueError as e:
        errs.append(f"first commit {short} could not be parsed: {e}")
        first_meta = None
    if first_meta is not None:
        for f in L.FROZEN:
            if f == "made_on" and date_mismatch:
                continue
            if L.normalize(call.meta.get(f)) != L.normalize(first_meta.get(f)):
                errs.append(f"{f}: differs from the first commit ({short}); published calls are frozen. "
                            f"To correct it, add a new call with supersedes: {call.id}")

    # previous version: the working tree vs HEAD if dirty, else HEAD vs the commit before it
    if L.working_tree_differs(root, call.rel):
        prev_sha = hist[-1][0]
    elif len(hist) >= 2:
        prev_sha = hist[-2][0]
    else:
        prev_sha = None
    if prev_sha:
        prev_text = L.file_at(root, prev_sha, call.rel)
        try:
            prev_meta, _, _ = L.split_front_matter(prev_text or "")
        except ValueError:
            prev_meta = None
        if prev_meta is not None:
            pshort = prev_sha[:7]
            # updates is append-only, newest first: the old list must be the tail of the new one
            prev_u = L.normalize(prev_meta.get("updates") or [])
            cur_u = L.normalize(call.meta.get("updates") or [])
            if len(cur_u) < len(prev_u) or cur_u[len(cur_u) - len(prev_u):] != prev_u:
                errs.append(f"updates: entries from {pshort} were changed or removed; the log is append-only "
                            "(add new entries at the top, never edit old ones)")
            # set-once fields
            for f in L.SET_ONCE:
                if prev_meta.get(f) not in (None, "", []) and \
                        L.normalize(prev_meta.get(f)) != L.normalize(call.meta.get(f)):
                    errs.append(f"{f}: was set in {pshort} and is set once; it cannot change")
            # a resolved call stays resolved, with the same status
            prev_status = str(prev_meta.get("status", "")).strip()
            if prev_status in L.RESOLVED_STATUSES and call.status != prev_status:
                errs.append(f"status: was {prev_status} in {pshort}; a resolved call cannot change status")
    return errs, warns


def check_deleted(root: pathlib.Path) -> list[str]:
    """Every call ever committed must still exist. Deleting one would drop a miss from the scores.
    Returns full ERROR lines."""
    errs: list[str] = []
    out = L.git(root, "log", "--no-renames", "--diff-filter=A", "--format=@%h", "--name-only", "--", "calls/")
    added: dict[str, str] = {}
    sha = ""
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("@"):
            sha = line[1:]
        elif line.endswith(".md") and not pathlib.PurePosixPath(line).name.startswith("_"):
            added[line] = sha  # log is newest first, so this ends on the first add
    for rel, add_sha in sorted(added.items()):
        if (root / rel).is_file():
            continue
        gone = L.git(root, "log", "-1", "--no-renames", "--diff-filter=D", "--format=%h", "--", rel, check=False)
        where = f"deleted in {gone}" if gone else "deleted in the working tree"
        restore = f"git checkout {gone}^ -- {rel}" if gone else f"git checkout HEAD -- {rel}"
        errs.append(f"ERROR {rel}: file: was published in {add_sha} and {where}; published calls are never deleted "
                    f"(void or retract it instead). Restore it with: {restore}")
    return errs


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", help="ledger repository root (default: parent of scripts/)")
    ap.add_argument("--check-examples", action="store_true", help="also validate _*.md files (schema only)")
    ap.add_argument("--no-git", action="store_true", help="skip first-commit, append-only and deletion checks")
    ap.add_argument("--quiet", action="store_true", help="print errors only")
    args = ap.parse_args(argv)

    root = L.repo_root(args.root)
    today = dt.date.today()
    paths = L.call_paths(root, include_examples=args.check_examples)
    if not paths:
        gone = check_deleted(root) if not args.no_git and L.is_git_repo(root) else []
        for e in gone:
            print(e)
        if gone:
            print(f"\n{len(gone)} error(s). The deploy is blocked until they are fixed.")
            return 1
        print(f"no calls found under {root / 'calls'}")
        return 0

    calls: list[L.Call] = []
    errors: list[str] = []
    warnings: list[str] = []
    for p in paths:
        try:
            calls.append(L.load_call(root, p))
        except (ValueError, UnicodeDecodeError) as e:
            errors.append(f"ERROR {L.rel(root, p)}: front matter: {e}")

    all_ids = {c.id for c in calls if not c.is_example}
    use_git = not args.no_git and L.is_git_repo(root)
    if not args.no_git and not use_git:
        warnings.append(f"WARN {root}: not a git repository; immutability checks skipped")

    seen: dict[str, str] = {}
    for c in calls:
        errs, warns = check_schema(c, all_ids, root, today)
        if use_git and not c.is_example:
            e2, w2 = check_git(c, root)
            errs += e2
            warns += w2
        if not c.is_example:
            cid = str(c.meta.get("id", "")).strip()
            if cid in seen:
                errs.append(f"id: {cid} is also used by {seen[cid]}")
            seen[cid] = c.rel
        errors += [f"ERROR {c.rel}: {e}" for e in errs]
        warnings += [f"WARN {c.rel}: {w}" for w in warns]

    if use_git:
        errors += check_deleted(root)

    if not args.quiet:
        for w in warnings:
            print(w)
    for e in errors:
        print(e)
    n = len([c for c in calls if not c.is_example])
    if errors:
        print(f"\n{len(errors)} error(s) in {n} call(s). The deploy is blocked until they are fixed.")
        return 1
    print(f"OK: {n} call(s) valid" + (f", {len(calls) - n} example(s) checked" if len(calls) != n else "")
          + (f", {len(warnings)} warning(s)" if warnings else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
