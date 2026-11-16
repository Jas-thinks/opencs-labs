# Operations

## Deploy targets

| Target | Topology | Use |
|---|---|---|
| Docker Compose | single host, DockerSpawner | development, small class |
| Kubernetes + Helm | Hub + KubeSpawner + per-user pods | production, 400 concurrent users |

## Configuration

All settings are `OPENCE_*` environment variables (see `.env.example`). Secrets
come from a Kubernetes Secret in production.

Production startup refuses to run when:

- `OPENCE_JWT_SECRET` is short or contains `change-me`
- `OPENCE_COOKIE_SECURE` is false
- `OPENCE_NOTEBOOK_BACKEND` is not `hub`
- `OPENCE_JUPYTERHUB_API_TOKEN` is empty
- `OPENCE_AUTH_MODE` is `dev`

## First deploy (Kubernetes)

```bash
# 1. namespaces and config
kubectl apply -f infrastructure/kubernetes/namespace.yaml
kubectl apply -f infrastructure/kubernetes/grading-namespace.yaml
kubectl apply -f infrastructure/kubernetes/grading-rbac.yaml
kubectl apply -f infrastructure/kubernetes/configmap.yaml

# 2. secrets (never commit these)
kubectl -n opencs create secret generic opencs-secrets \
  --from-literal=OPENCE_JWT_SECRET="$(openssl rand -base64 48)" \
  --from-literal=OPENCE_JUPYTERHUB_API_TOKEN="$(openssl rand -hex 32)" \
  --from-literal=OPENCE_DATABASE_URL="postgresql+psycopg://opencs:<pw>@postgres:5432/opencs" \
  --from-literal=OPENCE_S3_ACCESS_KEY=... \
  --from-literal=OPENCE_S3_SECRET_KEY=...

# 3. storage and data services
kubectl apply -f infrastructure/kubernetes/postgres.yaml
kubectl apply -f infrastructure/kubernetes/minio.yaml
kubectl apply -f infrastructure/kubernetes/datasets-pvc.yaml

# 4. application
kubectl apply -f infrastructure/kubernetes/backend.yaml
kubectl apply -f infrastructure/kubernetes/frontend.yaml
kubectl apply -f infrastructure/kubernetes/ingress.yaml
kubectl apply -f infrastructure/kubernetes/networkpolicy.yaml
kubectl apply -f infrastructure/kubernetes/pdb.yaml
```

Or with Helm:

```bash
helm upgrade --install opencs infrastructure/helm/opencs \
  --namespace opencs --create-namespace \
  --set ingress.host=opencs.example.edu
```

### Migrations and seed

The backend container runs `alembic upgrade head` on start. Seed content is
**idempotent** and gated by `OPENCE_SEED_ON_START`:

```bash
kubectl -n opencs exec deploy/opencs-backend -- python /srv/seed.py
```

Seeding refuses to run in production for demo users — create real accounts
through the identity provider.

### Datasets

```bash
make fetch-datasets     # download + verify + manifest
make sync-datasets      # verify + upload to MinIO + materialise serving tree
```

The serving tree must be on a volume that notebook pods mount read-only at
`/opt/opencs/datasets`.

## Health and monitoring

- `GET /health` — liveness (no dependencies)
- `GET /ready` — readiness (executes `SELECT 1`)
- `GET /metrics` — Prometheus

Alerts ship in `infrastructure/monitoring/prometheus-rules.yaml`
(API error rate and latency, spawn failures, capacity, Postgres/MinIO down,
PVC pressure). Dashboards: `infrastructure/monitoring/grafana-dashboard.json`.

## Scaling

- **Backend:** stateless; scale replicas horizontally. Note that rate limits
  are per process.
- **Notebooks:** scale worker nodes. Each active student is one pod with
  CPU/memory requests from the KubeSpawner config.
- **Capacity guard:** `OPENCE_MAX_ACTIVE_SESSIONS` (default 450) refuses new
  spawns beyond the validated capacity with `CAPACITY_EXHAUSTED`.
- **Idle culling:** the Hub idle-culler stops servers after 30 minutes
  (`--timeout=1800`).

## Backup and recovery

| Data | Where | Backup | Restore test |
|---|---|---|---|
| Notebook files | per-user PVC | volume snapshots (daily) | restore a snapshot, open a notebook |
| Platform DB | Postgres PVC | `pg_dump` nightly + WAL | restore into a scratch DB, run `alembic current` |
| Datasets | MinIO + Git manifests | MinIO bucket versioning + re-fetch from manifests | rebuild serving tree from manifests, verify checksums |
| Content | `content/` in Git | source control | `make validate && make seed` |

### Recovery drill

1. Restore Postgres from the last dump into a scratch instance.
2. Restore one user's PVC snapshot.
3. Point a scratch backend at both; confirm `GET /notebooks` lists the notebook
   and `GET /notebooks/{id}/download` returns valid JSON.
4. Confirm `GET /datasets` returns the catalogue and `GET /datasets/iris/snippet`
   returns `auto_execute: false`.

## Failure handling

| Symptom | Likely cause | Action |
|---|---|---|
| `503 UPSTREAM_UNAVAILABLE` on launch/open | Hub unreachable or token invalid | check `opencs-hub` pods and `OPENCE_JUPYTERHUB_API_TOKEN` |
| `503 CAPACITY_EXHAUSTED` | active sessions ≥ `OPENCE_MAX_ACTIVE_SESSIONS` | add nodes or cull idle servers |
| `NOTEBOOK_START_TIMEOUT` | spawn slow / image pull | check pod events; confirm the image is present on nodes |
| Evaluation `503` | Docker/Job sandbox unavailable | check the grader path; the API never fakes a pass |
| `404` on your own notebook | file removed in JupyterLab | re-create or re-sync from JupyterLab |
| Dataset snippet path wrong | mount path mismatch | check `OPENCE_DATASET_MOUNT_PATH` in both backend and spawner |

## Upgrade procedure

1. Bump `notebook-image/requirements.lock`; `make build-image`; `make test-env`.
2. Deploy the new image tag to the spawner; existing notebooks keep their
   recorded `environment_image` metadata.
3. Run `alembic upgrade head`.
4. Roll the backend; readiness gates traffic.
5. Verify a lesson launch and a practice evaluation end to end.

## Rollback

- Backend: `kubectl rollout undo deploy/opencs-backend`.
- Image: repoint the spawner to the previous tag; new spawns use it.
- Database: Alembic downgrades exist for each revision; take a dump before
  migrating.
