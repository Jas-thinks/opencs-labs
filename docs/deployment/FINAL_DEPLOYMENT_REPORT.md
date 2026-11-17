# Final deployment report — OpenCS Labs

**Deployed commit:** `65f3e11` (also the commit this report is part of)
**Date:** 2026-11-17
**Deployment type:** native (no Docker), 4 containers, systemd-less

---

## 1. Executive summary

The application is **running and verified end to end** on the four accessible
containers: a native Nginx load balancer in front of three uvicorn backends,
backed by a native PostgreSQL 16 cluster. Login, curriculum, datasets,
practice, notebooks, autosave, grading, analytics and real Python kernel
execution were all exercised with measured results (370 load-test requests,
0 errors; 124 backend tests passing).

Three deliverables **cannot** be met on this infrastructure, and this report
says so plainly rather than claiming them:

1. **No public URL exists.** The host publishes only SSH ports.
2. **Notebook execution is not per-user isolated.** No Docker, no Kubernetes,
   no systemd → JupyterHub cannot spawn pods.
3. **8 of the 12 assigned endpoints were never reachable.** No working
   credentials were supplied for `.79:2221-2224` or `.53:2253-2256`.

---

## 2. What the infrastructure actually is

The brief described 12 machines in three groups of four. Measurement found
**four containers on one host**, each reachable on four SSH ports:

```
machine-id = b051ddfadc974a06bda6f561198b834e   identical on 2305-2308
boot_id    = 64227714-f41c-4c1f-916f-da4d7b397969 identical on 2305-2308
```

A shared `machine-id` and `boot_id` is impossible across separate machines.
`PID 1` is `sshd` on all four (no systemd), the root filesystem is overlayfs,
and each container is capped at **1 CPU / 512 MiB** by cgroup — despite
`nproc` reporting the host's 120 CPUs and `free` showing 125 GiB.

### The 12 endpoints

| # | Endpoint | Status |
|---|---|---|
| 1 | `.53:2305` | **Deployed** — LB + PostgreSQL |
| 2 | `.53:2306` | **Deployed** — backend 1 |
| 3 | `.53:2307` | **Deployed** — backend 2 |
| 4 | `.53:2308` | **Deployed** — backend 3 |
| 5-8 | `.79:2221-2224` | **Not deployed** — auth rejected |
| 9-12 | `.53:2253-2256` | **Not deployed** — auth rejected |

---

## 3. Machine-to-service deployment

| Endpoint | Host | Services | Port | Verified |
|---|---|---|---|---|
| `.53:2305` | `stu87_sys1` | nginx 1.24, PostgreSQL 16 | 80, 5432 | yes |
| `.53:2306` | `stu87_sys2` | uvicorn, JupyterLab | 8000, 8888 | yes |
| `.53:2307` | `stu87_sys3` | uvicorn, JupyterLab | 8000, 8888 | yes |
| `.53:2308` | `stu87_sys4` | uvicorn, JupyterLab | 8000, 8888 | yes |

All three backends run **the same commit** (`65f3e11`), verified by
`git rev-parse --short HEAD` on each.

---

## 4. Architecture

```
                    (no published HTTP port — internal only)
                                 │
                    ┌────────────▼───────────────┐
                    │ stu87_sys1 172.17.0.22     │
                    │ nginx :80  (LB + SPA)      │
                    │ PostgreSQL 16 :5432        │
                    └──┬─────────┬─────────┬─────┘
          round-robin  │         │         │  max_fails=3 fail_timeout=15s
            ┌──────────▼──┐ ┌────▼────────┐ ┌▼─────────────┐
            │ sys2 .61    │ │ sys3 .57    │ │ sys4 .39     │
            │ uvicorn ×1  │ │ uvicorn ×1  │ │ uvicorn ×1   │
            │ JupyterLab  │ │ JupyterLab  │ │ JupyterLab   │
            └─────────────┘ └─────────────┘ └──────────────┘
```

Full detail: [`DEPLOYMENT_ARCHITECTURE.md`](DEPLOYMENT_ARCHITECTURE.md).

---

## 5. Access and URLs

