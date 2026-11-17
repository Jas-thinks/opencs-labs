# PLAN_2 — Distributed Deployment and Capacity Plan

> Status: deployment design after the capacity interview.
> Supersedes the single-host assumptions in `docs/PLAN.md` for production.
> **Hard constraint: no Docker.** This deployment uses native systemd services,
> Python virtualenvs, Nginx, PostgreSQL, PgBouncer and a custom JupyterHub
> spawner. Do not install Docker, DockerSpawner, Swarm, or mount
> `/var/run/docker.sock` on any assigned server.

---

## 1. Confirmed requirements

| Item | Value |
|---|---|
| Students per class | 500 |
| Peak concurrent students in one session | 500 |
| Notebook profile | Heavy: 8–16 GB RAM per student |
| Peak execution | All 500 may run heavy code at the same instant |
| GPU requirement | One GPU per heavy student |
| Database | 3 DB nodes: primary + synchronous hot standby + asynchronous read replica |
| Hardware | 16 homogeneous SSH servers |
| Per server | 32 cores, 128 GB RAM, 2–4 TB NVMe, fast private LAN, NAS available |
| Final allocation | `1 + 3 + 3 + 4 = 11`; five servers unassigned |
| Container runtime | **None. No Docker anywhere.** |

The original request mentioned DockerSpawner and a grader sandbox; the
no-Docker constraint replaces that with a systemd-based design described in
§5 and §9.

---

## 2. Capacity verdict — read this first

**The requested workload is not feasible on the current 11-server allocation,
or on all 16 servers.** This is a hardware limit, not a software limit.

Planning assumptions for every notebook node:

- 128 GB RAM, minus ~16 GB for OS, page cache, JupyterHub/proxy, the spawn
  helper and grading bursts → **~112 GB usable**.
- 32 cores, minus ~4 cores for the same services → **~60 vCPU usable**
  (assuming SMT is enabled; if only 32 logical CPUs are available, CPU density
  is roughly halved and the verdict is worse).

| Notebook profile | Per node | 4 nodes (current) | Nodes for 500 all-active |
|---|---:|---:|---:|
| 16 GB / 4 vCPU | 7 | 28 | 72 |
| 12 GB / 3 vCPU | 9 | 36 | 56 |
| 8 GB / 2 vCPU | 14 | 56 | 36 |
| 2 GB / 1 vCPU | 56 | 224 | 9 |

GPU is still the decisive constraint:

- 500 simultaneous GPU-backed notebooks require **500 GPUs**.
- At 4 GPUs per server, that is **125 notebook nodes**; at 8 GPUs per server,
  it is **63 notebook nodes**.
- Four notebook nodes with 4 GPUs each provide **16 concurrent GPU sessions**;
  with 8 GPUs each, **32**. Neither is 500.

What the 11-server platform **can** do:

1. Admit **~224 resident sessions** at a **2 GB / 1 vCPU** standard profile
   (4 × 56 = 224), with overcommit and admission control. It cannot admit 500
   standard sessions on 4 notebook nodes.
2. Run **~28 concurrent 16 GB CPU-only notebooks**, or **~56 concurrent 8 GB
   notebooks**, or **~36 concurrent 12 GB notebooks**.
3. Run a GPU-heavy pool limited to the **actual number of GPUs installed**
   (for example 16 or 32), with the rest queued.
4. Promote the five unassigned servers to `nb-5..nb-9` to reach ~504 standard
   slots (9 × 56) for a 500-standard class. Heavy/GPU profiles still cannot be
   satisfied by 16 servers.
5. Keep the API and LB tiers comfortably within their capacity; the 3-node DB
   tier adds HA and read scaling, not notebook capacity.

To genuinely serve 500 simultaneous heavy GPU notebooks, add roughly **63–125
additional GPU notebook nodes** (plus platform services) or use external
GPU/cloud burst capacity. That is outside the 16-server limit.

The deployment documents and admission policy must reflect this. On the
current 4 notebook nodes, set `OPENCE_MAX_ACTIVE_SESSIONS` to at most 224 for
the standard profile, 56 for 8 GB, 28 for 16 GB, or the real GPU count. Do not
set it to 500 while running the 16 GB/GPU profile; that would promise capacity
the hardware does not have.

---

## 3. Final topology

```
Server        Role
-----------   ---------------------------------------------------------------
lb-1          Nginx: static SPA, TLS, /api, /hub, /user, WebSocket proxying
api-1..api-3  FastAPI (uvicorn, multiple workers) + opencs-worker (outbox)
db-1          PostgreSQL primary
db-2          PostgreSQL synchronous hot standby
db-3          PostgreSQL asynchronous read replica
nb-1..nb-4    JupyterHub control (nb-1) + per-user systemd JupyterLab
              + systemd-run grading sandbox
spare-1..5    Unassigned warm spares (same base image/OS)
-----------   ---------------------------------------------------------------
Assigned: 11  Unassigned: 5
```

`n_1 = 3`, `n_2 = 4`, `1 + 3 + 3 + 4 = 11 ≤ 16`.

