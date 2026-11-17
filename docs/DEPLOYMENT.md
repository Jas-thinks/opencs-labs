# DEPLOYMENT — No-Docker Multi-Node Runbook

This runbook deploys the 11 assigned servers from `docs/PLAN_2.md`:

```
1   lb-1        Nginx / static frontend / TLS
3   api-1..3    FastAPI + opencs-worker
3   db-1..3     PostgreSQL primary + synchronous standby + async read replica
4   nb-1..nb-4  JupyterHub + per-user systemd JupyterLab + systemd-run grading
5   spare-1..5  unassigned
---
11 assigned, 5 spare
```

**Do not install Docker, containerd, Podman, DockerSpawner, Swarm, or mount
`/var/run/docker.sock` on any server.** The Jupyter and grading paths use
native systemd. The existing `docker-compose.yml` and Dockerfiles are not used
in this deployment.

Where the original brief said **DockerSpawner**, this runbook uses the custom
**`SSHSystemdSpawner`** (one JupyterHub, SSH to per-user systemd units on
`nb-1..nb-4`). Where it said a **grader sandbox container**, this runbook uses
**`systemd-run`** with a private network namespace, cgroup limits and read-only
datasets. Where it said a **notebook image**, this runbook uses a shared
**Python virtualenv** on every notebook node.

Before starting, implement the code changes in `docs/PLAN_2.md` §8:

- multi-worker outbox claim with `FOR UPDATE SKIP LOCKED`
- advisory locks for maintenance
- `OPENCE_WATCHER_ENABLED` and `app.worker`
- `SSHSystemdSpawner` and the spawn helper
- `SystemdSandbox` and `OPENCE_GRADER=systemd`
- grade queue/concurrency
- Hub PostgreSQL database

The runbook assumes those changes are present in the release you deploy.

---

## 1. Inventory and addressing

Replace the example addresses with your real plan.

| Host | Private IP | Role | Notes |
|---|---|---|---|
| `lb-1` | `10.0.0.10` | Nginx, TLS, static SPA | Public/campus DNS `opencs.example.edu` |
| `api-1` | `10.0.0.21` | FastAPI + worker | Watcher leader (`OPENCE_WATCHER_ENABLED=true`) |
| `api-2` | `10.0.0.22` | FastAPI + worker | Watcher disabled |
| `api-3` | `10.0.0.23` | FastAPI + worker | Watcher disabled |
| `db-1` | `10.0.0.30` | PostgreSQL primary + PgBouncer 6432 | WAL archive to NAS |
| `db-2` | `10.0.0.31` | PostgreSQL synchronous standby | Promoted on primary failure |
| `db-3` | `10.0.0.32` | PostgreSQL asynchronous read replica | Dumps/reporting reads |
| `nb-1` | `10.0.0.41` | JupyterHub control + notebooks | Hub proxy on 8000, Hub API 8081 |
| `nb-2` | `10.0.0.42` | Notebook node | systemd user units |
| `nb-3` | `10.0.0.43` | Notebook node | systemd user units |
| `nb-4` | `10.0.0.44` | Notebook node | systemd user units |
| `spare-1` | `10.0.0.60` | Unassigned | Promote to `nb-5` if needed |
| `spare-2` | `10.0.0.61` | Unassigned | Promote to `nb-6` if needed |
| `spare-3` | `10.0.0.62` | Unassigned | Promote to `nb-7` if needed |
| `spare-4` | `10.0.0.63` | Unassigned | Promote to `nb-8` if needed |
| `spare-5` | `10.0.0.64` | Unassigned | Promote to `nb-9` if needed |
| `nas-1` | `10.0.0.5` | NFS homes/datasets/backups | Not counted in the 16 |

`db-vip` is a keepalived/DNS address (for example `10.0.0.35`) that points at
the current primary and moves to `db-2` on failover.

Ports:

| Port | Where | Who may connect |
|---|---|---|
| 443 | `lb-1` | Campus/public |
| 80 | `lb-1` | Redirect to 443 |
| 8000 | `api-1..3` | `lb-1` only |
| 8000 | `nb-1` | `lb-1` only (JupyterHub proxy) |
| 8081 | `nb-1` | `api-1..3`, `nb-1` local (Hub API) |
| 20000–30000 | `nb-1..4` | `nb-1` (Hub proxy) only |
| 5432 | `db-1..3` | `db-1..3` replication, `api-1..3`, `nb-1` |
| 6432 | `db-1..2` | `api-1..3`, `nb-1` (PgBouncer) |
| 22 | all | Admin jump host; `nb-1` → `nb-2..4` for `opencs-hub` |
| 2049 | `nas-1` | `nb-1..4`, `db-1..3` |

**Students must never reach `api-*`, `db-*`, or `nb-*` directly.** They only
reach `lb-1:443`; Nginx proxies `/api/` to the API upstream and `/hub/` and
`/user/` to `nb-1:8000`.

---

## 2. Base OS and preflight (all servers)

Target: Ubuntu 24.04 LTS (or your current LTS). Run on every assigned server.

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y \
  python3.12 python3.12-venv python3-pip \
  build-essential pkg-config \
  chrony nftables rsync curl jq htop iotop \
  prometheus-node-exporter

# Confirm no container runtime is present.
dpkg -l | grep -Ei 'docker|containerd|podman' && {
  echo "Container runtime found; remove it before continuing" >&2; exit 1;
}
test ! -S /var/run/docker.sock
```

Create service accounts:

```bash
sudo groupadd --system opencs 2>/dev/null || true
sudo useradd --system --create-home --home-dir /var/lib/opencs \
  --shell /usr/sbin/nologin opencs
