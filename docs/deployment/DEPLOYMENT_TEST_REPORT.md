# Deployment test report — OpenCS Labs

All results below were produced by running commands against the deployed stack
on 2026-11-17. Nothing here is inferred from configuration files. Where a test
could not be run, it says so.

**Deployed commit:** `65f3e11` (`main`), verified identical on all three
backend containers.

## 1. Infrastructure

| Test | Result |
|---|---|
| All 12 SSH endpoints TCP-reachable | **12/12 reachable** |
| All 12 endpoints authenticated | **4/12** — 8 rejected every credential (see inventory) |
| Target containers identified | `stu87_sys1..4` |
| Shared machine-id across 2305-2308 | **Confirmed identical** → one host, four containers |
| cgroup limits read | **1 CPU / 512 MiB per container** |
| systemd present | **No** (`PID 1 = sshd`) |
| Docker present | **No** |
| Disk | 247 GB, ~48 GB free (81% used) |

## 2. Load balancer

| Test | Result |
|---|---|
| nginx config valid | PASS (`nginx -t`) |
| Listener count on :80 | 1 (no competing LB) |
| `/healthz` | **200** |
| Frontend `/` | **200**, 520 bytes (SPA shell) |
| `GET /health` via LB | **200** `{"status":"ok","version":"0.1.0"}` |
| `GET /ready` via LB | **200** `{"status":"ready","database":"ok"}` |
| `GET /api/v1/config` via LB | **200** |
| Round-robin distribution | **3 / 3 / 3** across all three backends |
| All three backends healthy | PASS |

### Failover test (controlled)

Stopped `stu87_sys4` (172.17.0.39) completely, confirmed `ss` showed no
listener and `pgrep` showed no uvicorn process, then issued requests:

| Metric | Result |
|---|---|
| 20 requests `GET /api/v1/config` | **20 × 200** |
| 6 requests `POST /api/v1/auth/login` (DB-backed) | **6 × 200** |
| nginx behaviour | logged `connect() failed (111) ... upstream 172.17.0.39`, then `upstream server temporarily disabled`, retried on a healthy peer |

Restored sys4 → `/health` 200 → after `fail_timeout` it re-entered rotation.

> Measurement note: `$upstream_addr` logs the *first* peer attempted, so during
> the outage lines still mention `.39` while the response came from a peer that
> nginx retried onto. The absence of any 5xx is the real evidence.

## 3. Database

| Test | Result |
|---|---|
| PostgreSQL 16 installed natively | PASS |
| Cluster started (`pg_ctlcluster`, no systemd) | PASS |
| `pg_isready` | **accepting connections** |
| Listening | `0.0.0.0:5432` |
| Role + database created | `opencs` / `opencs`, owner `opencs` |
| Auth from all three backends | **3/3** `DB_OK opencs opencs PostgreSQL 16.15` |
| Migrations applied (once, on sys2) | PASS — `f443308c6e53 → 9a1f2b3c4d5e` |
| `alembic current` | `9a1f2b3c4d5e (head)` |
| Seed | 5 users, 1 course, 12 modules, **21 lessons**, **22 exercises**, 9 datasets, 1 assignment + rubric |
| Empty-password rejection | verified — a quoting bug produced an empty password and PostgreSQL refused it |

## 4. Code execution

| Test | Result |
|---|---|
| JupyterLab started by the app | PASS (log: "Jupyter Server 2.21.1 is running at http://localhost:8888/lab") |
| Notebook create | **201**, returns notebook record |
| Notebook list | **200** |
| Autosave with `base_version`/`document` | **200**, `{"version":1,"saved":true,"sha256":"391ab4ca…","version_number":1}` |
| Version history after autosave | **200**, 1 entry, `kind: autosave` |
| Notebook download | **200**, valid `.ipynb` |
| Open URL resolution | **200** |
| **Real kernel execution** | **PASS** — nbclient, kernel `python3` |
| ↳ pandas read of deployed dataset | `150 5.84` (Iris: 150 rows, mean sepal length 5.84) |
| ↳ second cell (`value_counts`) | executed, no error |

### Honest scope of "code execution"

Execution is real but **not isolated per user**. One JupyterLab process per
backend container serves every user of that node as the same OS user. There is
no per-student pod, no CPU/memory quota per kernel, and no cross-user
filesystem protection at the kernel level. This is the `local` backend's
documented design, and it is the direct consequence of having no Docker or
Kubernetes.

