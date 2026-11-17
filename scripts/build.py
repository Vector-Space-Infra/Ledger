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
    "Site and Power Connection Review": "/services/#site-power-review",
    "Lender Diligence Memo": "/services/#lender-memo",
    "Data Center Business Model Comparison": "/services/#business-model-comparison",
    "Customer Demand and Contract Assessment": "/services/#demand-contract-assessment",
    "Utility Application Guidance": "/services/#utility",
    "Commissioning Data & Turnover Support": "/services/#commissioning",
}

SITE_NAME = "VectorSpace Infrastructure"


def doc_title(title) -> str:
    """The <title>: the page's own title with the brand after it when the pair fits a search result
    line (63 characters), else the title alone. Same rule as the site's tools/seo.js docTitle."""
    t = " ".join(str(title or "").split())
    if not t:
        return SITE_NAME
    if SITE_NAME in t:
        return t
    full = f"{t} | {SITE_NAME}"
    return full if len(full) <= 63 else t


def iso_datetime(day: str) -> str | None:
    return f"{day}T00:00:00Z" if day else None


def schema_graph(base: str, path: str, page_type: str, name: str, description: str,
                 crumbs: list[tuple[str, str]], article: dict | None = None) -> str:
    """One JSON-LD @graph for a ledger page. The organization, website and founder are described in
    full on the site's own pages; here they are named by the same @id so search engines join them."""
    org_id, site_id, person_id = f"{base}/#organization", f"{base}/#website", f"{base}/about/#person"
    url = f"{base}{path}"
    trail = [("Home", "/"), *crumbs]
    nodes: list[dict] = [
        {"@type": ["Organization", "ProfessionalService"], "@id": org_id, "name": SITE_NAME, "url": f"{base}/",
         "logo": {"@type": "ImageObject", "url": f"{base}/assets/img/icon-512.png", "width": 512, "height": 512}},
        {"@type": "WebSite", "@id": site_id, "url": f"{base}/", "name": SITE_NAME, "publisher": {"@id": org_id}},
        {"@type": page_type, "@id": f"{url}#webpage", "url": url, "name": name, "description": description,
         "isPartOf": {"@id": site_id}, "about": {"@id": org_id}, "breadcrumb": {"@id": f"{url}#breadcrumb"},
         "inLanguage": "en-US"},
        {"@type": "BreadcrumbList", "@id": f"{url}#breadcrumb",
         "itemListElement": [{"@type": "ListItem", "position": i + 1, "name": n, "item": f"{base}{u}"}
                             for i, (n, u) in enumerate(trail)]},
    ]
    if article:
        nodes.append({"@type": "Person", "@id": person_id, "name": "Makho Mashoba", "url": f"{base}/about/",
                      "worksFor": {"@id": org_id}})
        nodes.append({k: v for k, v in {
            "@type": "Article", "@id": f"{url}#article", "headline": name[:110], "description": description,
            "datePublished": article.get("published"), "dateModified": article.get("modified"),
            "author": {"@id": person_id}, "publisher": {"@id": org_id},
            "image": [f"{base}/assets/img/og-calls.png"], "mainEntityOfPage": {"@id": f"{url}#webpage"},
            "inLanguage": "en-US",
        }.items() if v})
    return json.dumps({"@context": "https://schema.org", "@graph": nodes}, ensure_ascii=False).replace("<", "\\u003c")


def clip(text: str, n: int = 158) -> str:
    """Plain text cut to n characters at a word, for meta descriptions."""
    t = " ".join(str(text or "").split())
    if len(t) <= n:
        return t
    return t[: n - 1].rsplit(" ", 1)[0].rstrip(",;:") + "…"


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
        "doc_title": doc_title,
        "site_name": SITE_NAME,
    })
    base = args.base_url.rstrip("/")
    calls_crumb = ("Calls", "/ledger/")

    def write(relpath: str, html: str) -> None:
        p = out / relpath
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(html, encoding="utf-8")

    strip = resolved_this_quarter(root, ctx_calls, today, use_git)
    index_desc = ("A public, dated, scored record of our data center market forecasts. "
                  "Each call is frozen the day it is made, with its resolution rule named in advance.")
    write("index.html", env.get_template("index.html").render(
        schema=schema_graph(base, "/ledger/", "CollectionPage", "Data Center Market Forecast Ledger", index_desc, [calls_crumb]),
        calls=ctx_calls, strip=strip,
        years=sorted({c["horizon_year"] for c in ctx_calls if c["horizon_year"]}),
        thesis_slugs=sorted({c["thesis"] for c in ctx_calls if c["thesis"]}),
    ))
    for c in ctx_calls:
        c["description"] = clip(c["claim"])
        dates = [c["made_on"]] + [u["date"] for u in c["updates"] if u["date"]]
        c["modified_on"] = max(d for d in dates if d) if any(dates) else ""
        write(f"{c['id']}/index.html", env.get_template("call.html").render(
            call=c,
            schema=schema_graph(base, c["url"], "WebPage", c["title"], c["description"], [calls_crumb, (c["title"], c["url"])],
                                article={"published": iso_datetime(c["made_on"]), "modified": iso_datetime(c["modified_on"])}),
        ))

    method_md = (root / "METHOD.md")
    method_desc = "How the VectorSpace Infrastructure forecast ledger writes, timestamps, resolves and scores its calls, including the Brier score and the void rule."
    write("method/index.html", env.get_template("method.html").render(
        schema=schema_graph(base, "/ledger/method/", "WebPage", "Forecast Ledger Method", method_desc,
                            [calls_crumb, ("Method", "/ledger/method/")]),
        description=method_desc,
        body_html=md(method_md.read_text(encoding="utf-8") if method_md.exists() else "_METHOD.md is missing._")))
    for t in theses:
        t_desc = clip(t.get("summary") or f"Calls in the ledger that test the thesis: {t['title']}.")
        write(f"thesis/{t['slug']}/index.html", env.get_template("thesis.html").render(
            thesis=t, description=t_desc,
            schema=schema_graph(base, t["url"], "CollectionPage", t["title"], t_desc, [calls_crumb, (t["title"], t["url"])])))
    if prior:
        p_desc = ("Technology and macro calls made before the ledger existed, with the post that dates each one "
                  "and the source that resolved it. Scored on their own.")
        write("prior/index.html", env.get_template("prior.html").render(
            prior=prior, prior_scores=scores.get("prior", {}), description=p_desc,
            schema=schema_graph(base, "/ledger/prior/", "CollectionPage", "Prior Calls", p_desc, [calls_crumb, ("Prior calls", "/ledger/prior/")])))

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