The five spares are deliberately unassigned. Promote them only when measured
load or availability needs justify it:

- `nb-5..nb-9` reaches 9 notebook nodes and ~504 standard 2 GB slots for a
  500-standard class (total 16 servers).
- `db-2`/`db-3` already provide the DB HA design below; a fourth DB node is
  not needed for this scale.
- `api-4` is only useful for API HA beyond the current three nodes.

Heavy/GPU profiles cannot be met by promoting the remaining spares; they need
additional GPU capacity.

---

## 4. Runtime architecture (no Docker)

```
Browser (campus or public)
        │ HTTPS 443
        ▼
   lb-1  Nginx
     ├── /              → /srv/opencs/frontend/dist  (static SPA)
     ├── /api/          → api-1..api-3:8000          (FastAPI)
     ├── /hub/          → nb-1:8000                   (JupyterHub + CHP)
     └── /user/         → nb-1:8000                   (Hub proxy → user server)

   api-1..api-3 ── 6432 ──► db-vip: PgBouncer → db-1 primary (5432)
        │                         │
        │                         ├── db-2 synchronous standby
        │                         └── db-3 asynchronous read replica
        └── 8081 /hub/api ────────┘
                                  │
   nb-1: JupyterHub (Hub DB in PostgreSQL via db-vip)
        │  SSH (restricted helper) to nb-1..nb-4
        ▼
   systemd-run per student: jupyter-<user>.service
        │  NFS /home/opencs/<user>, read-only /opt/opencs/datasets
        ▼
   nb-1..nb-4 systemd-run grading units (no network, no Docker)

   NAS: NFS homes, dataset tree, PostgreSQL WAL archive and dumps
```

### 4.1 Host runtime

- Ubuntu 24.04 LTS (or the institution's current LTS) on every server.
- Python 3.12 virtualenvs:
  - `/opt/opencs/backend-venv` — FastAPI, SQLAlchemy, Alembic.
  - `/opt/opencs/hub-venv` — JupyterHub, idle-culler, the custom spawner.
  - `/opt/opencs/notebook-venv` — JupyterLab and the pinned data-science
    libraries from `notebook-image/requirements.lock`.
- Nginx from the distribution; statically built frontend in
  `/srv/opencs/frontend/dist`.
- PostgreSQL 16 and PgBouncer from the distribution.
- `systemd`, `nftables`, `chrony`, `rsync`, `node_exporter`.
- **No Docker packages, no `/var/run/docker.sock`, no Compose, no Swarm.**

### 4.2 JupyterHub control plane

- One Hub process on `nb-1`, listening on `0.0.0.0:8000` (Configurable HTTP
  Proxy) and `127.0.0.1:8081` (Hub API, reachable only from the LAN).
- Hub database is PostgreSQL `jupyterhub` on `db-vip` (primary `db-1`), not
  SQLite.
- Existing `OpenCSAuthenticator` continues to validate the shared session JWT.
- `jupyterhub-idle-culler` runs as a Hub service and stops idle user servers
  through the same spawner.
- `JUPYTERHUB_CRYPT_KEY` is set so `auth_state` (OpenCS user id/role) survives
  Hub restarts.

### 4.3 Custom SSH/systemd spawner

Because there is no Docker, the Hub cannot use DockerSpawner or SwarmSpawner.
The required component is a small custom spawner,
`jupyterhub/ssh_systemd_spawner.py`, implementing the standard
`jupyterhub.spawner.Spawner` contract:

- `start()`:
  1. Select a notebook node from the `jupyter_nodes` table using least active
     slots, respecting GPU/CPU profile labels.
  2. Allocate a port from the node's `spawn_slots` table (for example
     20000–30000) in a short Postgres transaction.
  3. Open an SSH connection as `opencs-hub` to the node's restricted helper
     and request a start with `(username, uid, port, profile)`.
  4. The helper runs `systemd-run` with the per-user unit and returns when the
     unit is active.
  5. Set `self.ip = <node private IP>` and `self.port = <allocated port>` so
     the Hub proxy routes `/user/<name>/` to the right node.
- `poll()`: SSH helper action `status` → `systemctl is-active
  jupyter-<user>.service`.
- `stop()`: SSH helper action `stop` → `systemctl stop`, then release the
  port slot.
- `get_url()`: return the Hub-relative URL; the browser never talks to the
  notebook node directly.

The SSH key used by the Hub is restricted:

```
from="10.0.0.41",command="/usr/local/sbin/opencs-spawn",no-port-forwarding,\
no-agent-forwarding,no-X11-forwarding,no-pty ssh-ed25519 AAAA... hub@nb-1
```

`opencs-spawn` is a small allow-listed helper (`start|stop|status|health`)
that validates the username, numeric UID, port and profile before invoking
`systemd-run`. It must not accept arbitrary commands.

### 4.4 Per-user systemd units

The helper creates a transient unit with fixed, non-negotiable properties:

