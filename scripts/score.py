#!/usr/bin/env python3
"""Compute the ledger's headline numbers and write scores.json.

Reads calls/*.md (skipping _*.md) and prior/*.md. Never fails the build: with
no resolved calls it writes nulls, which the index renders as an em dash.

Scoring (from the page spec):
  - A call resolved YES or NO contributes (p - o)^2, p = confidence/100,
    o = 1 for YES and 0 for NO. Lower is better.
  - A retracted call scores as NO at its stated confidence.
  - Void calls count toward the void rate and nothing else.
  - Hit rate = hits / (YES + NO + retracted), where a hit is a YES called at
    50% or more, or a NO called under 50%.
  - Prior-page entries are scored on their own and never pooled.

Usage:
  python scripts/score.py                       # writes <root>/scores.json
  python scripts/score.py --out path/scores.json
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sys
from collections import defaultdict

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import ledgerlib as L  # noqa: E402


def score_calls(root: pathlib.Path, calls: list[L.Call], use_git: bool) -> dict:
    per_call: dict[str, dict] = {}
    hits = 0
    scored = 0
    brier_sum = 0.0
    counts = defaultdict(int)
    cal: dict[int, dict] = defaultdict(lambda: {"n": 0, "yes": 0})

    for c in calls:
        status = c.status
        counts[status] += 1
        conf = c.meta.get("confidence")
        conf = conf if isinstance(conf, int) and not isinstance(conf, bool) else None
        result = L.RESULT_FOR_STATUS.get(status)
        brier = hit = None
        if result in ("YES", "NO") and conf is not None:
            brier = L.brier_contribution(conf, result)
            hit = L.is_hit(conf, result)
            scored += 1
            brier_sum += brier
            hits += int(hit)
            cal[conf]["n"] += 1
            cal[conf]["yes"] += int(result == "YES")
        resolved_on = L.resolution_date(root, c.rel) if (use_git and status in L.RESOLVED_STATUSES) else None
        per_call[c.id] = {
            "status": status,
            "confidence": conf,
            "made_on": L.normalize(c.meta.get("made_on")),
            "resolves_on": L.normalize(c.meta.get("resolves_on")),
            "resolved_on": resolved_on,
            "result": result,
            "hit": hit,
            "brier": brier,
        }

    made = len(calls)
    voids = counts["void"]
    return {
        "calls_made": made,
        "open": counts["open"],
        "flagged": counts["flagged"],
        "resolved_yes": counts["resolved_yes"],
        "resolved_no": counts["resolved_no"],
        "retracted": counts["retracted"],
        "void": voids,
        "resolved": scored,
        "hits": hits,
        "hit_rate": round(hits / scored, 4) if scored else None,
        "brier": round(brier_sum / scored, 4) if scored else None,
        "brier_n": scored,
        "void_rate": round(voids / made, 4) if made else None,
        "void_flag": bool(made and voids / made > 0.10),
        "calibration": [
            {"confidence": k, "n": v["n"], "observed": round(v["yes"] / v["n"], 4)}
            for k, v in sorted(cal.items())
        ],
        "calibration_ready": scored >= 20,
        "calls": per_call,
    }


def score_prior(root: pathlib.Path) -> dict:
    """prior/*.md: date, call, outcome (YES/NO/VOID), optional confidence. Scored separately."""
    entries = []
    folder = root / "prior"
    if folder.is_dir():
        for p in sorted(folder.glob("*.md")):
            if p.name.startswith("_"):
                continue
            try:
                meta, _, _ = L.split_front_matter(p.read_text(encoding="utf-8"))
            except ValueError:
                continue
            entries.append(meta)
    hits = scored = 0
    brier_sum = 0.0
    brier_n = 0
    for e in entries:
        result = L.yes_no(e.get("outcome")) or ""
        if result not in ("YES", "NO"):
            continue
        scored += 1
        conf = e.get("confidence")
        if isinstance(conf, int) and not isinstance(conf, bool):
            hits += int(L.is_hit(conf, result))
            brier_sum += L.brier_contribution(conf, result)
            brier_n += 1
        else:
            hits += int(result == "YES")  # no stated probability: the call either came true or did not
    return {
        "entries": len(entries),
        "resolved": scored,
        "hits": hits,
        "hit_rate": round(hits / scored, 4) if scored else None,
        "brier": round(brier_sum / brier_n, 4) if brier_n else None,
        "brier_n": brier_n,
    }


def compute(root: pathlib.Path) -> dict:
    calls = L.load_calls(root)
    use_git = L.is_git_repo(root)
    out = {"generated_at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()}
    out.update(score_calls(root, calls, use_git))
    out["prior"] = score_prior(root)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", help="ledger repository root (default: parent of scripts/)")
    ap.add_argument("--out", help="where to write scores.json (default: <root>/scores.json)")
    args = ap.parse_args(argv)
    root = L.repo_root(args.root)
    scores = compute(root)
    out = pathlib.Path(args.out) if args.out else root / "scores.json"
    out.write_text(json.dumps(scores, indent=2) + "\n", encoding="utf-8")
    hr = f"{scores['hit_rate']:.0%}" if scores["hit_rate"] is not None else "—"
    br = f"{scores['brier']:.3f}" if scores["brier"] is not None else "—"
    print(f"scores.json: {scores['calls_made']} calls, {scores['resolved']} scored, "
          f"hit rate {hr}, Brier {br} (N={scores['brier_n']}), void {scores['void']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
