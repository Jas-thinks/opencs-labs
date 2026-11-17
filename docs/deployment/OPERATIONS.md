# Operations — OpenCS Labs deployment

Exact commands for the deployed stack. Run them on the named container, or
prefix with SSH. **There is no systemd**, so `systemctl` never works here —
use the commands below.

Set these once in your shell:

```bash
KEY=~/.ssh/opencs_deploy_ed25519
SSH="ssh -i $KEY -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null"

LB=$SSH\ -p\ 2305\ student@10.1.75.53      # load balancer + PostgreSQL
BE1=$SSH\ -p\ 2306\ student@10.1.75.53     # backend 1
BE2=$SSH\ -p\ 2307\ student@10.1.75.53     # backend 2
BE3=$SSH\ -p\ 2308\ student@10.1.75.53     # backend 3
```

## Service status

```bash
# Backends (PID-file supervisor)
ssh -p 2306 student@10.1.75.53 '~/opencs-runtime/svc.sh status backend'
ssh -p 2307 student@10.1.75.53 '~/opencs-runtime/svc.sh status backend'
ssh -p 2308 student@10.1.75.53 '~/opencs-runtime/svc.sh status backend'

# Load balancer
ssh -p 2305 student@10.1.75.53 'pgrep -c nginx; ss -ltn | grep ":80 "'

# PostgreSQL
ssh -p 2305 student@10.1.75.53 'pg_lsclusters; pg_isready'
```

## Start / stop / restart

```bash
# A backend
ssh -p 2306 student@10.1.75.53 '~/opencs-runtime/svc.sh restart backend'

# All three, in sequence (staggered so the LB always has healthy peers)
for P in 2306 2307 2308; do
  ssh -p $P student@10.1.75.53 '~/opencs-runtime/svc.sh restart backend'
  sleep 5
done

# nginx (needs root)
ssh -p 2305 student@10.1.75.53 'echo "<pw>" | sudo -S -p "" nginx -s reload'
# full restart (required after changing worker_processes)
ssh -p 2305 student@10.1.75.53 'echo "<pw>" | sudo -S -p "" "nginx -s stop; sleep 2; nginx"'

# PostgreSQL (no systemd -> use pg_ctlcluster)
ssh -p 2305 student@10.1.75.53 'echo "<pw>" | sudo -S -p "" pg_ctlcluster 16 main restart'
```

## Logs

```bash
# Application logs
ssh -p 2306 student@10.1.75.53 'tail -f ~/opencs-runtime/logs/backend.log'
ssh -p 2306 student@10.1.75.53 'tail -f ~/opencs-runtime/logs/backend.supervisor.log'

# JupyterLab
ssh -p 2306 student@10.1.75.53 'tail -f ~/opencs-runtime/notebooks/jupyterlab.log'

# nginx (per-request upstream + timing)
ssh -p 2305 student@10.1.75.53 'echo "<pw>" | sudo -S -p "" tail -f /srv/opencs/logs/access.log'
ssh -p 2305 student@10.1.75.53 'echo "<pw>" | sudo -S -p "" tail -f /srv/opencs/logs/error.log'

# PostgreSQL
ssh -p 2305 student@10.1.75.53 'echo "<pw>" | sudo -S -p "" tail -f /var/log/postgresql/postgresql-16-main.log'
```

## Health checks

```bash
# One-shot, from the LB node (all 10 checks)
ssh -p 2305 student@10.1.75.53 '~/opencs-runtime/healthcheck.sh'

# Individual
ssh -p 2305 student@10.1.75.53 'curl -sS http://127.0.0.1/healthz'
ssh -p 2305 student@10.1.75.53 'curl -sS http://127.0.0.1/ready'
ssh -p 2306 student@10.1.75.53 'curl -sS http://127.0.0.1:8000/health'
```

## Which backend is serving traffic