```
systemd-run \
  --unit=jupyter-<user> --collect --quiet \
  --uid=opencs-<user> --gid=opencs \
  --property=MemoryMax=<profile-memory> \
  --property=CPUQuota=<profile-cpu-percent> \
  --property=TasksMax=512 \
  --property=NoNewPrivileges=yes \
  --property=ProtectSystem=strict \
  --property=ProtectHome=read-only \
  --property=ReadWritePaths=/home/opencs/<user> \
  --property=ReadOnlyPaths=/opt/opencs/datasets \
  --property=PrivateTmp=yes \
  --property=PrivateDevices=yes \
  --property=RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6 \
  --property=KillMode=control-group \
  --property=WorkingDirectory=/home/opencs/<user> \
  --setenv=HOME=/home/opencs/<user> \
  --setenv=JUPYTERHUB_SERVICE_PREFIX=/user/<user>/ \
  --setenv=JUPYTERHUB_USER=<user> \
  --setenv=JUPYTERHUB_SERVER_NAME= \
  --setenv=JUPYTERHUB_API_URL=http://10.0.0.41:8081/hub/api \
  --setenv=JUPYTERHUB_API_TOKEN=<per-user token> \
  --setenv=JUPYTERHUB_CLIENT_ID=user-<user> \
  /opt/opencs/notebook-venv/bin/jupyterhub-singleuser \
    --ip=<node-private-ip> --port=<port> \
    --ServerApp.base_url=/user/<user>/ \
    --ServerApp.token= --ServerApp.password=
```

GPU profiles override `PrivateDevices=no` and add
`--property=DeviceAllow=/dev/nvidia* rw` (or the exact device nodes) plus
`CUDA_VISIBLE_DEVICES`; do not apply GPU device access to every unit.

Per-user OS accounts are created ahead of the class
(`opencs-<hub_username>`, UID range 20000–30000) and their homes live on NFS.
If per-user OS accounts are operationally impossible, the fallback is a shared
service account with per-user home directories and `ProtectHome=tmpfs` bind
mounts; this weakens isolation and must be documented as a security trade-off.

GPU profiles add `DeviceAllow`/`CUDA_VISIBLE_DEVICES` only for approved users.
There are not enough GPUs for all 500; the GPU pool is sized to the real
inventory.

### 4.6 JupyterLab extension and notebook metadata

- Build `jupyterlab-extension/` once and install the prebuilt labextension
  into `/opt/opencs/notebook-venv` on every `nb-*` node. There is no notebook
  image, so `jupyter labextension list` must show the OpenCS extension for the
  shared venv.
- The backend writes `metadata.opencs.notebook_id`, `state_version` and
  `api_base` into every created notebook. `api_base` must equal
  `OPENCE_API_PUBLIC_BASE` (`https://opencs.example.edu/api/v1`), not a private
  `api-*` address.
- The extension runs inside `/user/<name>/lab`, which is the same public origin
  as `/api`; the session cookie is same-origin and no cross-origin browser
  access to the API nodes is required.
- Autosave/heartbeat remains 30 s in the extension. In distributed mode the
  backend watcher is disabled except on the designated leader, so the extension
  is the primary save path.
- The extension's `configureAutosave` sets JupyterLab's document-manager
  `autosaveInterval` to 30 s; verify it survives JupyterLab upgrades.

### 4.7 NFS homes, datasets and backups

- NAS exports:
  - `/srv/opencs/homes` → mounted at `/home/opencs` on every `nb-*` node,
    per-user quotas (recommended 5–10 GB).
  - `/srv/opencs/datasets` → mounted read-only at `/opt/opencs/datasets`, or
    rsynced to node-local NVMe and made read-only. The notebook code path
    remains `/opt/opencs/datasets`.
  - `/srv/opencs/backups` → PostgreSQL WAL/dumps and configuration backups.
- NFS mount options: `rw,hard,noatime,rsize=1048576,wsize=1048576,vers=4.2`.
- A shared home lets any `nb-*` node run any student. If the NAS cannot serve
  homes, use node-local NVMe plus deterministic user→node affinity and rsync
  backups; document that a node failure requires remounting/restoring that
  student's home before the notebook can start elsewhere.

---

## 5. Tier sizing

### 5.1 Load balancer (`lb-1`)

| Item | Estimate |
|---|---|
| Static SPA | ~500 page loads over 2–5 min; 2–5 rps; assets cached |
| API proxy | 70–120 rps sustained; 300–500 rps at class start and deadlines |
| WebSockets | 500–1000 persistent `/user/<name>/` sockets |
| TLS | 500 handshakes at class start; negligible on 32 cores |
| Nginx | `worker_processes auto`, `worker_connections 8192`, `ulimit -n 65535`, CPU <10%, RAM <2 GB |

Nginx settings required: HTTP/1.1 upstreams with `keepalive`, `Upgrade` and
`Connection` for WebSockets, `proxy_buffering off`, `proxy_read_timeout 3600s`,
`proxy_send_timeout 3600s`, and a health check against `GET /health` (API) and
`GET /healthz` (Nginx).

A single `lb-1` is a single point of failure. One of the five spares can become
`lb-2` with a floating IP or DNS failover later; that is outside the current
11-server assignment.