sudo useradd --system --create-home --shell /bin/bash opencs-hub
sudo useradd --system --create-home --shell /usr/sbin/nologin opencs-grader
sudo install -d -o opencs -g opencs -m 0750 /opt/opencs /srv/opencs /etc/opencs
sudo install -d -o opencs -g opencs -m 0750 /srv/opencs/releases
```

System limits (`/etc/security/limits.d/opencs.conf`):

```
* soft nofile 65535
* hard nofile 65535
```

`/etc/sysctl.d/90-opencs.conf`:

```
fs.file-max = 2097152
fs.inotify.max_user_watches = 524288
net.core.somaxconn = 4096
net.ipv4.ip_local_port_range = 20000 65000
vm.swappiness = 10
```

```bash
sudo sysctl --system
sudo systemctl enable --now chrony
```

SSH:

```bash
# On each node, disable password auth and install the admin key.
sudo sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
sudo sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config
sudo systemctl reload ssh
```

Keep an admin jump host; do not expose SSH to students.

Build the frontend once on a workstation or `lb-1`:

```bash
cd frontend
VITE_API_BASE=/api/v1 VITE_NOTEBOOK_ORIGIN= npm ci
npm run build
sudo rsync -a --delete dist/ /srv/opencs/frontend/dist/
```

The frontend is a static bundle; no Node runtime is needed in production.

---

## 3. `db-1..db-3` — PostgreSQL primary, standby, read replica

`n_1 = 3` in the approved allocation:

- `db-1`: primary.
- `db-2`: synchronous hot standby (`synchronous_standby_names='db-2'`).
- `db-3`: asynchronous read replica for reporting and `pg_dump`.
- PgBouncer runs on `db-1` and `db-2`; `db-vip` (keepalived or DNS) points at
  the current primary. The application DSN uses `db-vip:6432`.
- No Docker, no Patroni required for this deployment. A manual/keepalived
  promotion is documented; automated failover is an optional later step.

### 3.1 Install on all three DB nodes

```bash
sudo apt install -y postgresql-16 postgresql-client-16 pgbouncer
sudo systemctl enable --now postgresql
```

### 3.2 Primary `db-1`

Create roles and databases (choose strong passwords):

```bash
sudo -u postgres psql <<'SQL'
CREATE ROLE opencs LOGIN PASSWORD 'REPLACE_ME';
CREATE ROLE replicator REPLICATION LOGIN PASSWORD 'REPLACE_REPLICATION_PASSWORD';
CREATE DATABASE opencs OWNER opencs;
CREATE DATABASE jupyterhub OWNER opencs;
SQL
```

`/etc/postgresql/16/main/pg_hba.conf` on all three nodes:

```
host    opencs      opencs      10.0.0.0/24  scram-sha-256
host    jupyterhub  opencs      10.0.0.0/24  scram-sha-256
host    replication replicator  10.0.0.31/32 scram-sha-256
host    replication replicator  10.0.0.32/32 scram-sha-256
local   all         postgres                  peer
```

`/etc/postgresql/16/main/postgresql.conf` on `db-1`:

```
listen_addresses = '10.0.0.30,127.0.0.1'
shared_buffers = 24GB
effective_cache_size = 72GB
work_mem = 48MB
maintenance_work_mem = 2GB
max_connections = 200
max_wal_senders = 10
max_replication_slots = 10
wal_level = replica
synchronous_commit = on
synchronous_standby_names = 'db-2'
archive_mode = on
archive_command = 'test ! -f /srv/opencs/backups/wal/%f && cp %p /srv/opencs/backups/wal/%f'
max_wal_size = 8GB
checkpoint_timeout = 15min
random_page_cost = 1.1
effective_io_concurrency = 200
```

Create the NAS mount and archive directory on `db-1`:

```bash
sudo mkdir -p /srv/opencs/backups/wal /srv/opencs/backups/dumps
# /etc/fstab: 10.0.0.5:/srv/opencs/backups /srv/opencs/backups nfs4 rw,hard,noatime,_netdev 0 0
sudo mount -a
sudo chown -R postgres:postgres /srv/opencs/backups
sudo systemctl restart postgresql
```

Verify:

```bash
sudo -u postgres psql -c "SELECT version(), current_setting('archive_mode'), current_setting('synchronous_standby_names');"
sudo -u postgres psql -d opencs -c 'SELECT 1;'
```

### 3.3 Synchronous standby `db-2`

Stop PostgreSQL on `db-2`, clone the primary, and start in standby mode:

```bash
sudo systemctl stop postgresql
sudo -u postgres rm -rf /var/lib/postgresql/16/main
sudo -u postgres PGPASSWORD='REPLACE_REPLICATION_PASSWORD' \
  pg_basebackup -h 10.0.0.30 -U replicator \
  -D /var/lib/postgresql/16/main -Fp -Xs -P -R
```

`-R` creates `standby.signal` and `primary_conninfo` in
`postgresql.auto.conf`. Debian/Ubuntu keeps `postgresql.conf` outside the data
directory, so `pg_basebackup` does not copy it. Set the node-specific values on
`db-2` before starting:

```bash
sudo sed -i "s/^#\?listen_addresses.*/listen_addresses = '10.0.0.31,127.0.0.1'/" \
  /etc/postgresql/16/main/postgresql.conf
sudo sed -i "s/^#\?hot_standby.*/hot_standby = on/" \
  /etc/postgresql/16/main/postgresql.conf
sudo sed -i "s/^archive_mode.*/archive_mode = off/" \
  /etc/postgresql/16/main/postgresql.conf
sudo systemctl start postgresql
```

Verify from `db-1`:

```bash
sudo -u postgres psql -c "SELECT application_name, state, sync_state FROM pg_stat_replication;"
# db-2 should be streaming and sync
```

The primary uses `synchronous_standby_names='db-2'`, so the standby's
`application_name` must match. `pg_basebackup -R` does not set it. On `db-2`,
while there is no class traffic yet:

```bash
sudo -u postgres psql -c \
  "ALTER SYSTEM SET primary_conninfo = 'host=10.0.0.30 port=5432 user=replicator password=REPLACE_REPLICATION_PASSWORD application_name=db-2';"
sudo systemctl restart postgresql
```

Set `hot_standby = on` on `db-2` (default is on; confirm). Do the same on
`db-3` with `application_name=db-3`; `db-3` is asynchronous, so it is not in
`synchronous_standby_names`.

### 3.4 Asynchronous read replica `db-3`

Repeat the clone against `db-1` without adding `db-3` to
`synchronous_standby_names`:

```bash
sudo systemctl stop postgresql
sudo -u postgres rm -rf /var/lib/postgresql/16/main
sudo -u postgres PGPASSWORD='REPLACE_REPLICATION_PASSWORD' \
  pg_basebackup -h 10.0.0.30 -U replicator \
  -D /var/lib/postgresql/16/main -Fp -Xs -P -R
sudo sed -i "s/^#\?listen_addresses.*/listen_addresses = '10.0.0.32,127.0.0.1'/" \
  /etc/postgresql/16/main/postgresql.conf
sudo sed -i "s/^#\?hot_standby.*/hot_standby = on/" \
  /etc/postgresql/16/main/postgresql.conf
