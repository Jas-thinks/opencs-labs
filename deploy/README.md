# OpenCS Labs — native (no-Docker) deployment

This directory contains the deployment for the 12 assigned systems. It is
**native**: system Python virtualenvs, a native PostgreSQL cluster, and Nginx
as the reverse proxy. No Docker, no containers, no Kubernetes — per the strict
rule in [`docs/ARCHITECTURE.md`](../../docs/ARCHITECTURE.md).

## What is actually deployed

Read [`docs/deployment/INFRASTRUCTURE_INVENTORY.md`](../../docs/deployment/INFRASTRUCTURE_INVENTORY.md)
first: it records measured facts about the machines, including several that
differ from the briefing (shared kernel, no systemd, no published HTTP port).

| Role | Endpoint | Runtime | Notes |
|---|---|---|---|
| Load balancer + frontend | `.53:2305` | Nginx 1.24 (native) | Also hosts PostgreSQL |
| Backend 1 | `.53:2306` | uvicorn, venv | |
| Backend 2 | `.53:2307` | uvicorn, venv | |
| Backend 3 | `.53:2308` | uvicorn, venv | |
| Database | `.53:2305` | PostgreSQL 16 | native cluster, `pg_ctlcluster` |

The remaining eight endpoints (`.79:2221-2224`, `.53:2253-2256`) were not
reachable with the credentials supplied; see the inventory for the blocking
detail.

## Why there is no systemd

`PID 1` on every target is `sshd`, not `init`. `systemctl` reports *"System has
not been booted with systemd as init system"*. Services are therefore
supervised by [`scripts/svc.sh`](scripts/svc.sh) — a PID-file supervisor with
restart-on-exit and log rotation. This is a real constraint of the
infrastructure, not a simplification.

## Layout

```
deploy/
├── backend/            uvicorn service definition and env template
├── database/           PostgreSQL cluster configuration
├── load-balancer/      nginx.conf (frontend + API + health-aware upstreams)
├── config/             rendered .env template (no secrets)
├── scripts/            svc.sh supervisor, deploy, health-check helpers
└── README/             this directory's notes
```

## Deploying

```bash
# 1. One-time host preparation (venv, apt packages)
deploy/scripts/bootstrap_node.sh backend      # on each backend node

# 2. Database (once, on the DB node)
deploy/scripts/bootstrap_node.sh database

# 3. Migrations + seed (once, on one backend node)
deploy/scripts/migrate.sh

# 4. Start services
deploy/scripts/svc.sh start backend

# 5. Verify
deploy/scripts/healthcheck.sh
```

Secrets are **not** in this directory. `.env` is rendered per node with mode
`0600` and is never committed; see `config/env.template`.