### 5.2 API nodes (`api-1..api-3`)

| Workload | Total | Per node |
|---|---:|---:|
| Heartbeats (every 30 s) | 16.7 rps | 5.6 rps |
| Autosaves (30 s cadence) | 16.7 rps | 5.6 rps |
| Autosave burst (all edit at once) | ~250 rps | ~83 rps |
| Other API reads | 30–60 rps | 10–20 rps |
| Peak | 300–500 rps | 100–170 rps |

At 5–20 ms per request, one node needs ~2–4 cores; 32 cores is ample. The
three nodes exist for availability and burst absorption, not raw CPU.

Deployment shape per API node:

- 2–4 uvicorn workers (`uvicorn --workers 4`), with
  `OPENCE_BACKGROUND_WORKERS_ENABLED=false` so every worker does not start its
  own watcher/outbox loop.
- One `opencs-worker` systemd process per node running the outbox consumer.
- One designated node (`api-1`) also runs the watcher
  (`OPENCE_WATCHER_ENABLED=true`); the other two set it false. In hub mode,
  three watchers would multiply `contents_get` calls across 500 notebooks.
- PgBouncer in front of PostgreSQL:
  - Client connections: 3 nodes × 4 workers × 10 pool = 120.
  - PgBouncer `pool_mode=transaction`, `max_client_conn=500`,
    `default_pool_size=30–40`, `reserve_pool_size=5`.
- Rate limiting is currently per process. Three API processes therefore
  multiply every effective limit by three. Either divide the configured limits
  by three or replace the limiter with a shared PostgreSQL/Redis implementation
  (§8).

### 5.3 Notebook nodes (`nb-1..nb-4`)

Usable per node: ~112 GB RAM, ~60 vCPU.

| Profile | Per node | 4 nodes (current) | 500 all-active |
|---|---:|---:|---:|
| 16 GB / 4 vCPU | 7 | 28 | 72 nodes |
| 12 GB / 3 vCPU | 9 | 36 | 56 nodes |
| 8 GB / 2 vCPU | 14 | 56 | 36 nodes |
| 2 GB / 1 vCPU | 56 | 224 | 9 nodes |

Grading sandbox:

- 1 GB / 1 vCPU per concurrent evaluation.
- Concurrency cap 4–8 per node; 4 nodes → 16–32 concurrent graders.
- 500 submissions at 16–32 concurrent × 30–90 s each = roughly 8–47 minutes
  of grading, assuming a full burst. Queue rather than spawning 500 units.

JupyterHub/spawn overhead:

- The Hub, CHP, idle-culler, Nginx local health checks and SSH helper use
  ~2–4 GB and ~2–4 vCPU on `nb-1`; reserve that in the density table.
- Spawn rate: 500 starts in a burst if the five spares are promoted to
  `nb-5..nb-9`. Pre-create OS accounts and homes, pre-pull no images (no
  Docker), and pre-install the venv. The bottleneck is systemd unit starts and
  Python/Jupyter startup (~1–4 s each), not network.

### 5.4 Database tier (`db-1..db-3`)

| Dimension | Estimate |
|---|---|
| Heartbeats | ~33 row updates/s (notebooks + sessions) |
| Autosaves | 17–50 version writes/s; <50 MB/s at 1 MB notebooks |
| Submissions/grades | 2–10/s |
| Peak write IOPS | <500; NVMe handles tens of thousands |
| Connections | 60–240 client connections via PgBouncer |
| Analytics | 10k submissions and ~200k criterion scores per class; indexed queries <300 ms |
| Blob storage per class | ~30–300 GB at 100 KB–1 MB per version after SHA dedup |
| 3–5 semesters retained | ~150 GB–1.5 TB plus indexes/WAL |

The write load is far below one NVMe primary. The 3-node tier is for
availability and read scaling, not throughput:

- `db-1`: primary.
- `db-2`: synchronous hot standby (`synchronous_commit=remote_write`,
  `synchronous_standby_names='db-2'`).
- `db-3`: asynchronous read replica for reporting/backup reads; the application
  still uses the primary unless read routing is added.
- PgBouncer on `db-1`/`db-2`, fronted by a `db-vip` (keepalived or DNS) so a
  primary failure can promote `db-2` without changing every API env file.

A primary failure is still a platform outage until failover completes, but the
3-node tier removes the single-node data-loss risk. The five spares can provide
a replacement primary or a second read replica if needed.

---

## 6. Database storage and replication design

### 6.1 Primary + standby + read replica, no sharding

- `db-1`: PostgreSQL 16 primary.
- `db-2`: synchronous hot standby, promoted on primary failure.
- `db-3`: asynchronous read replica for reporting/backup reads.
- PgBouncer on `db-1`/`db-2`, transaction pooling, behind a `db-vip`
  (keepalived or DNS) so the application DSN does not change on failover.
