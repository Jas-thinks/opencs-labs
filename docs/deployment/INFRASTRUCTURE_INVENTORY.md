# Infrastructure inventory — OpenCS Labs deployment

**Status:** measured, not assumed. Every value below was read from the target
during Phase 0 discovery on 2026-11-17.
**Scope:** the 12 assigned endpoints.

## 1. Headline finding: the allocation is not 12 machines

The briefing describes 12 machines in three groups of four. Measurement
contradicts this in ways that change the deployment design:

| Assumption in briefing | Measured reality |
|---|---|
| 12 independent machines | **4 containers** (`stu87_sys1..4`), each exposed on 4 SSH ports |
| One SSH port per machine | Ports are **alternate access paths to the same 4 containers** |
| 120 CPU / 125 GiB per machine | Host has those resources; **each container is capped at 1 CPU / 512 MiB** |
| systemd available | **No systemd.** `PID 1 = sshd` on every target |
| Docker available | **No Docker, no Docker socket, no Kubernetes** |
| Public HTTP entry point | **No HTTP port is published**; only SSH is mapped |

### Evidence: identical machine identity

All four endpoints on `10.1.75.53` (`2305`-`2308`) report:

```
machine-id = b051ddfadc974a06bda6f561198b834e   (identical)
boot_id    = 64227714-f41c-4c1f-916f-da4d7b397969 (identical)
kernel     = 6.8.0-136-generic                    (identical)
```

A shared `machine-id` and `boot_id` cannot occur on separate machines: they
share one kernel and one boot. Filesystems are *not* shared — a marker written
to `/home/student` on sys2 was absent on sys3/sys4 — so these are four
containers (overlayfs roots, `PID1=sshd`) on one host.

### Evidence: cgroup limits, not host resources

```
/sys/fs/cgroup/memory.max = 536870912   (512 MiB — on all four containers)
/sys/fs/cgroup/cpu.max    = 100000 100000  (1 CPU)
```

`nproc` and `free` report the **host's** 120 CPUs and 125 GiB, which is why a
naive reading suggests a powerful machine. The scheduler only ever grants
1 CPU / 512 MiB per container. This single fact drove several design
decisions (single uvicorn worker, 2 nginx workers, careful request sizes).

## 2. Endpoint inventory

| # | Endpoint | Host key | Auth result | Container | Internal IP |
|---|---|---|---|---|---|
| 1 | `.53:2305` | rsa…odLfU= | key + password + sudo | `stu87_sys1` | `172.17.0.22` |
| 2 | `.53:2306` | same as 2305 | password + sudo | `stu87_sys2` | `172.17.0.61` |
| 3 | `.53:2307` | same as 2305 | password + sudo | `stu87_sys3` | `172.17.0.57` |
| 4 | `.53:2308` | same as 2305 | password + sudo | `stu87_sys4` | `172.17.0.39` |
| 5 | `.79:2221` | rsa… (distinct) | **rejected all credentials** | unknown | unreachable |
| 6 | `.79:2222` | rsa… (distinct) | **rejected all credentials** | unknown | unreachable |
| 7 | `.79:2223` | rsa… (distinct) | **rejected all credentials** | unknown | unreachable |
| 8 | `.79:2224` | rsa… (distinct) | **rejected all credentials** | unknown | unreachable |
| 9 | `.53:2253` | ecdsa (distinct) | **rejected all credentials** | unknown | unreachable |
| 10 | `.53:2254` | ecdsa (distinct) | **rejected all credentials** | unknown | unreachable |
| 11 | `.53:2255` | ecdsa (distinct) | **rejected all credentials** | unknown | unreachable |
| 12 | `.53:2256` | ecdsa (distinct) | **rejected all credentials** | unknown | unreachable |

Ports 5-12 are **TCP-reachable** but reject authentication. Host keys differ
from the `2305-2308` group, so they are genuinely different containers — but
without credentials nothing could be inventoried or deployed there.

Attempted credentials on each blocked endpoint: the default password, the
sys1-sys4 group password, and three common application defaults. Attempted
usernames on `.79`: `student`, `12340080`, `adarsh`. All rejected.
`Systems.md` documents credentials for the `2305-2308` group only.

> Credential values are deliberately not reproduced here. `Systems.md` in the
> working tree does contain them in plaintext and is excluded from version
> control; rotate those passwords and move that file out of the working tree.

## 3. Measured per-container baseline

| Property | Value |
|---|---|
| OS | Ubuntu 24.04.4 LTS |
| Kernel | 6.8.0-136-generic, x86_64 |
| CPU (cgroup) | 1 CPU |
| Memory (cgroup) | 512 MiB |
| Disk | 247 GB total, ~48-52 GB free (81% used) |
| Python | 3.12.3 (3.14.6 on sys1 via conda) |
| Node.js | not installed |
| Git | 2.43.0 |
| Docker | **absent** |
| systemd | **absent** (`systemctl` reports "not booted with systemd") |
| Process supervisor | none (no supervisor/runit/s6/tmux) |
| Outbound network | GitHub ✓, PyPI ✓ (except one node), Ubuntu archive ✓, CloudFront ✗ on sys2 |

### Notable pre-existing state

- **`stu87_sys1` runs another application**: `/home/student/pond_deploy/condaenv`
  uvicorn on `0.0.0.0:8000`, started 2026-10-28, 4 workers, ~376 MiB RSS.
  **Not touched.** It is why OpenCS bind decisions and memory planning here
  are conservative, and it competes for the same 512 MiB cgroup.
- Each container has its own git clone at the assigned path
  (`/home/student/opencs-labs`), all at `bdc606e` before deployment.
- sys2 cannot reach `d37ci6vzurychx.cloudfront.net` (connection reset), which
  is why the NYC-taxi dataset could not be built *on that node*.

## 4. Consequences for the deployment

1. **No systemd** → services run under `deploy/scripts/svc.sh`, a PID-file
   supervisor with restart-on-exit and backoff.
2. **512 MiB per container** → one uvicorn worker per backend; 2 nginx
   workers (the packaged `worker_processes auto` would fork **120** workers
   and OOM the container — this caused real sshd starvation during rollout).
3. **No Docker/Kubernetes** → JupyterHub + DockerSpawner/KubeSpawner is
   impossible; the application runs `OPENCE_NOTEBOOK_BACKEND=local`
   (host-process JupyterLab).
4. **8 endpoints unusable** → only the 4 accessible containers carry the
   deployment. "Four database nodes" became one native PostgreSQL cluster.
5. **No published HTTP port** → no public URL; verification runs inside the
   docker network from `172.17.0.22`.
