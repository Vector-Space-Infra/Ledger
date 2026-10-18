# VectorSpace Infrastructure — Forecast Ledger

The public, dated, scored record behind [vectorspaceinfra.com/ledger](https://vectorspaceinfra.com/ledger/).
One Markdown file per call; the site is built from this repository, so the page and the record cannot drift.

## Adding a call (Makho)

All in the browser on github.com; nothing to install.

1. Open `calls/_example.md` and click the copy icon above the text.
2. In `calls/`, choose **Add file → Create new file**. Name it `FCB-2026-NNN.md`, the next number for the year.
3. Paste, then replace every value. `id` matches the file name; `made_on` is today; `confidence` is a whole percent in steps of 5.
4. **Commit changes**, message `FCB-2026-NNN: <title>`, **Commit directly to the main branch**.
5. Open **Actions**. A green tick means the call is live at `/ledger/FCB-2026-NNN/` in about three minutes. A red cross
   means it did not publish: open the run, read the `ERROR` line (file and field), fix the file (pencil icon) and commit again.

A call is published by its first commit that passes every check; commits before that never deployed and can be
fixed freely. Published calls are frozen: the build refuses any change to `id`, `title`, `claim`, `made_on`, `resolves_on`,
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
- **Site repo** (`Vector-Space-Infra/vectorspaceinfrasite`, a Worker with static assets): its build command stays
  `npm run build`, and the site's `package.json` runs `tools/ledger.sh` after it (the `postbuild` script). That script
  clones this repo with full history, validates, scores and renders `/ledger/` into `_site/ledger`. Validation
  failure = the build fails = no deploy, and the live site stays as it was. No Cloudflare setting had to change.
- **After each deploy:** automatic. When a push changes a call, the workflow waits until the live call page matches
  the push, saves it and the ledger index to the Wayback Machine, commits the links (`archive: … [skip ci]`) and
  rebuilds the site. If that step fails (the Wayback Machine is often slow), open the run in Actions and click
  **Re-run failed jobs**. By hand instead: `python scripts/archive.py --commit`, push; the links appear at the next
  deploy. To test the step without saving anything: Actions → Validate and deploy → **Run workflow**.
- **Templates:** `templates/base.html` is the site's own head, header and footer (built from the site's About page on
  15 Oct 2026, with Calls current in the nav). When the site's nav, footer, fonts or analytics tags change, make the same
  change here, or the ledger pages fall out of step with the rest of the site.
  `static/ledger.css` holds only what the ledger adds; colours, type, header, footer and the filter buttons come from the
  site's `/assets/css/site.css`. The status chips are `.status-chip` (the site already uses `.chip`). `build.py` has
  `SERVICE_URLS`, the related-service links, keyed by the exact service names on the Services page.
- **Repository settings:** protect `main` (Settings → Branches: block force pushes and deletion). The immutability checks
  read git history, so rewritten history is the one change they cannot see.

Deleting a call file fails validation (`file: was published in … and deleted in …`); void or retract it instead.
Never rebase, squash or force-push `main`, and never delete a call file.