- Do **not** shard. The schema has course-scoped, small-to-medium tables:
  - 500 students × 20 assignments ≈ 10k submissions.
  - ~200k criterion scores.
  - Notebook blobs are content-addressed and deduplicated.
  - Cross-course analytics, rosters and reporting views need joins across
    courses, assignments, submissions and grades. Sharding would make those
    queries and the existing `v_*` views much harder.
- The write rate (<500 IOPS) and read rate are well within one NVMe primary.
  The extra DB nodes are for HA and read scale, not write throughput.

Replication/partitioning/sharding comparison:

| Strategy | Fit for this schema | Notes |
|---|---|---|
| Primary + sync standby + async read replica | **Chosen** | `db-1` primary, `db-2` sync standby, `db-3` async replica; `n_1=3`, `n_2=4` |
| Single primary | Would handle the write volume, but no HA | Not chosen now that 3 DB nodes are allocated |
| Table partitioning | Later, if retention grows | Time-based partitions for `notebook_versions`, `submissions`, `jobs`; no cross-node joins |
| Sharding | **Rejected** | Course/assignment/submission/grade analytics and the `v_*` views need cross-course joins; sharding would complicate every roster and dashboard query for no throughput benefit at 500 students |

### 6.2 Tuning starting points

`postgresql.conf`:

```
shared_buffers = 24GB
effective_cache_size = 72GB
work_mem = 48MB
maintenance_work_mem = 2GB
max_connections = 200
wal_level = replica
archive_mode = on
archive_command = 'test ! -f /srv/opencs/backups/wal/%f && cp %p /srv/opencs/backups/wal/%f'
max_wal_size = 8GB
checkpoint_timeout = 15min
random_page_cost = 1.1
effective_io_concurrency = 200
```

Set `application_name=db-2` in `db-2`'s `primary_conninfo`; otherwise
`synchronous_standby_names='db-2'` will not match and synchronous commits can
block. `db-3` uses `application_name=db-3` and is asynchronous.

PgBouncer:

```
[databases]
opencs = host=127.0.0.1 port=5432 dbname=opencs
jupyterhub = host=127.0.0.1 port=5432 dbname=jupyterhub pool_mode=session

[pgbouncer]
listen_addr = 0.0.0.0
listen_port = 6432
pool_mode = transaction
max_client_conn = 500
default_pool_size = 35
reserve_pool_size = 5
reserve_pool_timeout = 5
server_idle_timeout = 60
```

The backend DSN includes `?prepare_threshold=0` because psycopg 3 and
transaction pooling must not use client-side prepared statements. The
`jupyterhub` database uses session pooling for the Hub's psycopg2 connection.

### 6.3 Backups and recovery

- Continuous WAL archiving from `db-1` to NAS
  (`/srv/opencs/backups/wal`).
- Nightly `pg_dump -Fc` of `opencs` and `jupyterhub` from the `db-3` read
  replica to NAS, so backups do not load the primary.
- Weekly restore drill into a scratch database; run `alembic current` and
  `SELECT count(*) FROM notebooks`.
- Target RPO ≤ 15 minutes with WAL; RTO 30–60 minutes for a full restore or
  standby promotion.
- Back up `/etc/opencs`, Nginx config, systemd units, the Hub venv/config and
  the custom spawner alongside the database.

### 6.4 Retention and bloat

- Autosave versions: newest 20 per notebook (`OPENCE_AUTOSAVE_RETENTION=20`).
- Submission versions: never pruned.
- Orphan blobs: garbage-collected when no version references them.
- `prune_autosaves` and `close_idle_sessions` must run under a singleton
  advisory lock (§8.2) so three workers do not prune concurrently.
- Alert when `db-1` data + WAL exceeds 70% of the NVMe size.

---

## 7. Admission and capacity policy

The platform cannot admit 500 heavy/GPU sessions on this hardware. Use profiles
and admission control rather than overcommitting silently.

Recommended profiles:

| Profile | RAM / CPU | Intended use | Max admitted on 4 nodes |
|---|---|---|---:|
| `standard` | 2 GB / 1 vCPU | Default for a 500-student class | 224 (resident) |
| `medium` | 8 GB / 2 vCPU | Approved EDA/ML subset | 56 |
| `heavy` | 16 GB / 4 vCPU | Approved CPU-heavy work | 28 |
| `gpu` | GPU + 8–16 GB | Approved GPU work | actual GPU count (e.g. 16/32) |

- Set `OPENCE_MAX_ACTIVE_SESSIONS` to the real limit for the active profile,
  not a blanket 500. On 4 notebook nodes, the standard ceiling is 224; promote
  all five spares to `nb-5..nb-9` (total 16 servers) if the class needs the full
  500 standard sessions. For `heavy`, set ~28; for `gpu`, set the GPU count.
- The SPA and API must surface a clear `CAPACITY_EXHAUSTED` / queue state
  instead of an opaque 503.
- Queue heavy/GPU launches behind a simple admission queue (database table or
  the existing jobs table). Serve the standard profile to the rest of the
  class.
- The docs and the instructor-facing capacity report must state the measured
  numbers, not the requested 500-heavy number.

---

## 8. Required codebase changes

These are implementation work items for the distributed, no-Docker deployment.
They are not yet in the repository.

