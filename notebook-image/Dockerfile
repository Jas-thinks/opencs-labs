# OpenCS Labs -- pinned analytics notebook image (opencs/analytics:1.0.0)
#
# One centrally maintained environment for every student notebook and every
# grading sandbox. See HLD.md section 11: immutable image, pinned versions,
# non-root user, health checks. Rebuild via `notebook-image/build.sh`.
#
# The tag is part of the contract: the backend launches notebooks with
# OPENCE_ENVIRONMENT_IMAGE and grades with OPENCE_GRADER_IMAGE, both defaulting
# to opencs/analytics:1.0.0, so a new environment means a new tag.
# ---------------------------------------------------------------------------
# Stage 0: build the prebuilt OpenCS JupyterLab extension.
#
# A prebuilt extension needs BOTH the JupyterLab Python package (for
# core paths and the labextension CLI) and Node. Node must not exist in the
# final image — hundreds of MB with no use inside a notebook — so it lives only
# in this discarded stage.
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS extension

# Node 22 from the official tarball (Debian's nodejs is too old for JL4).
ARG NODE_VERSION=22.12.0
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates xz-utils \
 && NODE_ARCH=$([ "$(uname -m)" = "aarch64" ] && echo arm64 || echo x64) \
 && curl -fsSL "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-${NODE_ARCH}.tar.xz" \
      | tar -xJ -C /usr/local --strip-components=1 \
 && rm -rf /var/lib/apt/lists/*

# Only the JupyterLab core is needed to build an extension against it.
RUN pip install --no-cache-dir "jupyterlab==4.6.6"

WORKDIR /ext
COPY jupyterlab-extension/package.json jupyterlab-extension/tsconfig.json ./
COPY jupyterlab-extension/schema ./schema
COPY jupyterlab-extension/style ./style
COPY jupyterlab-extension/src ./src

RUN npm install --include=dev --no-audit --no-fund \
 && npx tsc \
 && jupyter labextension build .

FROM python:3.12-slim

LABEL org.opencs.version="1.0.0" \
      org.opencs.component="analytics-notebook" \
      org.opencs.description="Pinned Python/JupyterLab environment for OpenCS Labs notebooks and grading" \
      org.opencontainers.image.title="opencs/analytics" \
      org.opencontainers.image.version="1.0.0"

# Deterministic, non-interactive pip/apt behaviour.
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    MPLBACKEND=Agg \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8

# System packages:
#   build-essential, git, curl, ca-certificates  toolchain and TLS roots that
#                                                students expect to exist
#   libpq-dev                                   psycopg / PostgreSQL clients
#   libgomp1                                    OpenMP runtime required by xgboost
#   fonts-dejavu-core                           stable glyphs for matplotlib text
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        build-essential \
        git \
        curl \
        ca-certificates \
        libpq-dev \
        libgomp1 \
        fonts-dejavu-core \
 && rm -rf /var/lib/apt/lists/* /var/cache/apt/* /tmp/*

# ---------------------------------------------------------------------------
# Non-root user matching the host side of the read-only dataset mount.
# Kubernetes runs notebook pods with runAsUser/runAsGroup/fsGroup 1000
# (see jupyterhub/jupyterhub_config.py), so container and host must agree on
# uid/gid or the mounted datasets are unreadable.
# ---------------------------------------------------------------------------
RUN groupadd --gid 1000 opencs \
 && useradd --uid 1000 --gid 1000 --create-home --home-dir /home/opencs \
        --shell /bin/bash opencs

# ---------------------------------------------------------------------------
# Python environment: fully pinned, no build isolation surprises.
# ---------------------------------------------------------------------------
COPY notebook-image/requirements.in notebook-image/requirements.lock /opt/opencs/build/

RUN python -m pip install --no-cache-dir --upgrade pip setuptools wheel \
 && python -m pip install --no-cache-dir -r /opt/opencs/build/requirements.lock \
 && python -m pip check

# Register the kernel explicitly. `ipykernel install` writes a system-wide
# kernelspec, so every user (uid 1000 included) sees the same interpreter and
# the same pinned packages.
RUN python -m ipykernel install --sys-prefix \
        --name python3 \
        --display-name "Python 3 (OpenCS Analytics)"

# ---------------------------------------------------------------------------
# Grader entrypoint. The backend mounts a staging directory at /work and runs:
#   python /opt/opencs/grade_runner.py /work
# It must exist in the image: the grading sandbox has no network and no
# writable copy of the repository.
# ---------------------------------------------------------------------------
COPY notebook-image/grade_runner.py /opt/opencs/grade_runner.py
RUN chmod 0555 /opt/opencs/grade_runner.py

# The OpenCS dataset-insertion extension, prebuilt in the extension stage.
# Its contract: inserting a dataset cell never executes it (ADR-005).
# The labextension directory already contains the built package.json.
COPY --from=extension /ext/opencs_jupyterlab_datasets/labextension /usr/local/share/jupyter/labextensions/@opencs/jupyterlab-datasets

# ---------------------------------------------------------------------------
# Filesystem layout.
#
#   /opt/opencs/datasets  empty mount point; KubeSpawner mounts the read-only
#                         dataset tree here at spawn time (never baked in, so
#                         the image carries no course data)
#   /opt/opencs/smoke-tests  deliberately absent; tests are mounted read-only
#                            at runtime by build.sh / `make test-env`
#   /home/opencs/work     the single-user server's working directory
# ---------------------------------------------------------------------------
RUN mkdir -p /opt/opencs/datasets /home/opencs/work \
 && chown -R 1000:1000 /home/opencs \
 && chmod 0755 /opt/opencs /opt/opencs/datasets /home/opencs \
 && chmod 0775 /home/opencs/work

USER 1000:1000
WORKDIR /home/opencs/work

# JupyterLab's auth is terminated by JupyterHub in front of this server, which
# is why the token and password are empty here: the single-user server is only
# reachable through the Hub's authenticated proxy.
EXPOSE 8888

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:8888${JUPYTERHUB_SERVICE_PREFIX:-/}api" | grep -qE '^(200|302|403)$'

CMD ["jupyterhub-singleuser", "--ip=0.0.0.0", "--port=8888"]
