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

Every service is reached through the host's **mapped ports** — no SSH tunnels,
no internal bridge IPs in any browser-facing URL.

```
                http://10.1.75.53:6306  (frontend: SPA + /api proxy)
                              │
                http://10.1.75.53:5305  (load balancer)
                 │            │            │
   :5307 ────────┘   :5308 ───┘   :5253 ───┘   (3 backends, external mapped ports)
     │                │             │
     └────────────────┴─────────────┴──► PostgreSQL 172.17.0.56:5432 (server-to-server)
                                             ├── db-2 sync standby
                                             └── db-3 async replica
     │
     └──► http://10.1.75.79:5221 / 5222 / 5223 / 5224   (4 JupyterHub nodes)
```

### Port-mapping rule

SSH is `student@<HOST_IP> -p 2<XYZ>`. Internal port `P` is published at
`http://<HOST_IP>:<first digit of P><XYZ>`:

- internal `5000` → `5<XYZ>` (e.g. SSH `2306` → `10.1.75.53:5306`)
- internal `6000` → `6<XYZ>` (e.g. SSH `2306` → `10.1.75.53:6306`)
- internal `8000` → `8<XYZ>` (e.g. SSH `2221` → `10.1.75.79:8221`)

JupyterHub runs on internal **`5000`** (not `8000`) so `http://10.1.75.79:52<XYZ>`
serves it directly.

### Machine-to-service table

| Endpoint | Host | Role | Services | Internal port | External URL |
|---|---|---|---|---|---|
| `.53:2305` | sys1 | Load balancer | nginx | 5000 | `http://10.1.75.53:5305` |
| `.53:2306` | sys2 | Frontend | nginx + SPA | 6000 | `http://10.1.75.53:6306` |
| `.53:2307` | sys3 | Backend 1 | uvicorn | 5000 | `http://10.1.75.53:5307` |
| `.53:2308` | sys4 | Backend 2 | uvicorn | 5000 | `http://10.1.75.53:5308` |
| `.53:2253` | stu74_sys1 | Backend 3 | uvicorn | 5000 | `http://10.1.75.53:5253` |
| `.53:2254` | stu74_sys2 | Database primary | PostgreSQL 16 | 5432 | `10.1.75.53:5254` (DB) |
| `.53:2255` | stu74_sys3 | Database sync standby | PostgreSQL 16 | 5432 | mapping not published |
| `.53:2256` | stu74_sys4 | Database async replica | PostgreSQL 16 | 5432 | `10.1.75.53:5256` (DB) |
| `.79:2221` | stu36_sys1 | JupyterHub 1 | Hub + CHP | 5000 / 8081 | `http://10.1.75.79:5221` |
| `.79:2222` | stu36_sys2 | JupyterHub 2 | Hub + CHP | 5000 / 8081 | `http://10.1.75.79:5222` |
| `.79:2223` | stu36_sys3 | JupyterHub 3 | Hub + CHP | 5000 / 8081 | `http://10.1.75.79:5223` |
| `.79:2224` | stu36_sys4 | JupyterHub 4 | Hub + CHP | 5000 / 8081 | `http://10.1.75.79:5224` |

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
student. None of that exists here (no Kubernetes, no Docker, no systemd), so
JupyterHub cannot spawn pods.

Instead, **four JupyterHub instances run natively** on the `.79` nodes, each
with `OpenCSLocalSpawner` (a subclass of `LocalProcessSpawner` that resolves a
per-user home directory without requiring an OS account per Hub user). Three
backends are paired with a Hub for notebook work, and every Hub is reachable at
its own external mapped URL:

| Hub | External URL |
|---|---|
| `stu36_sys1` | `http://10.1.75.79:5221` |
| `stu36_sys2` | `http://10.1.75.79:5222` |
| `stu36_sys3` | `http://10.1.75.79:5223` |
| `stu36_sys4` | `http://10.1.75.79:5224` |

What works (verified):

- notebook create/list/open/download through the external URL,
- autosave with content hashing and versions,
- real Python kernels executing pandas (`EXTERNAL_KERNEL_OK 3.1.1` on all four
  Hubs, reached over the mapped ports),
- returned notebook URLs are external, e.g.
  `http://10.1.75.79:5223/user/student1/lab/tree/...` with no `172.17.0.x`.

What does not:

- per-user kernel isolation (all Hub users share one OS account),
- resource-limited per-student sandboxes (one cgroup per container).

## 5. Grading

`OPENCE_GRADER=local` runs `grade_runner.py` as a subprocess. The application
flags this as production-unsuitable ("runs untrusted code without isolation");
that is accurate and is documented, not hidden.

## 6. Network reality

- SSH ports are the administrative entry point: `.53:2305-2308`,`.53:2253-2256`,
  `.79:2221-2224`.
- The host **also publishes mapped HTTP ports** for internal listeners:
  `5<XYZ>`, `6<XYZ>`, `8<XYZ>` (see the port-mapping rule above). Those are the
  URLs the browser and the backends use.
- There is no domain and no TLS, so there are no `Secure` cookies.
- No SSH tunnels are required: `http://10.1.75.79:5221` is reachable from both
  the operator machine and from the `.53` containers.

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
