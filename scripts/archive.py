#!/usr/bin/env python3
"""Save ledger pages to the Wayback Machine and record the archive links.

Run after each deploy. For every call archived, a dated entry is added at the
top of that call's `updates` list (the file text is edited in place, nothing
else in the file is touched); the index and other non-call pages are logged
in ARCHIVES.md. Pass --commit to commit the result.

Usage:
  python scripts/archive.py                      # index + calls changed in the last commit
  python scripts/archive.py --calls FCB-2026-001 FCB-2026-002
  python scripts/archive.py --all                # every call
  python scripts/archive.py --no-index           # skip the ledger index
  python scripts/archive.py --commit             # also git add + commit
  python scripts/archive.py --dry-run            # no network, no commit; shows what would change

The Wayback Machine rate-limits anonymous saves; the script waits between
pages and retries a few times. Archiving ten pages takes a couple of minutes.
"""
from __future__ import annotations

import argparse
import datetime as dt
import pathlib
import re
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import ledgerlib as L  # noqa: E402

SAVE = "https://web.archive.org/save/"
UA = "vectorspace-ledger-archive/1.0 (+https://vectorspaceinfra.com/ledger/)"


def wayback_save(url: str, tries: int = 3, wait: int = 20) -> str | None:
    """Ask the Wayback Machine to save `url`; return the archived copy's URL or None."""
    for attempt in range(1, tries + 1):
        req = urllib.request.Request(SAVE + url, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                loc = resp.headers.get("Content-Location") or ""
                if loc.startswith("/web/"):
                    return "https://web.archive.org" + loc
                final = resp.geturl()
                if "/web/" in final:
                    return final
                link = resp.headers.get("Link") or ""
                m = re.search(r"<(https://web\.archive\.org/web/\d+/[^>]+)>;\s*rel=\"memento\"", link)
                if m:
                    return m.group(1)
                print(f"  saved but no archive URL in the response for {url}; check web.archive.org manually")
                return None
        except urllib.error.HTTPError as e:
            if e.code in (429, 502, 503, 504) and attempt < tries:
                print(f"  {e.code} from web.archive.org, waiting {wait * attempt}s (attempt {attempt}/{tries})")
                time.sleep(wait * attempt)
                continue
            print(f"  failed: HTTP {e.code} for {url}")
            return None
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt < tries:
                print(f"  {e}, waiting {wait * attempt}s (attempt {attempt}/{tries})")
                time.sleep(wait * attempt)
                continue
            print(f"  failed: {e}")
            return None
    return None


def yaml_str(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def add_update(text: str, date: str, note: str, url: str) -> str:
    """Insert a new entry at the top of the front matter's `updates` list, editing only that spot."""
    m = re.match(r"^(---[ \t]*\r?\n)(.*?)(\r?\n---[ \t]*(?:\r?\n|$))(.*)$", text, re.S)
    if not m:
        raise ValueError("no front matter block")
    head, front, close, body = m.groups()
    lines = front.split("\n")
    entry = lambda ind: [f"{ind}- date: {date}", f"{ind}  note: {yaml_str(note)}", f"{ind}  url: {yaml_str(url)}"]

    for i, line in enumerate(lines):
        if re.match(r"^updates:\s*\[\s*\]\s*(#.*)?$", line):              # updates: []
            lines[i:i + 1] = ["updates:"] + entry("  ")
            break
        if re.match(r"^updates:\s*(#.*)?$", line):                          # updates: (block list follows)
            ind = "  "
            for nxt in lines[i + 1:]:
                mm = re.match(r"^(\s*)- ", nxt)
                if mm:
                    ind = mm.group(1)
                break
            lines[i + 1:i + 1] = entry(ind)
            break
    else:                                                                  # no updates key at all
        lines += ["updates:"] + entry("  ")
    new_text = head + "\n".join(lines) + close + body
    # Prove the edit parsed and grew the list by one before returning it.
    old_meta, _, _ = L.split_front_matter(text)
    new_meta, _, _ = L.split_front_matter(new_text)
    if len(new_meta.get("updates") or []) != len(old_meta.get("updates") or []) + 1:
        raise ValueError("the updates list did not grow by exactly one entry; file left unchanged")
    return new_text


def changed_call_ids(root: pathlib.Path) -> list[str]:
    """Call ids touched by the last commit; every call if there is only one commit."""
    if not L.is_git_repo(root):
        return [p.stem for p in L.call_paths(root)]
    if L.git(root, "rev-parse", "--verify", "--quiet", "HEAD~1", check=False) == "":
        return [p.stem for p in L.call_paths(root)]
    out = L.git(root, "diff", "--name-only", "HEAD~1", "HEAD", "--", "calls/")
    ids = []
    for line in out.splitlines():
        p = pathlib.Path(line)
        if p.suffix == ".md" and not p.name.startswith("_") and (root / p).exists():
            ids.append(p.stem)
    return ids


def log_line(root: pathlib.Path, date: str, page: str, archive: str) -> None:
    log = root / "ARCHIVES.md"
    if not log.exists():
        log.write_text("# Archived pages\n\nWayback Machine captures of non-call pages, newest last.\n\n"
                       "| Date | Page | Archive |\n| --- | --- | --- |\n", encoding="utf-8")
    with log.open("a", encoding="utf-8") as f:
        f.write(f"| {date} | {page} | {archive} |\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", help="ledger repository root (default: parent of scripts/)")
    ap.add_argument("--base-url", default="https://vectorspaceinfra.com")
    ap.add_argument("--calls", nargs="*", metavar="ID", help="call ids to archive")
    ap.add_argument("--all", action="store_true", help="archive every call")
    ap.add_argument("--no-index", action="store_true", help="do not archive the ledger index")
    ap.add_argument("--pages", nargs="*", default=[], metavar="PATH",
                    help="extra site paths to archive and log, e.g. /ledger/method/")
    ap.add_argument("--wait", type=int, default=8, help="seconds between saves (default 8)")
    ap.add_argument("--commit", action="store_true", help="git add + commit the recorded links")
    ap.add_argument("--dry-run", action="store_true", help="no network, no commit; print the planned edits")
    args = ap.parse_args(argv)

    root = L.repo_root(args.root)
    base = args.base_url.rstrip("/")
    today = dt.date.today().isoformat()

    if args.all:
        ids = [p.stem for p in L.call_paths(root)]
    elif args.calls:
        ids = args.calls
    else:
        ids = changed_call_ids(root)
    missing = [i for i in ids if not (root / "calls" / f"{i}.md").exists()]
    if missing:
        print(f"no such call(s): {', '.join(missing)}")
        return 1

    pages: list[tuple[str, str | None]] = []           # (site path, call id or None)
    if not args.no_index:
        pages.append(("/ledger/", None))
    pages += [(p if p.startswith("/") else "/" + p, None) for p in args.pages]
    pages += [(f"/ledger/{i}/", i) for i in ids]
    if not pages:
        print("nothing to archive")
        return 0

    touched: list[pathlib.Path] = []
    failures = 0
    for n, (path, cid) in enumerate(pages, 1):
        url = base + path
        print(f"[{n}/{len(pages)}] {url}")
        if args.dry_run:
            archive = f"https://web.archive.org/web/{dt.datetime.now(dt.timezone.utc):%Y%m%d%H%M%S}/{url}"
            print(f"  (dry run) would save; using placeholder {archive}")
        else:
            archive = wayback_save(url)
            if n < len(pages):
                time.sleep(args.wait)
        if not archive:
            failures += 1
            continue
        if cid:
            f = root / "calls" / f"{cid}.md"
            new_text = add_update(f.read_text(encoding="utf-8"), today, f"Archived call page {path}", archive)
            if args.dry_run:
                print(f"  (dry run) would add an updates entry to {f.relative_to(root)}")
            else:
                f.write_text(new_text, encoding="utf-8")
                touched.append(f)
                print(f"  recorded in {f.relative_to(root)}")
        else:
            if args.dry_run:
                print(f"  (dry run) would log in ARCHIVES.md")
            else:
                log_line(root, today, path, archive)
                touched.append(root / "ARCHIVES.md")
                print("  logged in ARCHIVES.md")

    if args.commit and touched and not args.dry_run:
        names = ", ".join(sorted({p.stem for p in touched if p.parent.name == "calls"})) or "index"
        L.git(root, "add", *[str(p.relative_to(root)) for p in touched])
        # "[skip ci]": the push starts no workflow run of its own (the deploy workflow rebuilds the site itself)
        L.git(root, "commit", "-m", f"archive: {names} ({today}) [skip ci]")
        print(f"committed; push when ready")
    if failures:
        print(f"{failures} page(s) not archived; rerun with --calls for those ids")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
