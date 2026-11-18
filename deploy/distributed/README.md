# 12-node distributed deployment

This runbook deploys OpenCS Labs on the 12 lab containers. Every container is capped at 1 CPU and 512 MiB. They sit on two physical hosts.

The design goal is the lowest possible request latency. To get it, every hop of an API request stays on Host A's docker bridge, where a hop costs about 0.05 ms. Notebook execution runs on Host B.

```
browser ──► edge  10.1.75.53:5305  (stu87_sys1: nginx, SPA, rate limits)
             ├─/api/ ─► api1..api4  (stu87_sys2-4, stu74_sys1: uvicorn :8000, 1 worker each)
             │             └─► pg1 primary (stu74_sys2) ──async stream──► pg2 hot standby (stu74_sys3)
             └─/nb/<i>/ ─► Hub shard i  10.1.75.79:522<1+i>  (stu36_sys1-4)
ctl (stu74_sys4): background worker, watchdog, backups, standby edge on 10.1.75.53:5256
```

## Key decisions

- **Same origin for notebooks.** Each Hub shard is served by the edge under `/nb/<i>/`. That means:
  - the session cookie reaches `/hub/login`, giving single sign-on;
  - the JupyterLab extension's calls to `/api/v1` are same-origin;
  - no token ever appears in a URL.

  Without this, the browser would treat `.79` as a different site and withhold the `SameSite=Lax` cookie.
- **User → shard mapping.** Each user is pinned to shard `sha256(hub_username) % 4` (`OPENCE_JUPYTERHUB_SHARDS`). Every API node computes the same answer with no shared state. **Changing the number or order of shards moves users to an empty home directory.**
- **Exactly one background worker.** Only ctl sets `OPENCE_BACKGROUND_WORKERS_ENABLED=true`, so the four API CPUs serve only requests.
- **Edge rate limiting.** Limits live at the edge (`limit_req`), giving one consistent counter. The in-app limiter is per process, so it remains only as a backstop.
- **Async replication with a multi-host DSN.** The DSN lists both nodes with `target_session_attrs=read-write`. After a promotion, the APIs reconnect by themselves.

## Layout on every node: `~/opencs`

| Path | Contents |
|---|---|
| `current → releases/<sha>` | Code. `previous` holds the last release, used by rollback. |
| `venv/`, `nb-venv/`, `npm/` | Backend runtime; notebook/Hub runtime with the dataset extension; configurable-http-proxy. |
| `env/` | Rendered config and secrets (mode 0600). Never edit these on the node. |
| `run/`, `logs/` | Supervisor PID files and logs: `logs/<service>.log` and `logs/edge.access.log`. |
| `datasets/serving` | The read-only dataset tree. It sits at the same absolute path on API, ctl and Hub nodes. |
| `data/` | Hub database and student notebook homes (Hub nodes only). |

Run `bash ~/opencs/bin/opencs.sh {start|stop|restart|status} <api|worker|hub|edge|watchdog>` on a node to manage one of its services.

## First deployment

Prerequisites on the operator machine:
- `~/.ssh/opencs_deploy_ed25519` is authorised on all 12 nodes;
- `secrets/sudo.env` contains lines of the form `alias=password`;
- Node 18 or newer, for the frontend build;
- Node 20.19 or newer plus `jupyterlab==4.6.6` for the extension, set via `NODE22=/path/bin` and `JLAB_VENV=/path/venv`.

```bash
D=deploy/distributed/deploy.sh
$D render && $D preflight
$D cleanup          # dumps old opencs DBs to secrets/pre-deploy-dumps, stops old OpenCS processes
$D release          # a release is an exact commit: commit first
$D runtimes         # builds venvs once per host and copies them to peers (PyPI is blocked on some nodes)
$D postgres         # primary + streaming standby (FRESH_DB=0 keeps an existing database)
$D migrate          # alembic upgrade head + seed, run once from ctl
$D start all        # Hubs and APIs first, then ctl, then the edge
$D verify
```

## Day-2 operations

| Task | Command |
|---|---|
| Cluster status | `$D status`. ctl also writes `~/opencs/run/cluster-status` every 15 s. |
| Code update (zero downtime) | Commit, then `$D rollout`. It restarts APIs one at a time and reloads the edge. |
| Roll back | `$D rollback` |
| Restart one node's services | `$D start api3` / `$D stop nb2` |

### Watchdog (ctl)

Every 15 s the watchdog health-checks all nodes.

- **Failing service:** after 3 consecutive failures it restarts the service over SSH. This also recovers a node whose container restarted, since nothing starts by itself there (PID 1 is sshd).
- **Postgres:** it will start PostgreSQL but never promote it.
- **Logs:** it rotates logs hourly.
- **Backups:** it takes a daily `pg_dump` from the standby. Seven copies are kept on ctl and seven off-host on nb3.

### PostgreSQL failover (manual by design: no split-brain)

1. Confirm pg1 is really down: `ssh pg1 pg_isready`, and check the watchdog log.
2. Promote the standby: `ssh pg2 'sudo -u postgres pg_ctlcluster 16 main promote'`.
3. The APIs reconnect to pg2 on their next pooled connection. No config change is needed.
4. Rebuild pg1 as the new standby. The quickest way is to swap the `pg-primary` and `pg-standby` roles in `inventory.json` and run `$D postgres` with `FRESH_DB=0`.

Expected RTO is about a minute. RPO is the replication lag, normally under a second (`pg_stat_replication.replay_lag`).

### Edge failover

If stu87_sys1 dies, users switch to `http://10.1.75.53:5256`. That standby edge runs on ctl with identical config. There is no VIP or DNS on this network, so this switch stays manual.

## Capacity: read this before inviting a class

| Tier | Capacity |
|---|---|
| API | 4 × 1 CPU. Measured figures are recorded at the bottom of this file. |
| Notebooks | 4 shards × at most 2 running servers (`OPENCE_ACTIVE_SERVER_LIMIT`), so **8 concurrent notebook users**. Above that the API reports "capacity exhausted" instead of letting a kernel OOM a node. Idle servers are culled after 15 minutes. |

The biggest lever for notebook capacity is more cgroup memory on the stu36 containers. Sharding already scales out, so more memory needs no design change.

## Known limitations

- **No TLS and no domain**, so cookies cannot be `Secure`. Use this only on the campus network.
- **`OPENCE_ENV=development` and demo password auth** remain on, because production mode refuses both. Replace them with OIDC before any wider exposure.
- **No OS isolation between users on a shard.** All users share one account, with one directory each.
- **Host A is a single physical machine.** The off-host backup on Host B is the only protection against losing it.
- **The NYC-taxi dataset is not built.** Its CloudFront source resets connections from this network.