### 8.1 Multi-worker outbox with `FOR UPDATE SKIP LOCKED`

Current `app/core/jobs.py` selects a pending job and then updates it. On
PostgreSQL this is close to correct because the select locks the row, but the
claim, the stuck-job reclaim and the maintenance scheduling should be made
atomic and explicitly Postgres-aware.

Replace the claim with one statement:

```sql
UPDATE jobs
SET status = 'running',
    locked_at = now(),
    attempts = attempts + 1
WHERE id = (
    SELECT id
    FROM jobs
    WHERE status = 'pending' AND run_at <= now()
    ORDER BY run_at
    FOR UPDATE SKIP LOCKED
    LIMIT 1
)
RETURNING *;
```

- Run it inside a short transaction; commit immediately after the claim.
- Keep the SQLite fallback for development/tests, but production must use
  PostgreSQL.
- Add `app/worker.py` (or a console script) so each API node can run one
  `opencs-worker` systemd unit:
  `python -m app.worker` → `job_worker_loop` with
  `OPENCE_BACKGROUND_WORKERS_ENABLED=true`.
- Set `OPENCE_BACKGROUND_WORKERS_ENABLED=false` on the uvicorn API processes so
  4 workers × 3 nodes do not create 12 duplicate outbox loopss.

### 8.2 Singleton maintenance with advisory locks

`close_idle_sessions` and `prune_autosaves` must run once cluster-wide, not
once per API node. Use PostgreSQL session advisory locks:

```sql
SELECT pg_try_advisory_lock(hashtext('opencs:close_idle_sessions'));
-- run the handler only if true
SELECT pg_advisory_unlock(hashtext('opencs:close_idle_sessions'));
```

Wrap each handler in `try/finally` so the lock is always released. Also make
`schedule_maintenance` idempotent across nodes:

- Add a partial unique index on `jobs (kind) WHERE status IN ('pending','running')`
  and use `INSERT ... ON CONFLICT DO NOTHING`, or
- Guard the scheduler with a `pg_try_advisory_xact_lock`.

The current `schedule_maintenance` does a read-then-insert and is race-prone
when three workers start together.

### 8.3 Scope or disable the in-process watcher

Current `app/notebooks/watcher.py` polls every active session every 10 s and
calls JupyterHub `contents_get`. With three API nodes and 500 notebooks that is
up to ~150 contents calls/s and duplicated snapshots.

- Add `OPENCE_WATCHER_ENABLED` (default `false` in distributed production).
- Enable it on exactly one worker (`api-1` or a dedicated worker) with a
  Postgres advisory lock/leader election, or disable it entirely and rely on
  the JupyterLab extension + JupyterLab's 30 s autosave.
- Keep the extension's `PUT /autosave` and heartbeat as the primary path.
- If the watcher is enabled, batch/paginate sessions and skip notebooks whose
  `content_sha256` already matches.

### 8.4 Shared rate limiting

The current `SlidingWindowLimiter` is in-process. Three API nodes multiply the
effective limits by three. Choose one:

1. Accept it and divide the configured limits by three (simplest; document it).
2. Store sliding-window events in PostgreSQL (`rate_limit_events` with a
   timestamp index and periodic cleanup) or a native Redis package. No Docker
   is required for Redis; it is a native systemd service.
3. Use `pg_advisory_xact_lock` per principal for coarse-grained limiting.

For 500 users, a PostgreSQL-backed limiter is sufficient if option 2 is chosen.
Do not leave the per-process behavior undocumented.

### 8.5 JupyterHub custom spawner and configuration

- Add `jupyterhub/ssh_systemd_spawner.py` implementing `start`, `poll`, `stop`,
  `get_url`, and node/port allocation as described in §4.3.
- Add `opencs-spawn` helper on every `nb-*` node and the restricted SSH key.
- Add `jupyter_nodes` and `spawn_slots` tables to PostgreSQL (or a small
  dedicated database) for node inventory and port allocation.
- Update `jupyterhub/jupyterhub_config.py`:
  - `OPENCE_SPAWNER=ssh-systemd` selects the custom spawner; refactor the
    current `if SPAWNER == "docker" ... else KubeSpawner` branch into explicit
    `docker`, `kubernetes`, and `ssh-systemd` branches. Do not let
    `ssh-systemd` fall into the KubeSpawner trait block.
  - Remove DockerSpawner/SwarmSpawner from the production path.
  - `c.JupyterHub.db_url` points at PostgreSQL `jupyterhub` on `db-vip`
    (primary `db-1`).
  - Keep `OpenCSAuthenticator`, idle-culler, `cleanup_servers=True`.
  - Set `JUPYTERHUB_CRYPT_KEY` and `enable_auth_state`.
  - Set `start_timeout` and `http_timeout` for 500-user class starts.
- Add per-user OS account provisioning (`opencs-<hub_username>`, UID range
  20000–30000) and NFS home creation. This is a deployment script, not a
  request-time operation.
- The existing `LocalNotebookBackend` remains for development only; production
  uses `OPENCE_NOTEBOOK_BACKEND=hub` against the Hub API.

