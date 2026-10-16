#!/usr/bin/env python3
"""Render the ledger into static HTML.

Reads calls/, theses/, prior/, METHOD.md, scores.json and templates/, and writes:
  <out>/index.html                       the ledger index
  <out>/<id>/index.html                  one page per call
  <out>/method/index.html                the method note
  <out>/thesis/<slug>/index.html         one page per thesis (if theses/ has files)
  <out>/prior/index.html                 the prior-calls page (if prior/ has files)
  <out>/ledger.css, <out>/ledger.js      copied from static/

Run validate.py first; this script does not re-validate. If scores.json is
missing it computes the scores itself.

Usage:
  python scripts/build.py --out ./ledger --base-url https://vectorspaceinfra.com
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import shutil
import sys

import markdown
from jinja2 import Environment, FileSystemLoader, select_autoescape

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import ledgerlib as L  # noqa: E402
import score as scoremod  # noqa: E402
import validate  # noqa: E402

# Each service name, as written in a call's `service` field, mapped to its section on the site's
# Services page (ids from the site's src/_data/services.json). Unknown names link to /services/.
SERVICE_URLS = {
    "Site and Power Connection Review": "/services/#line-01",
    "Lender Diligence Memo": "/services/#lender-memo",
    "Data Center Business Model Comparison": "/services/#line-02",
    "Customer Demand and Contract Assessment": "/services/#line-03",
    "Utility Application Guidance": "/services/#utility",
    "Commissioning Data & Turnover Support": "/services/#commissioning",
}

MD = markdown.Markdown(extensions=["tables", "fenced_code", "sane_lists"])


def md(text: str | None) -> str:
    MD.reset()
    return MD.convert(text or "")


def fmt_date(v) -> str:
    try:
        return L.to_date(v).isoformat()
    except (ValueError, TypeError):
        return ""


def call_context(call: L.Call, root: pathlib.Path, scores: dict, use_git: bool,
                 repo_url: str, superseded_by: dict[str, list[str]]) -> dict:
    m = call.meta
    s = scores.get("calls", {}).get(call.id, {})
    status = call.status
    updates = []
    for u in m.get("updates") or []:
        updates.append({
            "date": fmt_date(u.get("date")),
            "note": str(u.get("note", "")),
            "url": u.get("url"),
            "indicator": u.get("indicator"),
        })
    indicators = []
    for i, ind in enumerate(m.get("leading_indicators") or [], 1):
        latest = next((u for u in updates if u["indicator"] == i), None)  # updates are newest first
        indicators.append({"n": i, "what": ind.get("what", ""), "cadence": ind.get("cadence", ""), "latest": latest})
    wayback = next((u["url"] for u in updates if str(u.get("url", "")).startswith("https://web.archive.org/")), None)
    pub = validate.publication(root, call) if use_git else None  # (index, sha, date)
    first = pub[1:] if pub else None
    conf = m.get("confidence")
    return {
        "id": call.id,
        "title": m.get("title", ""),
        "claim": str(m.get("claim", "")).strip(),
        "made_on": fmt_date(m.get("made_on")),
        "resolves_on": fmt_date(m.get("resolves_on")),
        "horizon_year": fmt_date(m.get("resolves_on"))[:4],
        "resolution_rule": str(m.get("resolution_rule", "")).strip(),
        "confidence": conf,
        "consensus": m.get("consensus_at_time") or [],
        "thesis": str(m.get("thesis", "")).strip(),
        "indicators": indicators,
        "changes_my_mind": str(m.get("changes_my_mind", "")).strip(),
        "implies_for": m.get("implies_for") or [],
        "service": m.get("service"),
        "service_url": SERVICE_URLS.get(str(m.get("service", "")).strip(), "/services/"),
        "status": status,
        "status_label": L.STATUS_LABEL.get(status, status),
        "status_group": L.STATUS_GROUP.get(status, ""),
        "updates": updates,
        "outcome": str(m.get("outcome") or "").strip(),
        "postmortem": str(m.get("postmortem") or "").strip(),
        "result": s.get("result"),
        "brier": s.get("brier"),
        "hit": s.get("hit"),
        "resolved_on": s.get("resolved_on"),
        "supersedes": m.get("supersedes"),
        "superseded_by": superseded_by.get(call.id, []),
        "first_sha": first[0] if first else None,
        "first_short": first[0][:7] if first else None,
        "commit_url": f"{repo_url}/commit/{first[0]}" if first else None,
        "wayback_url": wayback,
        "body_html": md(call.body),
        "url": f"/ledger/{call.id}/",
    }


def load_theses(root: pathlib.Path) -> list[dict]:
    out = []
    folder = root / "theses"
    if folder.is_dir():
        for p in sorted(folder.glob("*.md")):
            if p.name.startswith("_"):
                continue
            meta, body, _ = L.split_front_matter(p.read_text(encoding="utf-8"))
            out.append({"slug": p.stem, "title": meta.get("title", p.stem), "body_html": md(body),
                        "url": f"/ledger/thesis/{p.stem}/"})
    return out


def load_prior(root: pathlib.Path) -> list[dict]:
    out = []
    folder = root / "prior"
    if folder.is_dir():
        for p in sorted(folder.glob("*.md"), reverse=True):
            if p.name.startswith("_"):
                continue
            meta, body, _ = L.split_front_matter(p.read_text(encoding="utf-8"))
            links = meta.get("links") or {}
            out.append({
                "date": fmt_date(meta.get("date")),
                "call": str(meta.get("call", "")).strip(),
                "outcome": L.yes_no(meta.get("outcome")) or "",
                "happened": str(meta.get("happened", "")).strip(),
                "confidence": meta.get("confidence"),
                "call_link": links.get("call"),
                "outcome_link": links.get("outcome"),
                "body_html": md(body),
            })
    return out


def resolved_this_quarter(root: pathlib.Path, calls: list[dict], today: dt.date, use_git: bool) -> dict | None:
    """The strip above the table: shown for 30 days after each quarterly memo's tag."""
    if not use_git:
        return None
    tag = L.latest_quarter_tag(root)
    if not tag:
        return None
    name, date = tag
    tag_date = dt.date.fromisoformat(date)
    if not (tag_date <= today <= tag_date + dt.timedelta(days=30)):
        return None
    start, end = L.quarter_bounds(name)
    rows = [c for c in calls if c["resolved_on"] and start <= dt.date.fromisoformat(c["resolved_on"]) <= end]
    return {"tag": name, "date": date, "quarter": name, "calls": rows}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", help="ledger repository root (default: parent of scripts/)")
    ap.add_argument("--out", help="output folder (default: <root>/_site/ledger)")
    ap.add_argument("--base-url", default="https://vectorspaceinfra.com", help="site origin, for absolute links")
    ap.add_argument("--repo-url", default="https://github.com/Vector-Space-Infra/ledger")
    ap.add_argument("--scores", help="scores.json to use (default: <root>/scores.json, computed if missing)")
    args = ap.parse_args(argv)

    root = L.repo_root(args.root)
    out = pathlib.Path(args.out).resolve() if args.out else root / "_site" / "ledger"
    use_git = L.is_git_repo(root)
    today = dt.date.today()

    scores_path = pathlib.Path(args.scores) if args.scores else root / "scores.json"
    if scores_path.exists():
        scores = json.loads(scores_path.read_text(encoding="utf-8"))
    else:
        scores = scoremod.compute(root)

    calls = L.load_calls(root)
    superseded_by: dict[str, list[str]] = {}
    for c in calls:
        sup = c.meta.get("supersedes")
        if sup:
            superseded_by.setdefault(str(sup).strip(), []).append(c.id)
    ctx_calls = [call_context(c, root, scores, use_git, args.repo_url, superseded_by) for c in calls]
    ctx_calls.sort(key=lambda c: (c["made_on"], c["id"]), reverse=True)
    theses = load_theses(root)
    for t in theses:
        t["calls"] = [c for c in ctx_calls if c["thesis"] == t["slug"]]
    thesis_urls = {t["slug"]: t["url"] for t in theses}
    for c in ctx_calls:
        c["thesis_url"] = thesis_urls.get(c["thesis"])
    prior = load_prior(root)

    tag = L.latest_quarter_tag(root) if use_git else None
    env = Environment(loader=FileSystemLoader(str(root / "templates")),
                      autoescape=select_autoescape(["html"]), trim_blocks=True, lstrip_blocks=True)
    env.globals.update({
        "base_url": args.base_url.rstrip("/"),
        "repo_url": args.repo_url,
        "latest_tag": {"name": tag[0], "date": tag[1], "url": f"{args.repo_url}/releases/tag/{tag[0]}"} if tag else None,
        "today": today.isoformat(),
        "scores": scores,
        "theses": theses,
        "has_prior": bool(prior),
        "status_labels": L.STATUS_LABEL,
    })

    def write(relpath: str, html: str) -> None:
        p = out / relpath
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(html, encoding="utf-8")

    strip = resolved_this_quarter(root, ctx_calls, today, use_git)
    write("index.html", env.get_template("index.html").render(
        calls=ctx_calls, strip=strip,
        years=sorted({c["horizon_year"] for c in ctx_calls if c["horizon_year"]}),
        thesis_slugs=sorted({c["thesis"] for c in ctx_calls if c["thesis"]}),
    ))
    for c in ctx_calls:
        write(f"{c['id']}/index.html", env.get_template("call.html").render(call=c))

    method_md = (root / "METHOD.md")
    write("method/index.html", env.get_template("method.html").render(
        body_html=md(method_md.read_text(encoding="utf-8") if method_md.exists() else "_METHOD.md is missing._")))
    for t in theses:
        write(f"thesis/{t['slug']}/index.html", env.get_template("thesis.html").render(thesis=t))
    if prior:
        write("prior/index.html", env.get_template("prior.html").render(prior=prior, prior_scores=scores.get("prior", {})))

    static = root / "static"
    if static.is_dir():
        for f in static.iterdir():
            if f.is_file():
                shutil.copy2(f, out / f.name)

    print(f"built {len(ctx_calls)} call page(s), {len(theses)} thesis page(s)"
          f"{', prior page' if prior else ''}, method note -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
