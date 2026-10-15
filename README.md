# VectorSpace Infrastructure — Forecast Ledger

The public, dated, scored record behind [vectorspaceinfra.com/ledger](https://vectorspaceinfra.com/ledger/).
One Markdown file per call; the site is built from this repository, so the page and the record cannot drift.

## Adding a call (Makho)

1. Copy `calls/_example.md` to `calls/FCB-YYYY-NNN.md` using the next number for the year.
2. Fill in every field. `made_on` is today; `confidence` is a whole percent in steps of 5.
3. Check it: `python scripts/validate.py`
4. Commit with the message `FCB-YYYY-NNN: <title>` and push to `main`.
5. It is live at `/ledger/FCB-YYYY-NNN/` in about three minutes. If the Action fails, its log names the field.

Published calls are frozen: the build refuses any change to `id`, `title`, `claim`, `made_on`, `resolves_on`,
`resolution_rule`, `confidence`, `consensus_at_time`, `thesis`, `leading_indicators`, `changes_my_mind`,
`implies_for` or `supersedes`. To correct one, add a new call with `supersedes: <old id>`.
`status`, `service` and `updates` (append at the top, newest first) can change; `outcome`, `score` and
`postmortem` are set once, at resolution.

## Resolving, flagging, correcting

- **Indicator check:** add an entry at the top of `updates` (`date`, `note`, optional `url`, optional `indicator: 1`).
- **Flag:** set `status: flagged` in the same commit as the update that explains why.
- **Resolve** (on `resolves_on` or within 14 days): archive the referee page first, then set `status`,
  `outcome` (with the archived link), `score` (`YES` / `NO` / `VOID`) and `postmortem` in one commit.
- **Retract or void** early: `status: retracted` or `status: void`, with `outcome`, `score` and `postmortem`.
- **Quarterly memo:** commit it to `memos/YYYY-Qn.md`, publish it as a Note, then `git tag YYYY-Qn && git push --tags`.

## Scripts

| Script | Does | Fails when |
| --- | --- | --- |
| `scripts/validate.py` | Schema checks plus the git-based immutability checks | Any error; prints `ERROR <file>: <field>: <why>` |
| `scripts/score.py` | Writes `scores.json`: calls made, resolved, hit rate, Brier (with N), void rate, calibration, prior-page numbers | Never |
| `scripts/build.py` | Renders `templates/` into static HTML (`--out`), copies `static/` | A template error |
| `scripts/archive.py` | Saves pages to the Wayback Machine and records the links in each call's `updates` (and `ARCHIVES.md` for the index) | A save fails |

`scripts/ledgerlib.py` holds the shared parsing and git helpers. Python 3.10+; `pip install -r requirements.txt`.

Local build: `python scripts/validate.py && python scripts/score.py && python scripts/build.py` then open `_site/ledger/index.html`.
Example files (`calls/_example.md`, `theses/_template.md`, `prior/_template.md`) start with `_` and are ignored by the build;
`python scripts/validate.py --check-examples` checks them against the schema.

## Deployment (Nova)

- **This repo:** `.github/workflows/deploy.yml` validates every push and, on `main`, POSTs to the site Worker's deploy hook
  (Workers & Pages → vectorspaceinfrasite → Settings → Builds → Deploy Hooks), stored in the repository secret `CF_DEPLOY_HOOK`.
- **Site repo** (`Vector-Space-Infra/vectorspaceinfrasite`, a Worker with static assets): its Workers Builds build command runs
  `cloudflare-build.sh` (copy it there), which clones this repo with full history and renders `/ledger/` into the assets
  directory; the deploy command stays `npx wrangler deploy`. Validation failure = no deploy.
- **After each deploy:** `python scripts/archive.py --commit` then push. It archives the index plus the calls changed in the
  last commit; `--all` for everything, `--dry-run` to see what it would do.
- Templates: `templates/base.html` carries the site chrome; replace its stub nav, footer and stylesheet links with the site's own.
  `static/ledger.css` has the ledger-only styles; `build.py` has `SERVICE_URLS` for the related-service links.

Never rebase, squash or force-push `main`, and never delete a call file.