sudo sed -i "s/^archive_mode.*/archive_mode = off/" \
  /etc/postgresql/16/main/postgresql.conf
sudo systemctl start postgresql
```

`db-3` is read-only and may lag slightly. Use it for `pg_dump` and future
reporting read routing. Do not point application writes at it.

### 3.5 PgBouncer, `db-vip` and the application DSN

Install the same PgBouncer config on `db-1` and `db-2`:

`/etc/pgbouncer/pgbouncer.ini`:

```ini
[databases]
opencs = host=127.0.0.1 port=5432 dbname=opencs
jupyterhub = host=127.0.0.1 port=5432 dbname=jupyterhub pool_mode=session

[pgbouncer]
listen_addr = 0.0.0.0
listen_port = 6432
auth_type = scram-sha-256
auth_file = /etc/pgbouncer/userlist.txt
admin_users = postgres
pool_mode = transaction
max_client_conn = 500
default_pool_size = 35
reserve_pool_size = 5
reserve_pool_timeout = 5
server_idle_timeout = 60
```

`/etc/pgbouncer/userlist.txt` on both:

```
"opencs" "REPLACE_ME"
"postgres" "REPLACE_POSTGRES_PASSWORD"
```

```bash
sudo chown postgres:postgres /etc/pgbouncer/pgbouncer.ini /etc/pgbouncer/userlist.txt
sudo chmod 640 /etc/pgbouncer/pgbouncer.ini /etc/pgbouncer/userlist.txt
sudo systemctl enable --now pgbouncer
```

Configure a `db-vip` (for example `10.0.0.35`) with keepalived on `db-1` and
`db-2` (or DNS failover). A simple keepalived check:

```
vrrp_script chk_pg {
  script "/usr/bin/pg_isready -h 127.0.0.1 -p 5432"
  interval 2
  fall 3
}
vrrp_instance VI_1 {
  state BACKUP
  interface eth0
  virtual_router_id 51
  priority 110        # 110 on db-1, 100 on db-2
  advert_int 1
  virtual_ipaddress { 10.0.0.35/24 }
  track_script { chk_pg }
}
```

Use the same `db-vip` in every API and Hub DSN:

```bash
OPENCE_DATABASE_URL=postgresql+psycopg://opencs:REPLACE_ME@10.0.0.35:6432/opencs?prepare_threshold=0
OPENCE_HUB_DB_URL=postgresql+psycopg2://opencs:REPLACE_ME@10.0.0.35:6432/jupyterhub
```

keepalived only moves the VIP. On `db-2`, add a `notify_master` hook that runs
`pg_ctl promote -D /var/lib/postgresql/16/main` and fences the old primary;
otherwise the VIP can move to a read-only standby. Rehearse the promotion and
prefer a short outage over split-brain.

Verify from `api-1`:

```bash
PGPASSWORD='REPLACE_ME' psql -h 10.0.0.35 -p 6432 -U opencs -d opencs \
  -c 'SELECT now();'
PGPASSWORD='REPLACE_POSTGRES_PASSWORD' psql -h 10.0.0.35 -p 6432 -U postgres -d pgbouncer \
  -c 'SHOW POOLS;'
```

**Prepared statements:** the backend uses psycopg 3. With transaction pooling,
keep `?prepare_threshold=0` in the DSN. The `jupyterhub` database uses session
pooling for the Hub's psycopg2 connection.

### 3.6 Backups, failover and restore

Run dumps from the `db-3` read replica so the primary is not loaded:

`/etc/cron.d/opencs-backup` on `db-3`:

```
15 2 * * * postgres pg_dump -h 127.0.0.1 -Fc opencs > /srv/opencs/backups/dumps/opencs-$(date +\%F).dump
20 2 * * * postgres pg_dump -h 127.0.0.1 -Fc jupyterhub > /srv/opencs/backups/dumps/jupyterhub-$(date +\%F).dump
30 3 * * 0  postgres find /srv/opencs/backups/dumps -type f -mtime +35 -delete
```

WAL archiving runs on `db-1` via `archive_command`. Mount the NAS backup export
on `db-3` as in §3.2.

Manual failover drill (rehearse before the class):

```bash
# On db-2, promote the synchronous standby:
sudo -u postgres pg_ctl promote -D /var/lib/postgresql/16/main
# Move db-vip to db-2 (keepalived should follow the health/priority change,
# or move the VIP manually in the drill).
pg_isready -h 10.0.0.35 -p 5432
# Rebuild the old primary as the new standby with pg_rewind or a fresh
# pg_basebackup from db-2; do not point writes at the old primary until it is
# back in sync.
```

Record RPO (≤15 min with WAL) and RTO (30–60 min including promotion and
repointing). `db-1` is no longer a single point of failure, but the VIP,
keepalived and PgBouncer path must be tested.

Restore drill:

```bash
createdb -U postgres opencs_restore
pg_restore -U postgres -d opencs_restore /srv/opencs/backups/dumps/opencs-YYYY-MM-DD.dump
psql -U postgres -d opencs_restore -c 'SELECT count(*) FROM notebooks;'
```

---

## 4. `api-1..3` — FastAPI and outbox workers

Repeat on all three nodes unless noted.

### 4.1 Release and virtualenv

```bash
sudo install -d -o opencs -g opencs /srv/opencs/releases/2026-11-17
sudo rsync -a --delete /path/to/repo/backend/ /srv/opencs/releases/2026-11-17/backend/
sudo rsync -a /path/to/repo/scripts/ /srv/opencs/releases/2026-11-17/scripts/
sudo rsync -a /path/to/repo/content/ /srv/opencs/releases/2026-11-17/content/
sudo ln -sfn /srv/opencs/releases/2026-11-17 /srv/opencs/current

sudo -u opencs python3.12 -m venv /opt/opencs/backend-venv
sudo -u opencs /opt/opencs/backend-venv/bin/pip install --upgrade pip
sudo -u opencs /opt/opencs/backend-venv/bin/pip install \
  -r /srv/opencs/current/backend/requirements.txt