| Item | Value |
|---|---|
| Frontend URL | **none publicly reachable** |
| Internal LB | `http://172.17.0.22/` (docker network only) |
| API health | `http://172.17.0.22/health` (internal) |
| Monitoring | `/metrics` (Prometheus text) on each backend, internal only |
| Outside campus network | **not reachable** — no published port |

There is no domain and no certificate, so no TLS and no `Secure` cookie. This
is a hard limitation of the environment, not a configuration choice.

---

## 6. Verification results (measured)

| Area | Result |
|---|---|
| Health checks | **10/10 PASS** (`deploy/scripts/healthcheck.sh`) |
| Backend tests | **124 passed** |
| Load balancing | **3/3/3** even round-robin |
| Failover | **26/26 requests 200** with sys4 fully stopped |
| Migrations | `f443308c6e53 → 9a1f2b3c4d5e (head)` |
| Seed | 5 users, 1 course, 12 modules, 21 lessons, 22 exercises, 9 datasets |
| Login + session | 200 / 200, unauthenticated = **401** |
| RBAC | student → teacher analytics = **403** |
| Dataset snippet | `auto_execute: false` confirmed |
| Notebook create | **201** |
| Autosave + versions | **200**, version 1 with sha256 |
| **Kernel execution** | **PASS** — pandas read Iris: `150 rows, mean 5.84` |
| Load test | 370 requests, **0 errors**, 28.3 req/s @ 25 concurrent, p95 396 ms |

Full detail: [`DEPLOYMENT_TEST_REPORT.md`](DEPLOYMENT_TEST_REPORT.md).

---

## 7. Database

- **Topology:** single PostgreSQL 16 primary on `stu87_sys1`.
- **Not** a cluster. **No** replication, **no** failover, **no** quorum.
- Least-privilege role `opencs`, scram-sha-256, generated 43-char password.
- `pg_hba.conf` restricted to `172.17.0.0/16`.
- Managed with `pg_ctlcluster` (systemd absent).
- Backup: `pg_dump -Fc` documented and working; **restore drill not executed**.

The brief warned against "four independent databases that silently diverge".
Only one DB host was credentialled, so one primary is the honest outcome. It
is a single point of failure and is labelled as such.

---

## 8. Security summary

In place: scram-sha-256 DB auth, least-privilege DB role, 0600 env files,
dedicated SSH key, strong JWT secret, rate limiting, security headers,
`server_tokens off`, no Docker socket anywhere, request size limits, generic
error page, 401/403 enforcement verified.

Not in place: **TLS**, **OIDC/SSO** (dev password auth is live), per-user
notebook isolation, NetworkPolicies, seccomp/AppArmor, WAF.

The critical caveat: **development authentication is enabled on a deployed
system**, because the application refuses to boot in `production` mode without
JupyterHub + KubeSpawner + OIDC + TLS. It is only tolerable because nothing
outside the docker bridge can reach the app. It must be replaced before any
exposure.

Full detail: [`NETWORK_AND_SECURITY.md`](NETWORK_AND_SECURITY.md).

---

## 9. CI/CD

| Item | Status |
|---|---|
| `.github/workflows/ci.yml` | Pre-existing, unchanged, comprehensive |
| `.github/workflows/deploy.yml` | **New** — gated, staged, with rollback |
| Workflow YAML valid | yes (parsed + both workflows load) |
| **Pipeline executed** | **NO** — needs repository secrets only the owner can add |

The deploy workflow has 10 stages: preflight → frontend build (rejects
`localhost` leakage) → `production` environment approval → SSH with pinned
host keys → frontend ship → migrations once → one-at-a-time rollout →
6-check verification + login smoke test → SHA report → automatic rollback on
failure.

Required secrets are listed in [`CICD.md`](CICD.md). **No successful run
exists**, so CI/CD is delivered as working configuration, not as a proven
pipeline.

---

## 10. Known limitations and unresolved issues

1. **8 endpoints unusable** — no credentials. Four execution workers and four
   DB nodes were never touched.
2. **No public URL** — no published HTTP port, no domain.
3. **No per-user notebook isolation** — one JupyterLab per node, shared OS
   user. Cross-user protection is at the API layer only.
