#!/bin/sh
# OpenCS Labs backend entrypoint.
#
# Runs database migrations, optionally seeds development content, then hands
# over to the API server. Seeding is idempotent and gated by
# OPENCE_SEED_ON_START so production deployments can disable it.
set -eu

echo "opencs: applying database migrations"
alembic upgrade head

if [ "${OPENCE_SEED_ON_START:-false}" = "true" ]; then
  if [ -f /srv/scripts/seed.py ]; then
    echo "opencs: seeding demo users, content and dataset catalogue"
    python /srv/scripts/seed.py
  else
    echo "opencs: seed script not mounted; skipping seed" >&2
  fi
fi

echo "opencs: starting API"
exec uvicorn app.main:app \
  --host 0.0.0.0 \
  --port 8000 \
  --proxy-headers \
  --forwarded-allow-ips '*'
