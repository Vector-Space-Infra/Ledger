#!/usr/bin/env bash
# Build command for the SITE repository (Vector-Space-Infra/vectorspaceinfrasite), which deploys as a
# Cloudflare Worker with static assets through Workers Builds. Copy this file into the site repo, then in
# the Worker's Settings > Builds set:  Build command: bash cloudflare-build.sh   Deploy command: npx wrangler deploy
# It clones the ledger with full history, renders /ledger/ into the Worker's assets directory, and fails
# the build (so nothing deploys) if validation fails. OUT must be <assets directory>/ledger, where the
# assets directory is the one named in the site's wrangler config; ./ledger is right when assets are the repo root.
set -euo pipefail

LEDGER_REPO="${LEDGER_REPO:-https://github.com/Vector-Space-Infra/ledger.git}"
BASE_URL="${BASE_URL:-https://vectorspaceinfra.com}"
OUT="${OUT:-./ledger}"                      # where /ledger/ should appear in the deployed output
WORK="${WORK:-.ledger-src}"

rm -rf "$WORK"
git clone --quiet "$LEDGER_REPO" "$WORK"    # no --depth: the first-commit check needs history
python3 -m pip install --quiet -r "$WORK/requirements.txt"
python3 "$WORK/scripts/validate.py" --root "$WORK"
python3 "$WORK/scripts/score.py"    --root "$WORK"
python3 "$WORK/scripts/build.py"    --root "$WORK" --out "$OUT" --base-url "$BASE_URL"
rm -rf "$WORK"
echo "ledger rendered into $OUT"