# The API prepares dataset previews/snippets and reads the serving tree.
# Mount the NAS dataset export read-only on every API node.
sudo install -d -o opencs -g opencs /opt/opencs/datasets
# /etc/fstab:
# 10.0.0.5:/srv/opencs/datasets /opt/opencs/datasets nfs4 ro,hard,noatime,rsize=1048576,wsize=1048576,vers=4.2,_netdev 0 0
sudo mount -a
ls /opt/opencs/datasets | head
```

### 4.2 Environment

`/etc/opencs/backend.env` (root-owned, 0600, copied to each API node with the
same secrets):

```bash
OPENCE_ENV=production
OPENCE_DEBUG=false
OPENCE_JWT_SECRET=REPLACE_WITH_32PLUS_RANDOM_CHARS
OPENCE_JWT_ISSUER=opencs
OPENCE_SESSION_COOKIE=opencs_session
OPENCE_SESSION_TTL_SECONDS=43200
OPENCE_COOKIE_SECURE=true
OPENCE_PUBLIC_ORIGIN=https://opencs.example.edu
OPENCE_API_PREFIX=/api/v1
OPENCE_API_PUBLIC_BASE=https://opencs.example.edu/api/v1
OPENCE_CORS_ORIGINS=https://opencs.example.edu
OPENCE_DATABASE_URL=postgresql+psycopg://opencs:REPLACE_ME@10.0.0.35:6432/opencs?prepare_threshold=0
OPENCE_DB_POOL_SIZE=10
OPENCE_DB_MAX_OVERFLOW=10
OPENCE_AUTH_MODE=oidc
OPENCE_OIDC_ISSUER=https://idp.example.edu/realms/opencs
OPENCE_OIDC_CLIENT_ID=opencs
OPENCE_OIDC_CLIENT_SECRET=REPLACE_ME
OPENCE_NOTEBOOK_BACKEND=hub
OPENCE_JUPYTERHUB_URL=http://10.0.0.41:8081
OPENCE_JUPYTERHUB_API_URL=http://10.0.0.41:8081/hub/api
OPENCE_JUPYTERHUB_PROXY_URL=http://10.0.0.41:8000
OPENCE_JUPYTERHUB_PUBLIC_URL=https://opencs.example.edu
OPENCE_JUPYTERHUB_API_TOKEN=REPLACE_WITH_HUB_SERVICE_TOKEN
OPENCE_DATASET_SERVING_DIR=/opt/opencs/datasets
OPENCE_ENVIRONMENT_IMAGE=opencs/analytics:1.0.0
OPENCE_GRADER=systemd
OPENCE_GRADER_VENV=/opt/opencs/notebook-venv
OPENCE_GRADER_WRAPPER=/usr/local/sbin/opencs-grade-run
OPENCE_GRADER_STAGING_DIR=/srv/opencs/grading
OPENCE_GRADER_TIMEOUT_SECONDS=90
OPENCE_GRADER_MEMORY=1G
OPENCE_GRADER_CPUS=1
OPENCE_GRADER_CONCURRENCY=4
OPENCE_RATE_LIMIT_ENABLED=true
OPENCE_RATE_LIMIT_LAUNCH_PER_MINUTE=4
OPENCE_RATE_LIMIT_EVALUATE_PER_MINUTE=2
OPENCE_MAX_ACTIVE_SESSIONS=224
OPENCE_BACKGROUND_WORKERS_ENABLED=false
OPENCE_WATCHER_ENABLED=false
```

Notes:

- **Authentication prerequisite:** the current backend implements only the
  `dev` email/password login (`/auth/login`, `/auth/token`). `OPENCE_AUTH_MODE=oidc`
  is a configuration surface but the OIDC authorization-code/callback flow is
  not implemented in the repository. Either implement OIDC before production,
  or run a closed intranet class with dev auth and seeded accounts (set
  `OPENCE_AUTH_MODE=dev`; this bypasses the production hardening check and must
  be documented as a deliberate trade-off). Do not deploy the `oidc` setting
  and assume login works.
- `OPENCE_MAX_ACTIVE_SESSIONS=224` is only valid if the class uses the
  **standard 2 GB / 1 vCPU** profile on the current 4 notebook nodes
  (4 × 56 = 224). For 500 standard sessions, promote all five spares to
  `nb-5..nb-9` (9 × 56 = 504) and raise the ceiling to 500. For the heavy
  16 GB profile set it to ~28; for the 8 GB profile, ~56; for the GPU profile,
  the actual GPU count. This is the admission ceiling, not a target.
- Rate limits are divided by three relative to single-node values because the
  current limiter is per process. If a shared limiter is implemented, use the
  original limits.
- `OPENCE_GRADER=systemd` and `OPENCE_WATCHER_ENABLED` require the code changes
  from `PLAN_2.md` §8.
- The Hub API token must match `OPENCE_JUPYTERHUB_API_TOKEN` on `nb-1`.

```bash
sudo chown root:root /etc/opencs/backend.env
sudo chmod 600 /etc/opencs/backend.env
```

### 4.3 Migrations (once, on `api-1`)

Do not run `alembic upgrade head` from three nodes simultaneously.

```bash
cd /srv/opencs/current/backend
sudo -u opencs env $(grep -v '^#' /etc/opencs/backend.env | xargs) \
  /opt/opencs/backend-venv/bin/alembic upgrade head
```

Record the revision. Content seeding: the current `scripts/seed.py` refuses
demo users in production. Load curriculum/content through your controlled
content-import step before switching `OPENCE_ENV=production`, or extend the
seed to support content-only production imports. Do not run the demo seed in
production.

### 4.4 systemd units

`/etc/systemd/system/opencs-api.service`:

```ini
[Unit]
Description=OpenCS API
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=opencs
Group=opencs
EnvironmentFile=/etc/opencs/backend.env
Environment=OPENCE_BACKGROUND_WORKERS_ENABLED=false
WorkingDirectory=/srv/opencs/current/backend
ExecStart=/opt/opencs/backend-venv/bin/uvicorn app.main:app \
  --host 0.0.0.0 --port 8000 --workers 4 \
  --proxy-headers --forwarded-allow-ips=10.0.0.10
Restart=always
RestartSec=3
LimitNOFILE=65535
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
```

`/etc/systemd/system/opencs-worker.service`:

```ini
[Unit]
Description=OpenCS outbox worker
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=opencs
Group=opencs
EnvironmentFile=/etc/opencs/backend.env
Environment=OPENCE_BACKGROUND_WORKERS_ENABLED=true
# api-1 only:
# Environment=OPENCE_WATCHER_ENABLED=true
WorkingDirectory=/srv/opencs/current/backend
ExecStart=/opt/opencs/backend-venv/bin/python -m app.worker
Restart=always
RestartSec=3
LimitNOFILE=65535
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
```

On `api-1`, uncomment `OPENCE_WATCHER_ENABLED=true`; leave it false on
`api-2`/`api-3`.

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now opencs-api opencs-worker
sudo systemctl status opencs-api opencs-worker --no-pager
curl -fsS http://127.0.0.1:8000/health
curl -fsS http://127.0.0.1:8000/ready
```

