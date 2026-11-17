# CI/CD — OpenCS Labs

Two workflows in `.github/workflows/`:

| Workflow | File | Purpose |
|---|---|---|
| CI | `ci.yml` | Source validation, tests, builds, content + manifest checks |
| Deploy | `deploy.yml` | Gated rollout to the four containers, with rollback |

## Why this is a hand-written SSH deploy, not a container registry pull

The infrastructure has **no Docker and no Kubernetes** (see
`INFRASTRUCTURE_INVENTORY.md`). There is nothing to push an image to and
nothing to pull it with. The deployment unit is therefore a **git commit plus
a frontend bundle**, shipped over SSH to a venv-based runtime. The workflow
reflects that reality instead of pretending an image pipeline exists.

## CI (`ci.yml`) — already in the repository

Stages that matter for this deployment:

1. **Backend** — installs from `requirements.txt`, then a check that every
   imported distribution is actually declared (catches "works in my venv"
   breakage), then `pytest -q`. Locally on the deployed commit: **124 passed**.
2. **Content** — validates curriculum/exercise YAML and dataset manifests
   against the serving tree.
3. **Frontend** — `tsc --noEmit`, `vitest`, production `vite build`.
4. **Manifests** — YAML/JSON validity, `helm lint`, `helm template`.
5. **Notebook image / extension** — `py_compile` of the grade runner and Hub
   config; TypeScript build of the JupyterLab extension plus an assertion that
   `requestExecute` never appears (ADR-005: inserting a dataset cell must not
   execute it).

## Deploy (`deploy.yml`)

### Triggers

- `workflow_dispatch` with a `ref` input (commit SHA or branch) — the normal
  way to deploy.
- `workflow_run` after CI succeeds on `main`.

It **does not** deploy on every push. A failed CI run short-circuits at the
`preflight` job.

### Stages

| Stage | Job | What it does |
|---|---|---|
| 1. Preflight | `preflight` | Decides whether to deploy; resolves the target SHA |
| 2. Build | `build-frontend` | `npm ci` + `vite build`; **fails if `localhost:8000` leaks into the bundle**; uploads the artifact |
| 3. Approval | `deploy` (environment: `production`) | Blocked until a required reviewer approves |
| 4. Connect | `deploy` | Installs the SSH key, **pins the host key** (no `StrictHostKeyChecking=no`), verifies all four hosts |
| 5. Frontend | `deploy` | Ships the bundle and runs `opencs-deploy-frontend` (keeps the previous bundle) |
| 6. Migrations | `deploy` | `alembic upgrade head` **once**, on backend 1 only |
| 7. Rollout | `deploy` | Backends **one at a time**, each must answer `/ready` before the next |
| 8. Verify | `deploy` | 6 HTTP checks + a real login smoke test through the LB |
| 9. Report | `deploy` | Writes the deployed SHA per host into the job summary |
| 10. Rollback | `rollback` | On failure: restores each host's `previous-sha`, restarts, verifies |

### Rollback semantics

- Each backend writes `~/opencs-runtime/previous-sha` before the new checkout
  (`deploy/scripts/record_previous_sha.sh`).
- On failure the rollback job checks out that SHA and restarts.
- **Database migrations are not reversed.** Reversing a migration
  automatically is how data gets destroyed; restore from a dump instead
  (`docs/deployment/ROLLBACK.md`).

## Required GitHub configuration

The workflow reads these. **None of them are in the repository.**

### Secrets (`Settings → Secrets and variables → Actions`)

| Secret | Contents |
|---|---|
| `DEPLOY_SSH_KEY` | Private key for the deploy user (the whole PEM/OpenSSH block) |
| `DEPLOY_KNOWN_HOSTS` | Output of `ssh-keyscan -p <port> <host>` for all four endpoints |
| `DEPLOY_USER` | Service account name, e.g. `student` |
| `LB_HOST` / `LB_PORT` | Load balancer endpoint |
| `BE1_HOST` / `BE1_PORT` | Backend 1 endpoint |
| `BE2_HOST` / `BE2_PORT` | Backend 2 endpoint |
| `BE3_HOST` / `BE3_PORT` | Backend 3 endpoint |

### Variables

| Variable | Purpose |
|---|---|
| `PROD_URL` | Shown as the environment URL. **There is no public URL today** — leave empty or set the internal address. |

### Environment protection

Create an environment named **`production`** with required reviewers. Without
it, any push to `main` that passes CI would roll straight to the live stack.

```bash
gh api -X PUT repos/Jas-thinks/opencs-labs/environments/production \
  --input - <<'JSON'
{"deployment_branch_policy": {"protected_branches": true, "custom_branch_policies": false}}
JSON
```

Then add reviewers in the UI (the API for required reviewers needs a user/team
id).

### One-time host preparation

```bash
# On each backend: make the helper scripts reachable and recordable
scp -P 2306 deploy/scripts/record_previous_sha.sh student@10.1.75.53:~/opencs-runtime/
ssh -p 2306 student@10.1.75.53 'chmod +x ~/opencs-runtime/record_previous_sha.sh'

# On the LB: install the frontend deploy helper where the workflow expects it,
# and allow it via sudo without a password (it is the only privileged action).
scp -P 2305 deploy/scripts/deploy_frontend.sh student@10.1.75.53:/tmp/
ssh -p 2305 student@10.1.75.53 'echo "<pw>" | sudo -S -p "" bash -c "
  install -o root -g root -m 0755 /tmp/deploy_frontend.sh /usr/local/bin/opencs-deploy-frontend
  grep -q opencs-deploy-frontend /etc/sudoers.d/opencs-deploy || \
    echo \"$USER ALL=(root) NOPASSWD: /usr/local/bin/opencs-deploy-frontend\" > /etc/sudoers.d/opencs-deploy
  chmod 440 /etc/sudoers.d/opencs-deploy
"'
```

## Status: not yet executed

**This pipeline has not run.** It is committed and syntactically valid, but
executing it needs the secrets above, which only the repository owner can add
(they are credentials). Until then, treat the deploy workflow as
**unverified** — the configuration is real and usable, but no successful run
exists to point at.

To run it once the secrets exist:

```bash
gh workflow run deploy.yml -f ref=main
gh run watch
```

## Verification without GitHub

The same checks run by hand:

```bash
# CI equivalent
cd backend && .venv/bin/pytest -q
cd ../frontend && npx tsc --noEmit && npm run test -- --run && npm run build

# Deploy verification equivalent
ssh -p 2305 student@10.1.75.53 '~/opencs-runtime/healthcheck.sh'
```