```bash
ssh -p 2305 student@10.1.75.53 \
  'echo "<pw>" | sudo -S -p "" grep -o "upstream=[0-9.]*:[0-9]*" /srv/opencs/logs/access.log \
   | sort | uniq -c'
```

## Database

```bash
# Interactive psql
ssh -p 2305 student@10.1.75.53 \
  'echo "<pw>" | sudo -S -p "" runuser -u postgres -- psql -d opencs'

# Table sizes
ssh -p 2305 student@10.1.75.53 'echo "<pw>" | sudo -S -p "" runuser -u postgres -- \
  psql -d opencs -c "SELECT relname, n_live_tup FROM pg_stat_user_tables ORDER BY n_live_tup DESC LIMIT 15"'

# Connections
ssh -p 2305 student@10.1.75.53 'echo "<pw>" | sudo -S -p "" runuser -u postgres -- \
  psql -c "SELECT count(*), state FROM pg_stat_activity GROUP BY state"'
```

## Migrations

Run **once**, not on all three backends:

```bash
ssh -p 2306 student@10.1.75.53 '
  cd ~/opencs-labs/backend
  set -a; . ~/opencs-runtime/.env; set +a
  ~/opencs-runtime/venv/bin/alembic upgrade head
  ~/opencs-runtime/venv/bin/alembic current'
```

## Backup

```bash
# Logical dump (safe against a live database)
ssh -p 2305 student@10.1.75.53 \
  'echo "<pw>" | sudo -S -p "" runuser -u postgres -- \
   pg_dump -Fc -d opencs' > opencs-$(date +%F).dump

# Verify it is readable without restoring
pg_restore --list opencs-$(date +%F).dump | head
```

Store dumps **off** the host. The docker bridge filesystem is not a backup
target.

## Restore

```bash
# Stop writes first so the restore is consistent.
for P in 2306 2307 2308; do ssh -p $P student@10.1.75.53 '~/opencs-runtime/svc.sh stop backend'; done

scp -P 2305 opencs-YYYY-MM-DD.dump student@10.1.75.53:/tmp/restore.dump
ssh -p 2305 student@10.1.75.53 'echo "<pw>" | sudo -S -p "" runuser -u postgres -- \
  pg_restore -d opencs --clean --if-exists /tmp/restore.dump'

for P in 2306 2307 2308; do ssh -p $P student@10.1.75.53 '~/opencs-runtime/svc.sh start backend'; done
ssh -p 2305 student@10.1.75.53 '~/opencs-runtime/healthcheck.sh'
```

> A restore drill was **not** executed during this deployment. The procedure
> is standard `pg_dump`/`pg_restore`, but treat it as untested until you run it.

## Common problems

| Symptom | Cause | Fix |
|---|---|---|
| `systemctl` says "not booted with systemd" | No init | use `svc.sh` / `pg_ctlcluster` / `nginx` |
| Backend 503 quickly after start | Postgres unreachable, or OOM | check `backend.log`; check `memory.events` |
| All requests 200 but slow | one backend doing the work | check `upstream=` distribution in access log |
| sshd "banner exchange" timeout | cgroup memory exhaustion on that container | reduce workers; see the inventory note on sys1's pre-existing app |
| Notebook create returns 503 `UPSTREAM_UNAVAILABLE` | JupyterLab missing or failed to start | check `notebooks/jupyterlab.log`; reinstall `jupyterlab` in the venv |
| `nginx: duplicate upstream` | upstream file matched `conf.d/*.conf` | keep it named `*.inc` |

## Reloading configuration

```bash
# Backend env change
ssh -p 2306 student@10.1.75.53 '~/opencs-runtime/svc.sh restart backend'

# nginx config change
scp -P 2305 deploy/load-balancer/nginx.conf student@10.1.75.53:/tmp/
ssh -p 2305 student@10.1.75.53 'echo "<pw>" | sudo -S -p "" bash -c "cp /tmp/nginx.conf /etc/nginx/conf.d/opencs.conf && nginx -t && nginx -s reload"'
```
