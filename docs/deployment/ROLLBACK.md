# Rollback — OpenCS Labs deployment

The deployment is a git checkout plus a venv plus a rendered `.env` on each
backend container. Rollback is therefore: check out the previous commit, keep
the venv, restart the service. No image builds, no container rebuilds.

**Never roll back the database automatically.** Migrations are forward-only in
practice; restore from a dump if the schema genuinely must go backwards.

## 1. Know what is deployed

```bash
for P in 2306 2307 2308; do
  printf '%s: ' $P
  ssh -p $P student@10.1.75.53 'cd ~/opencs-labs && git rev-parse --short HEAD'
done
ssh -p 2306 student@10.1.75.53 'cd ~/opencs-labs/backend && set -a && . ~/opencs-runtime/.env && set +a && ~/opencs-runtime/venv/bin/alembic current'
```

Record the commit and the Alembic revision before changing anything.

## 2. Roll back the application (no schema change)

```bash
PREV=<previous-commit-sha>

for P in 2306 2307 2308; do
  ssh -p $P student@10.1.75.53 "
    cd ~/opencs-labs
    git fetch origin
    git checkout -q $PREV
    ~/opencs-runtime/svc.sh restart backend
    sleep 4
    curl -sS -m 8 http://127.0.0.1:8000/health || echo FAIL
  "
done

ssh -p 2305 student@10.1.75.53 '~/opencs-runtime/healthcheck.sh'
```

Roll one backend at a time (the loop above does) so the LB always has two
healthy peers.

## 3. Roll back with a schema change

Only if the release included a migration that must be reverted:

1. **Take a dump first** (see OPERATIONS.md → Backup).
2. Stop all backends.
3. `alembic downgrade -1` **once**, on one node only.
4. Check out the previous commit on all three, restart, verify.

```bash
ssh -p 2306 student@10.1.75.53 '
  cd ~/opencs-labs/backend
  set -a; . ~/opencs-runtime/.env; set +a
  ~/opencs-runtime/venv/bin/alembic downgrade -1
  ~/opencs-runtime/venv/bin/alembic current'
```

If the downgrade is not supported, restoring the dump is the only safe path.
Do not attempt to hand-edit the schema.

## 4. Roll back configuration only

`.env` changes are independent of code:

```bash
# The previous env is recoverable from the runtime dir if you kept a copy.
ssh -p 2306 student@10.1.75.53 '
  cp ~/opencs-runtime/.env ~/opencs-runtime/.env.new
  # edit ~/opencs-runtime/.env
  ~/opencs-runtime/svc.sh restart backend'
```

Keep `~/.opencs-runtime/.env.bak.<timestamp>` before edits — this deployment
does not create them automatically.

## 5. Roll back the load balancer

The previous nginx config is backed up on the host as
`/etc/nginx/nginx.conf.bak.<epoch>` and the site config is version-controlled
in `deploy/load-balancer/`.

```bash
ssh -p 2305 student@10.1.75.53 'echo "<pw>" | sudo -S -p "" bash -c "
  ls -t /etc/nginx/nginx.conf.bak.* | head -1
  cp \$(ls -t /etc/nginx/nginx.conf.bak.* | head -1) /etc/nginx/nginx.conf
  nginx -t && nginx -s stop; sleep 2; nginx"'
```

Test the config (`nginx -t`) before restarting. A broken LB takes the whole
application down even though the backends are healthy.

## 6. Roll back to a single backend

If a release is unstable on some nodes, the fastest safe state is to point the
LB at the known-good backends:

```bash
# edit deploy/load-balancer/opencs-upstreams.inc, comment out the bad server
ssh -p 2305 student@10.1.75.53 'echo "<pw>" | sudo -S -p "" bash -c "
  cp /tmp/opencs-upstreams.inc /etc/nginx/conf.d/opencs-upstreams.inc
  nginx -t && nginx -s reload"'
```

## 7. Automated rollback in CI/CD

`.github/workflows/deploy.yml` performs these same steps automatically when a
post-deploy health check fails: it checks out the previous SHA on each backend,
restarts, re-verifies, and reports the outcome. See `docs/deployment/CICD.md`.