### 8.6 `SystemdSandbox` for grading (no Docker)

Add a new sandbox strategy to `backend/app/integrations/grader.py`:

- `SystemdSandbox.available()` checks `systemd-run` and the wrapper.
- `run(work)` invokes `/usr/local/sbin/opencs-grade-run <unit> <work>` via a
  narrow sudoers rule, or the helper runs as a dedicated `opencs-grader` user.
- The wrapper validates the staging path and runs:
  `systemd-run --wait --collect --quiet --unit=<unit>
  --uid=opencs-grader --gid=opencs-grader
  --property=MemoryMax=1G --property=CPUQuota=100%
  --property=PrivateNetwork=yes --property=NoNewPrivileges=yes
  --property=ProtectSystem=strict --property=ProtectHome=yes
  --property=PrivateTmp=yes --property=ReadOnlyPaths=/opt/opencs/datasets
  --property=BindPaths=<work> --property=RuntimeMaxSec=120
  --setenv=MPLBACKEND=Agg
  /opt/opencs/notebook-venv/bin/python /opt/opencs/grade_runner.py <work>`
- Set `OPENCE_GRADER=systemd`, `OPENCE_GRADER_VENV`,
  `OPENCE_GRADER_WRAPPER`, `OPENCE_GRADER_CONCURRENCY`.
- Remove the Docker socket mount and `DockerSandbox` from production config.
- Queue grading to avoid 500 simultaneous units:
  - Add a `grade_attempt` job and a grader worker on `nb-*` nodes.
  - The existing synchronous `POST /practice/attempts/{id}/evaluate` can keep
    working for small classes; for large classes return `202 Accepted` with a
    job id and add a status endpoint, or keep it synchronous behind a bounded
    semaphore.
  - Cap concurrency per node (`OPENCE_GRADER_CONCURRENCY=4–8`).

### 8.7 Configuration summary

| Variable | Value |
|---|---|
| `OPENCE_ENV` | `production` |
| `OPENCE_NOTEBOOK_BACKEND` | `hub` |
| `OPENCE_GRADER` | `systemd` |
| `OPENCE_API_PUBLIC_BASE` | `https://opencs.example.edu/api/v1` |
| `OPENCE_PUBLIC_ORIGIN` | `https://opencs.example.edu` |
| `OPENCE_CORS_ORIGINS` | `https://opencs.example.edu` |
| `OPENCE_COOKIE_SECURE` | `true` |
| `OPENCE_AUTH_MODE` | `oidc` (production refuses `dev`) |
| `OPENCE_DATABASE_URL` | `postgresql+psycopg://opencs:...@db-vip:6432/opencs?prepare_threshold=0` |
| `OPENCE_HUB_DB_URL` | `postgresql+psycopg2://...@db-vip:6432/jupyterhub` |
| `OPENCE_JUPYTERHUB_API_URL` | `http://nb-1:8081/hub/api` |
| `OPENCE_JUPYTERHUB_PROXY_URL` | `http://nb-1:8000` |
| `OPENCE_JUPYTERHUB_PUBLIC_URL` | `https://opencs.example.edu` |
| `OPENCE_DATASET_SERVING_DIR` | `/opt/opencs/datasets` |
| `OPENCE_BACKGROUND_WORKERS_ENABLED` | `false` on API; `true` on worker |
| `OPENCE_WATCHER_ENABLED` | `true` on `api-1` only; `false` elsewhere |
| `OPENCE_MAX_ACTIVE_SESSIONS` | real admitted capacity (28/56/224 by profile on 4 nodes) |
| `OPENCE_RATE_LIMIT_*` | divide by 3 or move to a shared limiter |
| `OPENCE_GRADER_CONCURRENCY` | 4–8 per `nb-*` node |

### 8.8 Tests to add

- Two `JobWorker` instances against one PostgreSQL test database: each job is
  claimed exactly once (`FOR UPDATE SKIP LOCKED`).
- Advisory-lock test: two concurrent `close_idle_sessions` runs, only one
  performs the update.
- Watcher disabled/leader test: only the designated worker snapshots.
- `SystemdSandbox` unit test using a fake `systemd-run` wrapper; skip when the
  binary/wrapper is absent.
- Custom spawner test with a fake SSH helper: node selection, port allocation,
  start/poll/stop, leaked-port cleanup.
- Grade queue/concurrency test: 100 queued grade jobs never exceed the
  configured sandbox concurrency.
- Existing `test_migrations.py` and the full backend suite must pass.

---

## 9. Deployment phases (details in `DEPLOYMENT.md`)

1. **Base OS and network**: Ubuntu LTS, users, SSH keys, NTP, nftables,
   no Docker, no container packages.
2. **`db-1..db-3`**: PostgreSQL 16 primary + synchronous standby + asynchronous
   read replica, PgBouncer on the primary/standby, `db-vip`, databases/roles,
   WAL archive to NAS.
3. **`api-1..3`**: backend venv, systemd API + worker units, Alembic migration,
   `db-vip` DSN, PgBouncer/connection-pool verification.