4. **Dev authentication in a deployed system** — shared demo password.
5. **Single database, no HA** — declared, not faked.
6. **`sys1` is memory-starved** — 512 MiB shared with a **pre-existing
   unrelated application** (`pond_deploy`, 4 uvicorn workers, ~376 MiB).
   Cgroup recorded `oom_kill 31`. sshd became unresponsive during rollout;
   services kept serving. Not touched, per instruction.
7. **NYC-taxi dataset absent** — CloudFront blocked on sys2 and the parquet
   build exceeds 512 MiB.
8. **No reboot survival** — no systemd; the supervisor would need re-invocation
   after a container restart. Not tested (no reboot permission assumed).
9. **Load test stops at 25 concurrent** — the 400-user target was **not**
   attempted; it would have measured the OOM killer and risked a shared host.

---

## 11. Exact commands to manage the application

```bash
KEY=~/.ssh/opencs_deploy_ed25519

# status
ssh -i $KEY -p 2306 student@10.1.75.53 '~/opencs-runtime/svc.sh status backend'
ssh -i $KEY -p 2305 student@10.1.75.53 'pgrep -c nginx; pg_isready'

# restart one backend
ssh -i $KEY -p 2306 student@10.1.75.53 '~/opencs-runtime/svc.sh restart backend'

# all health checks
ssh -i $KEY -p 2305 student@10.1.75.53 '~/opencs-runtime/healthcheck.sh'

# logs
ssh -i $KEY -p 2306 student@10.1.75.53 'tail -f ~/opencs-runtime/logs/backend.log'

# database
ssh -i $KEY -p 2305 student@10.1.75.53 \
  'echo "<pw>" | sudo -S -p "" runuser -u postgres -- psql -d opencs'

# migrations (once)
ssh -i $KEY -p 2306 student@10.1.75.53 \
  'cd ~/opencs-labs/backend && set -a && . ~/opencs-runtime/.env && set +a && ~/opencs-runtime/venv/bin/alembic upgrade head'
```

More: [`OPERATIONS.md`](OPERATIONS.md), [`ROLLBACK.md`](ROLLBACK.md).

---

## 12. Deviation record (required by HLD §25.18)

| HLD / brief requirement | What was done | Why |
|---|---|---|
| "Dockerized services where suitable" | **No Docker** | `docs/ARCHITECTURE.md` STRICT RULE; no Docker on targets either way |
| KubeSpawner + Kubernetes, 1 pod/user | `OPENCE_NOTEBOOK_BACKEND=local` | No Docker/K8s/systemd |
| 4 DB nodes, replication | 1 native primary | Only 1 DB host credentialled; warn against divergence |
| 4 execution workers | not deployed | Cannot authenticate |
| OIDC / institutional SSO | `OPENCE_AUTH_MODE=dev` | No provider supplied |
| TLS + secure cookies | HTTP only, `cookie_secure=false` | No domain/cert/port |
| Production mode | `OPENCE_ENV=development` | App hard-refuses production without Hub+OIDC+TLS |
| systemd services | `svc.sh` PID supervisor | No systemd |
| 400 concurrent users | measured to 25 | 512 MiB/container; shared host |

---

## 13. Definition-of-done accounting

| Criterion | Met? |
|---|---|
| All 12 systems independently identified | Attempted — 4 identified, 8 credential-blocked |
| Each machine running its assigned role | 4/4 accessible nodes yes |
| LB serves the application | **Yes** (internally) |
| All three backends healthy | **Yes** |
| Four execution systems integrated | **No** — no credentials |
| DB topology works and preserves data | Yes, single node; persistence verified, restore untested |
| Frontend → backend → DB works | **Yes**, verified |
| Notebook/execution workflows work end to end | **Partly** — real kernels run; no per-user isolation |
| Services recover after failure | **Yes**, failover verified |
| Logs and health checks available | **Yes** |
| Actual application URL tested | **No public URL exists** |
| CI/CD implemented | Written and valid; **not executed** |
| Report contains measured evidence | Yes |

**Honest verdict:** the core application is deployed and working on the
infrastructure that was actually available. The notebook-isolation, public-URL
and full-inventory goals were not achievable with the access and runtimes
provided, and were not faked.
