# Deployment architecture — OpenCS Labs

Companion to [`INFRASTRUCTURE_INVENTORY.md`](INFRASTRUCTURE_INVENTORY.md).
That document records what the infrastructure *is*; this one records what was
deployed on it and why.

## 1. STRICT RULE: no Docker

`docs/ARCHITECTURE.md` opens with a hard constraint — **no Docker**. The
original brief for this task asked for "Dockerized services where suitable",
which directly contradicts it. The strict rule wins.

This turned out to be the *only* viable path anyway: the targets have no Docker
binary, no `/var/run/docker.sock` and no Kubernetes. A container-based design
could not have been executed there at all.

Deployment is therefore entirely native:

| Layer | Technology |
|---|---|
| Process supervision | `deploy/scripts/svc.sh` (PID file + restart with backoff) |
| Application runtime | Python 3.12 virtualenv, uvicorn |
| Database | PostgreSQL 16, native cluster (`pg_ctlcluster`) |
| Reverse proxy | Nginx 1.24 from the Ubuntu archive |
| Static frontend | Vite production build served by Nginx |

## 2. Topology actually deployed

```
                     (no published HTTP port — see §6)
                                │
                    ┌───────────▼────────────┐
                    │  stu87_sys1  172.17.0.22│
                    │  ─────────────────────  │
                    │  nginx :80  (LB + SPA)  │
                    │  PostgreSQL 16 :5432    │
                    └───┬────────┬────────┬───┘
                        │        │        │   round-robin, max_fails=3
        ┌───────────────▼──┐  ┌──▼─────────────┐  ┌──▼──────────────┐
        │ stu87_sys2       │  │ stu87_sys3     │  │ stu87_sys4      │
        │ 172.17.0.61:8000 │  │ 172.17.0.57    │  │ 172.17.0.39     │
        │ uvicorn (1 worker)│ │ uvicorn        │  │ uvicorn         │
        │ + JupyterLab :8888│ │ + JupyterLab   │  │ + JupyterLab    │
        └──────────────────┘  └────────────────┘  └─────────────────┘
                 │                    │                   │
                 └────────────────────┴───────────────────┘
                             all read/write
                        PostgreSQL @ 172.17.0.22:5432
```

### Machine-to-service table

| Endpoint | Host | Role | Services | Port |
|---|---|---|---|---|
| `.53:2305` | sys1 | Load balancer + DB | nginx, PostgreSQL 16 | 80, 5432 |
| `.53:2306` | sys2 | Backend 1 | uvicorn, JupyterLab | 8000, 8888 |
| `.53:2307` | sys3 | Backend 2 | uvicorn, JupyterLab | 8000, 8888 |
| `.53:2308` | sys4 | Backend 3 | uvicorn, JupyterLab | 8000, 8888 |
| `.79:2221-2224` | — | **not deployed** | no credentials | — |
| `.53:2253-2256` | — | **not deployed** | no credentials | — |

## 3. Why the database is a single node

The briefing asked for four database systems and warned: *"Do not configure
four independent databases that silently diverge."*

Only one node was both credentialled and accessible, so four nodes were not an
option. Rather than fake a cluster, this deployment runs **one PostgreSQL 16
primary** on `stu87_sys1` with:

- a dedicated `opencs` login role (scram-sha-256, generated 43-char password),
- `pg_hba.conf` restricted to the `172.17.0.0/16` app network,
- `listen_addresses = '*'` (required for the three sibling containers),
- native cluster management via `pg_ctlcluster` (no systemd).

**This is not high availability.** The database is a single point of failure.
No streaming replication, no failover, no quorum — because there is no second
database host to replicate to. Stated plainly rather than glossed over.

## 4. Notebook execution — the central limitation

The HLD specifies JupyterHub + KubeSpawner + Kubernetes, one isolated pod per
student. None of that exists here:

- no Kubernetes, no Docker, no systemd,
- so JupyterHub cannot spawn per-user servers.

The application therefore runs `OPENCE_NOTEBOOK_BACKEND=local`: a **single
host-process JupyterLab per backend container**, rooted at
`~/opencs-runtime/notebooks`, with each user's notebooks in a subdirectory.
The application itself documents this backend as development-only and
explicitly notes *"There is no per-user isolation: every notebook server,
kernel and the backend run as the same user."*

What works (verified, see the test report):

- notebook create/list/open/download,
- autosave with content hashing and versions,
- real Python kernels executing pandas against the deployed datasets.

What does not:

- per-user kernel isolation (all users share one JupyterLab per node),
- resource-limited per-student sandboxes,
- WebSocket proxying from the browser through the LB (the local backend serves
  JupyterLab on `localhost:8888` and there is no Hub proxy to mount it).

## 5. Grading

`OPENCE_GRADER=local` runs `grade_runner.py` as a subprocess. The application
flags this as production-unsuitable ("runs untrusted code without isolation");
that is accurate and is documented, not hidden.

## 6. Network reality

- Only SSH ports (2305-2308) are published from the host.
- Ports 80, 443, 8000, 5173 are **closed from outside** the host.
- There is no domain, so no TLS and no `Secure` cookies.
- Consequence: **no public URL exists.** All verification runs inside the
  docker network from `172.17.0.22`.

See [`NETWORK_AND_SECURITY.md`](NETWORK_AND_SECURITY.md).

## 7. Port allocation

| Port | Where | Exposed to | Service |
|---|---|---|---|
| 80 | sys1 | docker network | nginx (LB + SPA) |
| 5432 | sys1 | `172.17.0.0/16` only | PostgreSQL |
| 8000 | sys2/3/4 | `172.17.0.0/16` only | uvicorn |
| 8888 | sys2/3/4 | loopback only | JupyterLab (local backend) |
| 2305-2308 | all | host-mapped SSH | administration |

## 8. Health and failure behaviour

| Failure | Observed behaviour |
|---|---|
| One backend down | LB retries on the next peer; **all requests still 200** (verified: 26/26 with sys4 stopped) |
| Backend crash | `svc.sh` restarts it with exponential backoff (2s → 60s) |
| Backend down > `fail_timeout` | nginx re-admits it automatically once healthy |
| PostgreSQL down | `/ready` fails; `/health` still 200; API DB calls error |
| LB container memory pressure | cgroup OOM killer fires (`oom_kill 31` recorded); nginx itself survives, sshd may starve |

The last row is a real, measured risk: sys1 shares 512 MiB between nginx,
PostgreSQL and a **pre-existing unrelated application** (`pond_deploy`, 4
uvicorn workers). It was the source of the sshd unresponsiveness seen during
rollout. Reducing nginx from 120 to 2 workers fixed the worst of it.
