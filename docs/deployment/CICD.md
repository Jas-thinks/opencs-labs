# CI/CD

This document explains how code gets from a commit to the 12-node cluster. The reasoning is in [ADR-011](../ADR/011-observability-and-ci-cd.md).

```
pull request / push ──► CI  (GitHub-hosted runners)
                         backend tests · PostgreSQL migrations · content + datasets
                         frontend typecheck/tests/build · extension build
                         Helm/manifests · deploy tooling (shellcheck, render, nginx -t)
                         └─ main only ──► package  →  artifact "release"
                                                         │
push to main, CI green ──► Deploy  (self-hosted runner "opencs-edge" on stu87_sys1)
                         waits for approval (environment "production")
                         download the artifact for that exact commit
                         ship → schema migrations → rolling restart → verify
                         any failure ⇒ every node back to the previous release
```

## Why the work is split between GitHub and campus

GitHub's cloud runners cannot reach `10.1.75.x`. So:

- **GitHub does the building and testing.** The `package` job produces one artifact: the code tarball, the built frontend (precompressed), the dataset tree, the JupyterLab extension and the `SHA`.
- **A runner inside the network does the deploying**, using that exact artifact.

The runner sits on the edge node because that node uses about 10 MiB of its 512 MiB, and it can reach every other node over the bridge or the published SSH ports. Cluster credentials stay on that host (`~/.opencs-deploy/`, mode 0600), with a dedicated SSH key (`~/.ssh/opencs_runner_ed25519`). **No secret is stored in GitHub.**

## CI (`.github/workflows/ci.yml`)

| Job | What it proves |
|---|---|
| backend | all imports are declared in `requirements.txt`; the pytest suite (SQLite) passes |
| migrations-postgres | `alembic upgrade head`, then down 2 and back up, run on a real **PostgreSQL 16**; every ORM column exists in the migrated schema |
| content | curriculum validates; the dataset tree builds and matches its manifests |
| frontend | `tsc`, vitest and `vite build` all pass |
| jupyterlab-extension | the extension compiles, and the "never execute a dataset cell" contract holds |
| manifests / notebook-image | the Helm chart, Kubernetes YAML, Hub config and grade runner are valid |
| deploy-tooling | `shellcheck`; Python compiles; every node's config renders (with throwaway secrets); the dashboards, alert rules and scrape config are valid; **nginx accepts the rendered edge config** |
| package | (main only, after all of the above) builds and uploads the `release` artifact, kept 30 days |

## Deploy (`.github/workflows/deploy.yml`)

**Triggers.** A Deploy runs when a CI run for a *push* to `main` succeeds. It can also be started manually with **Run workflow**, optionally with a `ci_run_id` to redeploy an older green build.

**Gate.** The `production` environment. Its required reviewers approve each deploy.

**Steps,** all from `deploy/distributed/deploy.sh cd`:

1. **Record the running release** (for example `aa1ca1c…`).
2. **Ship** the artifact to all 12 nodes. Code and frontend live together under `releases/<sha>/`, and `current` is flipped on each node.
3. **Run schema migrations** with `alembic upgrade head` from the control node. The seed is never run. Migrations are additive, so the previous code also runs on the new schema.
4. **Rolling restart.** One API at a time, each health-checked and warmed, while the edge retries on the others. Then the worker restarts, the hubs (left running if healthy), and the edge reloads gracefully.
5. **Verify.** SPA, `/health`, gzip, all four notebook shards, load-balancer spread, login and an authenticated call.

**If any step fails, every node is pointed back at the recorded release, code and frontend together, and restarted the same way.** The workflow then fails. Migrations are not reversed, by design.

## One-time setup

### 1. The runner on the edge node (already installed)

`deploy.sh runner-setup` downloaded the runner, verified its SHA-256 against the release notes, installed it in `~/actions-runner`, and authorised the runner's SSH key on every node. It also copied the cluster secrets to `~/.opencs-deploy/`. **What's left is registration:**

1. GitHub → repository → **Settings → Actions → Runners → New self-hosted runner**, then copy the token. Tokens expire after 1 hour.
2. On the operator machine:
   ```bash
   ssh -F deploy/distributed/build/ssh_config edge '~/actions-runner/register-opencs.sh <TOKEN>'
   ```
   This registers the runner as `opencs-edge` (label `opencs-edge`) and starts it under the node supervisor. It shows **Idle** in the Runners list.

### 2. The `production` environment (required, or deploys are not gated)

GitHub → **Settings → Environments → New environment** named `production`:

- **Required reviewers:** add yourself and/or your teammates.
- **Deployment branches:** *Selected branches* → `main`.

If the environment doesn't exist, GitHub creates it on the first run **without protection**, and deploys would run unapproved. Create it before the first merge.

### 3. Branch protection (recommended)

Settings → Branches → `main`: require a pull request and require the CI checks to pass.

## Day to day

| Task | How |
|---|---|
| Ship a change | Merge a PR into `main`, wait for CI, then **approve** the Deploy run |
| Redeploy an older build | Actions → Deploy → Run workflow → `ci_run_id` |
| Deploy from a laptop (break glass) | `deploy/distributed/deploy.sh rollout` (builds locally and does the same rolling restart) |
| Manual rollback | `deploy/distributed/deploy.sh rollback` (swaps to the previous release on every node) |
| Runner offline? | `ssh … edge 'bash ~/opencs/bin/opencs.sh status runner'`; the watchdog does not manage it, so restart with `… start runner` |

## Local equivalents

`deploy.sh package` builds the same artifact CI builds. Run with `OPENCS_ARTIFACTS=<dir>`, `deploy.sh cd` performs exactly what the runner does.