## 5. Application

| Test | Result |
|---|---|
| `POST /api/v1/auth/login` (student) | **200**, session cookie set |
| `GET /api/v1/me` with cookie | **200**, correct user |
| `GET /api/v1/me` without cookie | **401** |
| `GET /api/v1/learning/paths` | **200**, curriculum returned |
| `GET /api/v1/datasets` | **200**, 9 datasets with licence + row counts |
| `GET /api/v1/datasets/iris/snippet` | **200**, `auto_execute: false`, read-only path |
| `GET /api/v1/practice/exercises` | **200** |
| `GET /api/v1/notebooks` | **200** |
| `GET /api/v1/courses` | **200** |
| `GET /api/v1/courses/{id}/assignments` (instructor) | **200** |
| `GET /api/v1/me/grades` (student) | **200** |
| `GET /api/v1/analytics/me` (student) | **200** (completion, scores, time-on-task) |
| `GET /api/v1/analytics/courses/{id}` as **student** | **403** (RBAC enforced) |
| `GET /api/v1/analytics/courses/{id}/export.csv` (instructor) | **200** |
| `GET /metrics` | **200**, Prometheus exposition |
| `GET /api/docs` | **200** |

## 6. Backend test suite

Run on `stu87_sys2` against the deployed code, clean checkout (no `.env`):

```
124 passed, 1 warning in 504.94s (0:08:24)
```

## 7. Load test (measured)

Driven from the LB node through nginx, authenticated `GET /api/v1/notebooks`:

| Stage | Concurrency | Requests | Errors | Throughput | p50 | p95 | p99 |
|---|---|---|---|---|---|---|---|
| Baseline | 1 | 20 | **0** | 15.1 req/s | 32 ms | 66 ms | 69 ms |
| Stage 2 | 10 | 100 | **0** | 25.0 req/s | 192 ms | 308 ms | 595 ms |
| Stage 3 | 25 | 250 | **0** | 28.3 req/s | 222 ms | 396 ms | 496 ms |

**370 requests, 0 errors.** Throughput plateaus around 28 req/s, consistent
with three single-worker backends on 1 CPU each.

### What this is NOT

- **Not evidence for 400 concurrent notebook users.** The HLD's 400-user
  target assumes one pod per user on a real cluster. This deployment has
  three containers, one shared JupyterLab per node, and 1 CPU each.
- Stages 50/100/200/400 were **not attempted**. Each container has 512 MiB and
  sys1 was already exhibiting cgroup OOM kills (`oom_kill 31`) from unrelated
  memory pressure. Running those stages would have measured the OOM killer and
  risked destabilising a shared host, which the brief explicitly forbids.
- A short burst of 20-way parallelism during an earlier test did starve sys1's
  sshd (services kept serving; only the shell was affected). That is recorded
  as a real capacity limit, not hidden.

## 8. Failure behaviour observed

| Scenario | Observed |
|---|---|
| Backend stopped | LB served 26/26 requests from remaining peers |
| Backend restored | Re-admitted after `fail_timeout` |
| Backend crash | Supervisor restarted with backoff (2s, 4s, … capped 60s) |
| Production-mode env | App **refused to start** with 7 explicit config errors — guardrails work |
| nginx `worker_processes auto` | Forked 120 workers in a 512 MiB cgroup → sshd starvation; fixed by pinning 2 workers |
| Memory pressure on sys1 | `oom_kill 31` recorded in cgroup events |

## 9. Not tested / could not test

- **Public URL** — none exists (no published HTTP port).
- **TLS** — no domain or certificate.
- **OIDC login** — no provider supplied.
- **Cross-user notebook isolation** — not implemented by the local backend.
- **Reboot persistence** — containers have no systemd; services would need the
  supervisor re-invoked. Not verified across a reboot (no reboot permission
  assumed on a shared host).
- **8 of 12 endpoints** — no credentials.
- **Backup/restore** — `pg_dump` works but a restore drill was not run;
  see OPERATIONS.md for the procedure.
- **NYC-taxi dataset** — source blocked on sys2 and the parquet build exceeds
  the 512 MiB cap; dataset absent from the catalogue.