Readiness must pass through PgBouncer. If `/ready` fails, check
`OPENCE_DATABASE_URL` and PgBouncer logs.

### 4.5 Verify outbox behavior

With two workers running (for example `api-1` and `api-2`), enqueue a test job
or run the worker test suite. Confirm:

```bash
sudo -u postgres psql -d opencs -c \
  "SELECT status, count(*) FROM jobs GROUP BY status;"
sudo -u postgres psql -d opencs -c \
  "SELECT pg_try_advisory_lock(hashtext('opencs:prune_autosaves'));"
```

No job should be processed twice. Maintenance jobs should run once cluster-wide.

---

## 5. `nb-1..nb-4` — NFS, notebook venv, systemd Jupyter

### 5.1 NFS homes and datasets (all nb nodes)

```bash
sudo install -d -o opencs -g opencs /home/opencs /opt/opencs/datasets

# /etc/fstab:
# 10.0.0.5:/srv/opencs/homes    /home/opencs         nfs4 rw,hard,noatime,rsize=1048576,wsize=1048576,vers=4.2,_netdev 0 0
# 10.0.0.5:/srv/opencs/datasets /opt/opencs/datasets nfs4 ro,hard,noatime,rsize=1048576,wsize=1048576,vers=4.2,_netdev 0 0
sudo mount -a
df -h /home/opencs /opt/opencs/datasets
```

If the dataset tree is node-local instead of NFS, rsync it and make it
read-only:

```bash
sudo rsync -a --delete nas-1:/srv/opencs/datasets/ /opt/opencs/datasets/
sudo chmod -R a-w /opt/opencs/datasets
```

### 5.2 Per-student OS accounts and homes

Provision before the class, not at spawn time. Get the student list from the
backend database:

```bash
psql -h 10.0.0.35 -p 6432 -U opencs -d opencs -Atc \
  "SELECT hub_username FROM users WHERE role='student' ORDER BY hub_username;" \
  > /tmp/students.txt
```

Run on every `nb-*` node:

```bash
while read -r user; do
  uid=$(python3 - <<PY
import zlib
u='$user'
print(20000 + (zlib.crc32(u.encode()) % 10000))
PY
)
  id "opencs-$user" >/dev/null 2>&1 || \
    sudo useradd --uid "$uid" --gid opencs --create-home \
      --home-dir "/home/opencs/$user" --shell /bin/bash "opencs-$user"
  sudo install -d -o "opencs-$user" -g opencs -m 0700 "/home/opencs/$user"
done < /tmp/students.txt
```

Use a deterministic, collision-checked UID allocator; the crc32 example is a
starting point, not a production identity system. Ensure homes are on NFS and
quota them (5–10 GB per student for this class profile).

### 5.3 Notebook virtualenv (all nb nodes)

```bash
sudo python3.12 -m venv /opt/opencs/notebook-venv
sudo /opt/opencs/notebook-venv/bin/pip install --upgrade pip
sudo /opt/opencs/notebook-venv/bin/pip install \
  -r /srv/opencs/current/notebook-image/requirements.lock
# jupyterhub-singleuser entry point:
sudo /opt/opencs/notebook-venv/bin/pip install 'jupyterhub>=4,<5'
sudo /opt/opencs/notebook-venv/bin/jupyterhub-singleuser --version
```

Copy `grade_runner.py` from the repo:

```bash
sudo install -o opencs -g opencs -m 0750 \
  /srv/opencs/current/notebook-image/grade_runner.py /opt/opencs/grade_runner.py
```

Install the OpenCS JupyterLab extension into the shared venv on every `nb-*`
node. Build it once on a workstation or `nb-1`:

```bash
cd /srv/opencs/current/jupyterlab-extension
npm ci
npm run build:prod
# Produces opencs_jupyterlab_datasets/labextension
```

Then install the prebuilt labextension into the notebook venv:

```bash
sudo /opt/opencs/notebook-venv/bin/jupyter labextension install \
  /srv/opencs/current/jupyterlab-extension/opencs_jupyterlab_datasets
sudo /opt/opencs/notebook-venv/bin/jupyter labextension list
```

The notebook metadata written by the backend must use the public API base:

```bash
OPENCE_API_PUBLIC_BASE=https://opencs.example.edu/api/v1
```

Do not set it to a private `api-*` address. The extension runs at
`https://opencs.example.edu/user/<name>/lab`, same origin as `/api`, so the
session cookie applies and no browser CORS path to the API nodes is needed.


### 5.4 JupyterHub on `nb-1`

```bash
sudo python3.12 -m venv /opt/opencs/hub-venv
sudo /opt/opencs/hub-venv/bin/pip install --upgrade pip
sudo /opt/opencs/hub-venv/bin/pip install \
  'jupyterhub>=4,<5' jupyterhub-idle-culler psycopg2-binary paramiko
sudo install -d -o opencs-hub -g opencs-hub -m 0700 /srv/jupyterhub/data

# SSH identity the Hub uses to reach the spawn helper on every nb-* node.
sudo install -d -o opencs-hub -g opencs-hub -m 0700 /home/opencs-hub/.ssh
sudo -u opencs-hub ssh-keygen -t ed25519 -N '' \
  -f /home/opencs-hub/.ssh/id_ed25519
sudo install -o opencs-hub -g opencs-hub -m 0600 \
  /home/opencs-hub/.ssh/id_ed25519 /etc/opencs/hub_ssh_key
sudo install -o opencs-hub -g opencs-hub -m 0644 \
  /home/opencs-hub/.ssh/id_ed25519.pub /etc/opencs/hub_ssh_key.pub
sudo cat /etc/opencs/hub_ssh_key.pub
```

Install the public key on every `nb-*` node for `opencs-hub` in §5.5.

`paramiko` is used by the custom `SSHSystemdSpawner`. If you implement it with
`asyncssh` instead, install that package and update the spawner import.


Copy the configuration and custom spawner from the release:

```bash
sudo install -o root -g opencs-hub -m 0640 \
  /srv/opencs/current/jupyterhub/jupyterhub_config.py \
  /etc/opencs/jupyterhub_config.py
sudo install -o root -g opencs-hub -m 0640 \
  /srv/opencs/current/jupyterhub/opencs_auth.py \
  /etc/opencs/opencs_auth.py
sudo install -o root -g opencs-hub -m 0640 \
  /srv/opencs/current/jupyterhub/ssh_systemd_spawner.py \
  /etc/opencs/ssh_systemd_spawner.py
```

`/etc/opencs/hub.env` (root-owned, 0600):

```bash
OPENCE_SPAWNER=ssh-systemd
OPENCE_JWT_SECRET=REPLACE_SAME_AS_BACKEND
OPENCE_JWT_ISSUER=opencs
OPENCE_SESSION_COOKIE=opencs_session
OPENCE_JUPYTERHUB_API_TOKEN=REPLACE_SAME_AS_BACKEND
OPENCE_HUB_DB_URL=postgresql+psycopg2://opencs:REPLACE_ME@10.0.0.35:6432/jupyterhub
OPENCE_HUB_BIND_URL=http://0.0.0.0:8000
OPENCE_HUB_PORT=8081
OPENCE_HUB_CONNECT_URL=http://10.0.0.41:8081
OPENCE_JUPYTERHUB_PUBLIC_URL=https://opencs.example.edu
OPENCE_HUB_NAMESPACE=opencs
OPENCE_NOTEBOOK_IMAGE=host-venv
OPENCE_NOTEBOOK_VENV=/opt/opencs/notebook-venv
OPENCE_DATASET_MOUNT_PATH=/opt/opencs/datasets
OPENCE_DATASET_SERVING_DIR=/opt/opencs/datasets
OPENCE_IDLE_TIMEOUT_SECONDS=1800
OPENCE_IDLE_CULL_EVERY_SECONDS=600
JUPYTERHUB_CRYPT_KEY=REPLACE_WITH_FERNET_KEY
```

Generate the Fernet key:

```bash
python3 -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
```

`/etc/systemd/system/jupyterhub.service`:

```ini
[Unit]
Description=OpenCS JupyterHub (no Docker)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=opencs-hub
Group=opencs-hub
EnvironmentFile=/etc/opencs/hub.env
WorkingDirectory=/etc/opencs
ExecStart=/opt/opencs/hub-venv/bin/jupyterhub -f /etc/opencs/jupyterhub_config.py
Restart=always
RestartSec=3
LimitNOFILE=65535
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
```

The Hub's custom spawner (`ssh-systemd`) must be configured with:

- node inventory (`nb-1..nb-4` private IPs and capacity labels)
- `opencs-hub` SSH identity
- per-user UID/home template
- profile memory/CPU values
- port range 20000–30000

Start and verify:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now jupyterhub
sudo systemctl status jupyterhub --no-pager
curl -fsS -H "Authorization: token $OPENCE_JUPYTERHUB_API_TOKEN" \
  http://127.0.0.1:8081/hub/api/
