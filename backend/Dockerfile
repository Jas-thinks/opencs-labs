# syntax=docker/dockerfile:1

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# Mirror the repository layout (/srv/backend, /srv/content, /srv/datasets,
# /srv/scripts) so scripts/seed.py resolves REPO_ROOT identically on the host
# and inside the container.
WORKDIR /srv/backend

# Runtime system dependencies: libpq for psycopg, curl for healthchecks, and
# the Docker CLI for the local grading sandbox (OPENCE_GRADER=docker). The CLI
# talks to the daemon through the mounted socket; only the client is installed,
# not a daemon. Production uses OPENCE_GRADER=kubernetes and needs none of this.
COPY --from=docker:27-cli /usr/local/bin/docker /usr/local/bin/docker
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY app ./app
COPY alembic.ini ./
COPY migrations ./migrations
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# Non-root runtime user matching the notebook image (uid/gid 1000).
# /srv/backend/data is writable so the development default
# (sqlite:///./data/opencs.db) works without a database server.
RUN useradd --uid 1000 --gid 0 --create-home --shell /usr/sbin/nologin opencs \
    && mkdir -p /srv/backend/data \
    && chown -R 1000:0 /srv
USER 1000:0

ENV PYTHONPATH=/srv/backend

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=20s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8000/health || exit 1

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
