#!/usr/bin/env python3
"""Wait until the live site serves the pages this commit builds, so archive.py saves the new version.

Compares each live page with the same page built locally from this commit (build.py output). They match
byte for byte once Cloudflare has deployed, apart from the Web Analytics beacon script Cloudflare adds to
some responses, which is removed before comparing. Standard library only.

Usage:
  python scripts/wait_for_deploy.py --built _built --paths /ledger/FCB-2026-001/ [--timeout 600]
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys
import time
import urllib.error
import urllib.request


# Cloudflare answers Python's default user agent with 403, so the script names itself
UA = "vectorspace-ledger-deploycheck/1.0 (+https://vectorspaceinfra.com/ledger/)"


# Cloudflare adds its Web Analytics beacon to some responses; it is not part of the built page
BEACON = re.compile(rb'<script[^>]*static\.cloudflareinsights\.com[^>]*>\s*</script>\s*')


def fetch(url: str) -> bytes | None:
    req = urllib.request.Request(f"{url}?deploycheck={int(time.time())}",
                                 headers={"Cache-Control": "no-cache", "User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return BEACON.sub(b"", r.read())
    except (urllib.error.URLError, TimeoutError):
        return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-url", default="https://vectorspaceinfra.com")
    ap.add_argument("--built", required=True, help="folder build.py wrote into (holds ledger/...)")
    ap.add_argument("--paths", nargs="+", required=True, help="site paths, e.g. /ledger/FCB-2026-001/")
    ap.add_argument("--timeout", type=int, default=600, help="seconds before giving up (default 600)")
    ap.add_argument("--interval", type=int, default=15)
    args = ap.parse_args(argv)

    base = args.base_url.rstrip("/")
    want = {}
    for path in args.paths:
        f = pathlib.Path(args.built) / path.strip("/") / "index.html"
        if not f.is_file():
            print(f"not built: {f}")
            return 1
        want[path] = f.read_bytes()

    deadline = time.time() + args.timeout
    waiting = set(want)
    while waiting:
        for path in sorted(waiting):
            if fetch(base + path) == want[path]:
                print(f"live: {base}{path}")
                waiting.discard(path)
        if not waiting:
            break
        if time.time() > deadline:
            print(f"the site did not serve this version within {args.timeout}s: {', '.join(sorted(waiting))}. "
                  "Check the Cloudflare build log (Workers & Pages > vectorspaceinfrasite > Deployments)")
            return 1
        time.sleep(args.interval)
    return 0


if __name__ == "__main__":
    sys.exit(main())
