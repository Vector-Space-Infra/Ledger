#!/usr/bin/env bash
# Pins a ledger commit in the site repository: writes its full hash to ledger.lock at the site's
# root and pushes that as an ordinary commit ("Ledger: pin abc1234") to the site's main branch.
# That push is what makes Cloudflare rebuild the site, and the site's tools/ledger.sh then builds
# exactly the pinned ledger commit. (A deploy-hook request for an unchanged site repository was
# accepted but often not built, so the workflow no longer sends one.)
#
# Usage, from the ledger repository's root:  scripts/pin_site.sh <full ledger commit hash>
#
# Needs SITE_REPO_TOKEN: a fine-grained GitHub token with Contents read/write on the site repository
# only. For testing, SITE_REMOTE can name any other remote (a local bare repository) instead.
# A pin never moves backwards: if the site already pins this commit or a later one, nothing is pushed.
# If the site's main moved between clone and push, it starts again from a fresh clone (3 tries).
set -euo pipefail

SHA="${1:-}"
if ! [[ "$SHA" =~ ^[0-9a-f]{40}$ ]]; then
  echo "pin_site.sh: expected one full ledger commit hash, got '${SHA}'"
  exit 1
fi
if [ -z "${SITE_REMOTE:-}" ]; then
  if [ -z "${SITE_REPO_TOKEN:-}" ]; then
    echo "SITE_REPO_TOKEN secret is not set (Settings > Secrets and variables > Actions in the ledger repository)"
    exit 1
  fi
  SITE_REMOTE="https://x-access-token:${SITE_REPO_TOKEN}@github.com/${SITE_REPO:-Vector-Space-Infra/vectorspaceinfrasite}.git"
fi
BRANCH="${SITE_BRANCH:-main}"
LEDGER_DIR="$(pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# The ledger commit pushed by this same run (an archive commit) is already local; others may not be
git -C "$LEDGER_DIR" fetch --quiet origin main 2>/dev/null || true

for attempt in 1 2 3; do
  rm -rf "$WORK/site"
  git clone --quiet --depth 1 --branch "$BRANCH" "$SITE_REMOTE" "$WORK/site"
  current=""
  [ -f "$WORK/site/ledger.lock" ] && current="$(tr -d '[:space:]' < "$WORK/site/ledger.lock")"
  if [ "$current" = "$SHA" ]; then
    echo "the site already pins ${SHA:0:7}"
    exit 0
  fi
  if [[ "$current" =~ ^[0-9a-f]{40}$ ]] && git -C "$LEDGER_DIR" merge-base --is-ancestor "$SHA" "$current" 2>/dev/null; then
    echo "the site already pins ${current:0:7}, which includes ${SHA:0:7}; leaving it"
    exit 0
  fi
  echo "$SHA" > "$WORK/site/ledger.lock"
  git -C "$WORK/site" add ledger.lock
  git -C "$WORK/site" -c user.name="ledger-bot" -c user.email="ledger-bot@users.noreply.github.com" \
    commit --quiet -m "Ledger: pin ${SHA:0:7}"
  if git -C "$WORK/site" push --quiet origin "HEAD:$BRANCH" 2>"$WORK/push.err"; then
    echo "the site now pins ${SHA:0:7}${current:+ (was ${current:0:7})}"
    exit 0
  fi
  # never print the remote URL: it carries the token
  sed -E 's#https://[^@ ]*@#https://#g' "$WORK/push.err"
  echo "push refused (attempt $attempt of 3); trying again from a fresh clone"
  sleep $((attempt * 5))
done
echo "could not push ledger.lock to the site after 3 attempts"
exit 1
