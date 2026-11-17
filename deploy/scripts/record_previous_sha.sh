#!/usr/bin/env bash
# Record the currently-deployed commit before a rollout, so the rollback job
# knows what to restore. Called by .github/workflows/deploy.yml.
#
# Usage: record_previous_sha.sh [runtime-dir]
set -euo pipefail

RUNTIME_DIR="${1:-$HOME/opencs-runtime}"
REPO_DIR="$HOME/opencs-labs"
OUT="$RUNTIME_DIR/previous-sha"

mkdir -p "$RUNTIME_DIR"

if [ ! -d "$REPO_DIR/.git" ]; then
  echo "no git checkout at $REPO_DIR" >&2
  exit 1
fi

current=$(git -C "$REPO_DIR" rev-parse HEAD)
printf '%s' "$current" > "$OUT"
chmod 600 "$OUT"
echo "recorded previous-sha=$current"