4. **`nb-1..nb-4`**: NFS homes, per-user accounts, notebook venv, dataset sync,
   JupyterHub + custom spawner + spawn helper, idle culler.
5. **`lb-1`**: static frontend, TLS, `/api` and `/hub`/`/user` proxy,
   WebSocket settings, health checks.
6. **Grading**: systemd-run wrapper, sudoers, grader worker, concurrency cap.
7. **Smoke and load test**: staged 10/50/100/224; spawn burst; grading burst;
   record measured capacity. A 500-standard test requires promoting
   `spare-1..5` to `nb-5..nb-9` first.
8. **Backup/restore drill** and **rollback rehearsal**.
9. **Promote `spare-1..5`** only when measured load or availability needs
   justify it: `nb-5..nb-9` for 500 standard sessions, or a replacement DB/API
   node. Heavy/GPU capacity still requires new GPU hardware.

---

## 10. Risks and mitigations

| Risk | Mitigation |
|---|---|
| 500 simultaneous 16 GB GPU notebooks cannot fit in the 11-server allocation or 16 servers | State the verdict; cap the heavy/GPU profiles; queue; add 63–125 GPU nodes for the full target |
| 500 standard 2 GB sessions do not fit on 4 notebook nodes (224 max) | Promote `spare-1..5` to `nb-5..nb-9` (9 × 56 = 504) when the class needs all 500; otherwise cap at 224 |
| No Docker means no container isolation | Per-user OS accounts, systemd sandboxing, `ProtectSystem`, `ProtectHome`, `PrivateTmp`, cgroup memory/CPU limits, NFS quotas; document the residual risk |
| Primary DB failure | `db-2` synchronous standby + `db-vip`; promote `db-2`; dumps from `db-3`; restore drill |
| Single LB and single Hub are SPOFs | Health checks, fast systemd restart; one spare can become `lb-2`; the Hub can move to another `nb-*` with NFS homes |
| Three watchers duplicate Hub reads | `OPENCE_WATCHER_ENABLED=false` on two nodes; leader/advisory lock |
| Outbox double-claim / duplicate maintenance | `FOR UPDATE SKIP LOCKED`; advisory locks; unique partial index |
| Rate limits triple across API nodes | Shared limiter or divide configured limits by 3 |
| NFS latency/throughput | 10 GbE, NFSv4.2, `noatime`, large rsize/wsize; monitor; node-local scratch |
| Hub JSON/SQLite corruption | Hub DB in PostgreSQL, not SQLite |
| Spawn burst overwhelms SSH/systemd | Pre-create users/homes, pre-install venv, limit concurrent spawns, start class in waves if necessary |
| Grading burst | Queue + per-node concurrency cap; 16–32 concurrent graders on 4 nodes |
| DB analytics slow at 500 students | Existing indexes/views; `db-3` read replica is available for future read routing; measure p95 |

---

## 11. Verification and load test plan

- **Unit**: outbox multi-worker claim, advisory locks, watcher leader, systemd
  sandbox, spawner fake SSH, grade concurrency.
- **Integration**: 10 users start/stop notebooks; one grade via systemd-run;
  PgBouncer connection count; Hub DB in PostgreSQL; standby promotion drill.
- **Staged load** (measured, not invented), on the 11-server allocation:
  1. 10 users, 2 min.
  2. 50 users, 5 min.
  3. 100 users, 10 min.
  4. 224 users (standard 2 GB ceiling), 10 min.
  5. Promote `nb-5..nb-9` and run 500 users, 15 min.
  6. 500 spawn burst, 5 min.
  7. Grading burst: 100 queued evaluations.
- Record API p95/error rate, spawn success/time, active notebooks per node,
  node CPU/RAM, NFS latency, DB connections/PgBouncer wait, WebSocket count,
  and grader queue time.
- Publish the measured ceiling. The expected outcome is that 224 standard
  2 GB sessions fit on 4 notebook nodes, 500 standard fits only after promoting
  `nb-5..nb-9`, and 500 heavy/GPU sessions cannot be served by 16 servers.

---

## 12. Open prerequisites

- Implement OIDC authorization-code/callback or explicitly use dev auth on a
  closed intranet. The repository currently implements only
  `/auth/login` and `/auth/token` (dev email/password); `OPENCE_AUTH_MODE=oidc`
  is a setting without a login flow.
- Confirm the actual GPU count and model per `nb-*` node. The capacity verdict
  depends on it.
- Confirm the NAS can export NFS homes for 500 users and has 3–5 TB free for
  homes plus PostgreSQL WAL/dumps.
- Confirm 32c means 32 physical cores with SMT (≈64 logical CPUs). If it means
  32 logical CPUs, reduce the density table accordingly.
- Confirm the campus/public hostname and TLS certificate source.
- Confirm whether content seeding can run in production or must be a separate
  content-import step (the current seed script refuses demo users in
  production).
- Confirm whether the five spares may be promoted to `nb-5..nb-9` for a
  500-standard class; otherwise the standard admission ceiling is 224.
