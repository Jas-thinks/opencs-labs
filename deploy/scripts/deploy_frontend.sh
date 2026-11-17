#!/usr/bin/env bash
# Install a frontend bundle on the load-balancer host.
# Invoked over SSH by .github/workflows/deploy.yml via:
#   sudo -n /usr/local/bin/opencs-deploy-frontend /tmp/frontend.tgz
#
# Keeps the previous bundle so a rollback can restore it without a rebuild.
set -euo pipefail

ARCHIVE="${1:-/tmp/frontend.tgz}"
DEST="${OPENCE_FRONTEND_DIR:-/srv/opencs/frontend}"
STAMP=$(date -u +%Y%m%dT%H%M%SZ)

if [ ! -f "$ARCHIVE" ]; then
  echo "archive not found: $ARCHIVE" >&2
  exit 1
fi

# Verify the bundle before swapping it in: a broken index.html takes the whole
# application down.
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
tar xzf "$ARCHIVE" -C "$tmp"
if [ ! -f "$tmp/index.html" ]; then
  echo "bundle has no index.html; refusing to deploy" >&2
  exit 1
fi

if [ -d "$DEST" ] && [ -n "$(ls -A "$DEST" 2>/dev/null || true)" ]; then
  cp -a "$DEST" "${DEST}.prev-${STAMP}"
  # Keep only the two most recent previous bundles.
  ls -1dt "${DEST}".prev-* 2>/dev/null | tail -n +3 | xargs -r rm -rf
fi

mkdir -p "$DEST"
find "$DEST" -mindepth 1 -delete
cp -a "$tmp/." "$DEST/"
chown -R www-data:www-data "$DEST"

# Reload nginx so it picks up any changed assets immediately.
if command -v nginx >/dev/null 2>&1; then
  nginx -t && nginx -s reload
fi

echo "frontend deployed to $DEST (previous kept at ${DEST}.prev-${STAMP})"