curl -fsS http://127.0.0.1:8000/hub/health
```

### 5.5 Spawn helper on `nb-1..nb-4`

`/usr/local/sbin/opencs-spawn` (root-owned, 0755) is a small JSON helper:

- reads `{"action": "start|stop|status|health", "user": "...", "uid": 20001,
  "port": 20001, "profile": "standard|medium|heavy|gpu"}` from stdin
- validates the username (`^[a-z0-9_]+$`), UID range, port range, and profile
- resolves the profile to fixed `MemoryMax`/`CPUQuota`
- runs `systemd-run` with the properties in `PLAN_2.md` §4.4
- never accepts arbitrary commands or paths from the Hub
- returns JSON with `{"ok": true, "unit": "...", "port": ...}` or an error

Install it on every `nb-*` node:

```bash
sudo install -o root -g root -m 0755 opencs-spawn /usr/local/sbin/opencs-spawn
```

Restricted SSH key for the Hub (`/home/opencs-hub/.ssh/authorized_keys`):

```
command="sudo /usr/local/sbin/opencs-spawn",no-pty,no-port-forwarding,\
no-agent-forwarding,no-X11-forwarding ssh-ed25519 AAAA... hub@nb-1
```

Sudoers (`/etc/sudoers.d/opencs-spawn`):

```
opencs-hub ALL=(root) NOPASSWD: /usr/local/sbin/opencs-spawn
```

Test from `nb-1` as `opencs-hub`:

```bash
echo '{"action":"health"}' | ssh -i /etc/opencs/hub_ssh_key opencs-hub@10.0.0.42
```

The forced command (`sudo /usr/local/sbin/opencs-spawn`) runs the helper; the
client does not get a shell. The response must be JSON. A start test will
create `jupyter-<user>.service`; verify with `systemctl status
jupyter-<user>` on the target node.

### 5.6 Node inventory

Create the inventory tables in the `jupyterhub` database (or a dedicated
schema) and seed them:

```sql
CREATE TABLE IF NOT EXISTS jupyter_nodes (
  hostname text PRIMARY KEY,
  private_ip inet NOT NULL,
  capacity_slots int NOT NULL,
  gpu_count int NOT NULL DEFAULT 0,
  profile_classes text[] NOT NULL DEFAULT '{standard}',
  active_slots int NOT NULL DEFAULT 0,
  last_seen_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS spawn_slots (
  hostname text NOT NULL REFERENCES jupyter_nodes(hostname),
  port int NOT NULL,
  username text,
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (hostname, port)
);
```

Seed `nb-1..nb-4` with the real private IPs, capacity (7/9/14/56 depending on
profile) and GPU counts. The spawner allocates ports transactionally; stale
slots are released when `poll()` returns stopped.

---

## 6. `lb-1` — Nginx, TLS, static frontend

### 6.1 Nginx

`/etc/nginx/conf.d/opencs.conf`:

```nginx
map $http_upgrade $connection_upgrade {
    default upgrade;
    ''      close;
}

upstream opencs_api {
    least_conn;
    server 10.0.0.21:8000 max_fails=3 fail_timeout=10s;
    server 10.0.0.22:8000 max_fails=3 fail_timeout=10s;
    server 10.0.0.23:8000 max_fails=3 fail_timeout=10s;
    keepalive 64;
}

server {
    listen 80;
    server_name opencs.example.edu;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    http2 on;
    server_name opencs.example.edu;

    ssl_certificate     /etc/letsencrypt/live/opencs.example.edu/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/opencs.example.edu/privkey.pem;

    client_max_body_size 10m;
    add_header Strict-Transport-Security "max-age=31536000" always;

    root /srv/opencs/frontend/dist;
    index index.html;

    location = /healthz { access_log off; return 200 "ok\n"; }

    location /api/ {
        proxy_pass http://opencs_api;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
        proxy_next_upstream error timeout http_502 http_503 http_504;
    }

    location /hub/ {
        proxy_pass http://10.0.0.41:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
        proxy_buffering off;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }

    location /user/ {
        proxy_pass http://10.0.0.41:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
        proxy_buffering off;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }

    location /assets/ {
        expires 1y;
        add_header Cache-Control "public, immutable";
        try_files $uri =404;
    }

    location / {
        try_files $uri $uri/ /index.html;
        add_header Cache-Control "no-cache";
    }
}
```

Set `worker_processes auto;` and `worker_connections 8192;` in
`/etc/nginx/nginx.conf`. Enable `limit_req` only if you deliberately want a
coarse edge limit; the application has its own limiter.

```bash
sudo nginx -t
sudo systemctl enable --now nginx
sudo systemctl reload nginx
curl -fsS https://opencs.example.edu/healthz
curl -fsS https://opencs.example.edu/api/v1/config
```

### 6.2 TLS

Use institutional certificates or certbot:

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d opencs.example.edu
sudo systemctl enable --now certbot.timer
```

Renewal must be tested before the class.

---

## 7. Grading on `nb-1..nb-4` (no Docker)

### 7.1 Wrapper and sudoers

Create the staging area and grant the sandbox user access:

```bash
sudo install -d -o opencs -g opencs -m 2770 /srv/opencs/grading
sudo usermod -aG opencs opencs-grader
```

`/usr/local/sbin/opencs-grade-run` (root-owned, 0750):

- reads JSON from stdin: `{"unit": "...", "work": "/srv/opencs/grading/..."}`
- validates `unit` (`^opencs-grade-[a-f0-9]{12}$`) and `work` under
  `/srv/opencs/grading/`
- `chown -R opencs-grader:opencs <work>` so the sandbox can read the notebook
  and write its scratch results
- runs `systemd-run --wait --collect` with:
  `--uid=opencs-grader --gid=opencs-grader`,
  `MemoryMax=1G`, `CPUQuota=100%`, `PrivateNetwork=yes`,
  `NoNewPrivileges=yes`, `ProtectSystem=strict`, `ProtectHome=yes`,
  `PrivateTmp=yes`, `ReadOnlyPaths=/opt/opencs/datasets`,
  `BindPaths=<work>`, `RuntimeMaxSec=120`, `MPLBACKEND=Agg`
- invokes `/opt/opencs/notebook-venv/bin/python /opt/opencs/grade_runner.py <work>`
- forwards stdout/stderr and the exit code

Sudoers:

```
opencs ALL=(root) NOPASSWD: /usr/local/sbin/opencs-grade-run
```

Do not grant `opencs` blanket sudo. The wrapper is the only privileged path.

### 7.2 Grader worker

On each `nb-*` node that should grade:

```ini
# /etc/systemd/system/opencs-grader.service
[Unit]
Description=OpenCS grader worker (systemd sandbox)
After=network-online.target

[Service]
User=opencs
Group=opencs
EnvironmentFile=/etc/opencs/backend.env
Environment=OPENCE_GRADER=systemd
Environment=OPENCE_GRADER_CONCURRENCY=4
WorkingDirectory=/srv/opencs/current/backend
ExecStart=/opt/opencs/backend-venv/bin/python -m app.grader_worker
Restart=always
RestartSec=3
LimitNOFILE=65535
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
```

`app.grader_worker` is a required code change: it claims `grade_attempt` jobs
from the outbox and runs at most `OPENCE_GRADER_CONCURRENCY` systemd units at
once. The API should enqueue and return `202 Accepted` with a job id for large
classes; the existing synchronous evaluation can remain for small classes.

Verify one grade manually:

```bash
sudo -u opencs /opt/opencs/backend-venv/bin/python - <<'PY'
from app.integrations.grader import NotebookGrader
print(NotebookGrader().evaluate(
    {"nbformat": 4, "nbformat_minor": 5, "metadata": {}, "cells": []},
    {"tests": [{"id": "noop", "description": "always passes", "code": "assert True"}]},
))
PY
```

Confirm the systemd unit has `PrivateNetwork=yes` and no network access, and
that the dataset tree is read-only inside the sandbox.

---

## 8. Firewall matrix

Use nftables or your institutional firewall. Example intent:

| Source | Destination | Port | Purpose |
|---|---|---|---|
| campus/public | `lb-1` | 443 | Students |
| admin jump | all | 22 | Administration |
| `lb-1` | `api-1..3` | 8000 | API proxy |
| `lb-1` | `nb-1` | 8000 | Hub proxy |
| `api-1..3` | `db-vip` | 6432 | PgBouncer |
| `nb-1` | `db-vip` | 6432 | JupyterHub DB |
| `db-1..3` | `db-1..3` | 5432 | Streaming replication |
| `api-1..3` | `nb-1` | 8081 | Hub API |
| `nb-1` | `nb-1..4` | 22 | restricted spawn SSH |
| `nb-1`/`lb-1` | `nb-1..4` | 20000–30000 | Hub proxy to user servers |
| `nb-1..4`, `db-1..3` | `nas-1` | 2049 | NFS |
| `api-1..3` | IdP | 443 | OIDC |
| `api-1..3` | `nb-1` | 8000 | Hub proxy contents (if backend uses it) |
| any | `spare-1..5` | — | none until promoted |

Deny students direct access to `api-*`, `db-*`, and `nb-*`. The only public
listener is `lb-1:443`.

---

## 9. Smoke test before announcing the class

1. `curl -fsS https://opencs.example.edu/healthz`
2. `curl -fsS https://opencs.example.edu/api/v1/config`
3. `curl -fsS https://opencs.example.edu/api/v1/health` (if exposed via LB)
4. Sign in with a test OIDC account.
5. Create a notebook, open it, run `print("hello")`.
6. Confirm `systemctl status jupyter-<user>` on the assigned `nb-*`.
7. Confirm the notebook file appears in `/home/opencs/<user>` on NFS.
8. Confirm autosave: edit a cell, wait 30 s, `GET /api/v1/notebooks/<id>/versions`.
9. Submit a practice exercise and confirm a systemd-run grade result.
10. Stop the notebook; confirm the systemd unit stops and the home remains.
11. Restart JupyterHub; confirm it reconnects to PostgreSQL and lists servers.
12. Kill one `nb-*` unit; confirm the Hub can restart it on the same node
    (NFS home makes this possible).

---

## 10. Staged load test (224 on the current 4 nodes; 500 after promotion)

Run from a workstation, not from the servers.

```bash
cd tests/load
python run_loadtest.py --base https://opencs.example.edu --users 10  --duration 120
python run_loadtest.py --base https://opencs.example.edu --users 50  --duration 300
python run_loadtest.py --base https://opencs.example.edu --users 100 --duration 600
python run_loadtest.py --base https://opencs.example.edu --users 224 --duration 600
# 500 requires promoting spare-1..5 to nb-5..nb-9 first:
python run_loadtest.py --base https://opencs.example.edu --users 500 --duration 900
python run_loadtest.py --base https://opencs.example.edu --users 500 --duration 300 --spawn
```

During each stage collect:

- API p50/p95/p99 and error rate (harness).
- Spawn success rate and time (Hub logs/API).
- Active notebooks per `nb-*` and node CPU/RAM.
- PostgreSQL connections, PgBouncer `SHOW POOLS`, `SHOW STATS` on `db-1`/`db-2`.
- Replication state on `db-1` (`pg_stat_replication`) and lag on `db-3`.
- NFS latency and throughput.
- WebSocket count on `lb-1` and `nb-1`.
- Grader queue depth and completion time.

**Expected result:** on the 11-server allocation, the standard 2 GB ceiling is
224 sessions (4 notebook nodes). 500 standard sessions fit only after
promoting `spare-1..5` to `nb-5..nb-9` (9 × 56 = 504). 500 heavy 16 GB or GPU
sessions cannot be served by 16 servers. The report must state the measured
ceiling and the profile used. Do not publish a capacity claim that contradicts
the hardware math in `PLAN_2.md`.

For a grading burst, queue 100 evaluations and confirm the per-node
`OPENCE_GRADER_CONCURRENCY` cap is respected and the queue drains.

---

## 11. Monitoring and alerts

Install native exporters; no Docker:

- `prometheus-node-exporter` on every server.
- `postgres_exporter` on `db-1`, `db-2`, `db-3`.
- `pgbouncer_exporter` on `db-1` and `db-2`.
- Nginx `stub_status` on `lb-1`.
- JupyterHub metrics (Hub `/metrics` if enabled) and logs in journald.

Minimum alerts:

- API 5xx rate >1% for 5 min.
- API p95 >400 ms for 10 min.
- `db-vip`/`db-1` connections >80% of `max_connections`, PgBouncer pool wait >5 s.
- Replication lag on `db-2`/`db-3` >30 s, WAL archive failures.
- `db-1..3` disk >80%.
- `nb-*` memory >85%, CPU >80% for 10 min, spawn failures.
- Hub 5xx rate or spawn failure rate >1%.
- Grading queue >10 min.
- NFS latency >50 ms or stale mounts.
- `lb-1` 5xx rate or upstream health failures.

Logs:

```bash
sudo journalctl -u opencs-api -u opencs-worker -f
sudo journalctl -u jupyterhub -f
sudo journalctl -u opencs-grader -f
```

---

## 12. Rollback

### Backend

Releases live under `/srv/opencs/releases/<date>` with a `current` symlink.

```bash
sudo systemctl stop opencs-api opencs-worker
sudo ln -sfn /srv/opencs/releases/PREVIOUS /srv/opencs/current
sudo systemctl start opencs-api opencs-worker
curl -fsS http://127.0.0.1:8000/ready
```

If the database migration is not backward-compatible, restore the dump taken
before the deploy. Never run `alembic downgrade` without a tested restore path.

### JupyterHub

```bash
sudo systemctl stop jupyterhub
sudo cp /srv/opencs/releases/PREVIOUS/jupyterhub/jupyterhub_config.py /etc/opencs/
sudo cp /srv/opencs/releases/PREVIOUS/jupyterhub/ssh_systemd_spawner.py /etc/opencs/
sudo systemctl start jupyterhub
```

`c.JupyterHub.cleanup_servers = True` stops user servers on Hub shutdown; drain
the class or accept that students relaunch. Their files are on NFS.

### Load balancer

```bash
sudo cp /etc/nginx/conf.d/opencs.conf.previous /etc/nginx/conf.d/opencs.conf
sudo nginx -t && sudo systemctl reload nginx
```

### Database

Restore `opencs`/`jupyterhub` from the nightly `db-3` dump or WAL to a scratch
instance first, validate `alembic current`, then switch the DSN. For a primary
failure, promote `db-2`, move `db-vip`, and rebuild the old primary as a
standby with `pg_rewind` or a fresh `pg_basebackup`. Keep the failed node
offline until it is back in sync.

### Notebook node failure

Because homes are on NFS, the custom spawner can start the user on another
`nb-*` node. If homes are node-local instead, restore the student's home from
the NAS rsync before relaunching, and document the affinity limitation.

### Spare

`spare-1..5` can become `lb-2`, `nb-5..nb-9` (to reach ~504 standard slots), a
replacement `db-1`/`db-2`, or `api-4`. Rebuild a spare with the same base OS and
package set; do not leave it as an unpromoted exceptional snowflake.

---

## 13. No-Docker checklist (run before go-live)

```bash
# No container runtime installed or running:
dpkg -l | grep -Ei 'docker|containerd|podman' || true
systemctl list-units --all | grep -Ei 'docker|containerd|podman' || true
test ! -S /var/run/docker.sock

# No Docker references in service units:
grep -R "docker" /etc/systemd/system /etc/opencs 2>/dev/null || true

# No Docker in the application production config:
grep -R "OPENCE_GRADER=docker\|OPENCE_SPAWNER=docker" /etc/opencs 2>/dev/null && exit 1

# Expected production paths:
grep -E 'OPENCE_GRADER=systemd|OPENCE_SPAWNER=ssh-systemd' /etc/opencs/*.env
test -x /usr/local/sbin/opencs-spawn
test -x /usr/local/sbin/opencs-grade-run
```

If any Docker package or socket is present, remove it before continuing. The
deployment must be entirely native systemd.
