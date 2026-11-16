# OpenCS Labs -- infrastructure

Everything needed to run OpenCS Labs on Kubernetes: the platform control plane
(FastAPI + React), JupyterHub with KubeSpawner, PostgreSQL, MinIO, the read-only
dataset serving tree, monitoring and admission policy.

**Two deployment paths, one contract.**

| Path | Status | Use it for |
| --- | --- | --- |
| `helm/opencs/` | **Recommended.** Versioned, templated, `--reuse-values` upgrades, rollback history. | Any shared, staging or production cluster. |
| `kubernetes/` | **Reference implementation.** Plain manifests, applied with `kubectl apply -f`. | Reading the intent, air-gapped bootstrap, disaster recovery, and diffing what the chart renders. |

The two describe the same system with the same resource names, labels, ports and
environment variables. When you change one, change the other, or the paths drift
and the runbooks become wrong. The raw manifests are deliberately more explicit
(every probe, every `securityContext`, every comment) because their job is to be
read as well as applied.

---

## Directory map

```
infrastructure/
├── README.md                        this file: apply order + environment contract
├── helm/
│   └── opencs/                      the recommended chart
│       ├── Chart.yaml               v2, name opencs, version/appVersion 1.0.0
│       ├── values.yaml              production defaults for every component
│       └── templates/
│           ├── _helpers.tpl         name/fullname/labels/selectorLabels/image helpers + value validation
│           ├── backend-deployment.yaml
│           ├── backend-service.yaml
│           ├── frontend-deployment.yaml
│           ├── frontend-service.yaml
│           ├── configmap.yaml       renders `opencs-config`
│           ├── secret.yaml          renders `opencs-secrets` only when no existingSecret is set
│           ├── ingress.yaml         one host, four paths, TLS, WebSocket, + JupyterHub proxy alias
│           ├── serviceaccount.yaml  token never mounted
│           └── NOTES.txt            post-install steps
├── kubernetes/                      reference manifests (apply in the order below)
│   ├── namespace.yaml               opencs + opencs-hub, with Pod Security Admission labels
│   ├── configmap.yaml               opencs-config: every non-secret OPENCE_* setting
│   ├── secret.example.yaml          opencs-secrets TEMPLATE -- never commit real values
│   ├── postgres.yaml                StatefulSet + headless Service (metadata store)
│   ├── minio.yaml                   StatefulSet + Service + minio-init Job (bucket creation)
│   ├── datasets-pvc.yaml            RWX serving PVC + datasets-sync Job
│   ├── backend.yaml                 Deployment (2 replicas) + Service
│   ├── frontend.yaml                Deployment (2 replicas) + Service
│   ├── ingress.yaml                 Ingress + ExternalName alias to the hub proxy
│   ├── networkpolicy.yaml           default-deny + the explicit allow-list for both namespaces
│   └── pdb.yaml                     PodDisruptionBudgets for backend/frontend/postgres/minio
├── helm/                            (see above)
├── storage/
│   ├── README.md                    dataset lifecycle: raw → verify → MinIO → PVC → read-only mount
│   └── storageclass-rwx.yaml        example RWX class for the serving tree + example RWO home class
├── monitoring/
│   ├── prometheus-rules.yaml        PrometheusRule: opencs-api / opencs-hub / opencs-infra
│   ├── servicemonitor.yaml          ServiceMonitors for the backend and JupyterHub
│   └── grafana-dashboard.json       Grafana dashboard (schemaVersion 39)
└── policies/
    ├── README.md                    policy index and the four-layer enforcement model
    ├── kyverno-notebook-policy.yaml ClusterPolicy opencs-notebook-guardrails
    └── resourcequota.yaml           ResourceQuota + LimitRange for opencs-hub
```

---

## Apply order

Dependencies are real: the backend's `/ready` probe fails without PostgreSQL, the
`minio-init` Job needs MinIO, and notebook pods cannot mount a PVC that does not
exist. Apply in this order, or use the Helm path which documents the same order in
`templates/NOTES.txt`.

```bash
# 0. Prerequisites you supply (not in this repo):
#      - a StorageClass for RWO volumes (student homes, PostgreSQL, MinIO)
#      - a RWX StorageClass for the dataset tree (see storage/storageclass-rwx.yaml)
#      - ingress-nginx, cert-manager, kube-prometheus-stack
#      - Kyverno (only for policies/kyverno-notebook-policy.yaml)

# 1. NAMESPACES
kubectl apply -f infrastructure/kubernetes/namespace.yaml

# 2. STORAGE
kubectl apply -f infrastructure/storage/storageclass-rwx.yaml   # if you need one
kubectl apply -f infrastructure/kubernetes/datasets-pvc.yaml    # PVC (+ sync Job, see below)

# 3. SECRETS  -- out of band, never from a committed file
kubectl -n opencs create secret generic opencs-secrets \
  --from-literal=OPENCE_JWT_SECRET="..." \
  --from-literal=OPENCE_JUPYTERHUB_API_TOKEN="..." \
  --from-literal=OPENCE_DATABASE_URL="..." \
  --from-literal=OPENCE_S3_ACCESS_KEY="..." \
  --from-literal=OPENCE_S3_SECRET_KEY="..." \
  --from-literal=OPENCE_OIDC_CLIENT_SECRET="..." \
  --from-literal=POSTGRES_PASSWORD="..." \
  --from-literal=MINIO_ROOT_USER="..." \
  --from-literal=MINIO_ROOT_PASSWORD="..."
#    secret.example.yaml documents the key set. It is a template, not a manifest.

# 4. CONFIG
kubectl apply -f infrastructure/kubernetes/configmap.yaml

# 5. POSTGRES
kubectl apply -f infrastructure/kubernetes/postgres.yaml
kubectl -n opencs rollout status sts/postgres --timeout=180s
#    Apply schema migrations before starting the backend:
kubectl -n opencs exec -it sts/postgres -- psql -U opencs -d opencs -c 'select 1;'

# 6. MINIO
kubectl apply -f infrastructure/kubernetes/minio.yaml
kubectl -n opencs rollout status sts/minio --timeout=180s
kubectl -n opencs wait --for=condition=complete job/minio-init --timeout=300s

# 7. DATASETS  -- publish to MinIO, then materialise the serving tree
make fetch-datasets && make sync-datasets          # from a workstation with network
kubectl -n opencs delete job datasets-sync --ignore-not-found
kubectl apply -f infrastructure/kubernetes/datasets-pvc.yaml
kubectl -n opencs wait --for=condition=complete job/datasets-sync --timeout=1800s
#    Full lifecycle and troubleshooting: storage/README.md

# 8. HUB  -- JupyterHub in opencs-hub (Zero to JupyterHub chart)
helm repo add jupyterhub https://hub.jupyter.org/helm-chart/
helm upgrade --install jupyterhub jupyterhub/jupyterhub \
  --namespace opencs-hub --create-namespace \
  --version "$(grep -A3 '^  chart:' infrastructure/helm/opencs/values.yaml | awk '/version:/{gsub(/"/,"",$2);print $2}')" \
  --values infrastructure/helm/jupyterhub-values.yaml
#    The hub must use proxy.service.type=ClusterIP and the OpenCS authenticator;
#    see the `jupyterhub:` block in helm/opencs/values.yaml.

# 9. APP  -- backend, frontend, ingress, disruption budgets
kubectl apply -f infrastructure/kubernetes/backend.yaml
kubectl apply -f infrastructure/kubernetes/frontend.yaml
kubectl apply -f infrastructure/kubernetes/ingress.yaml
kubectl apply -f infrastructure/kubernetes/pdb.yaml
kubectl -n opencs rollout status deploy/opencs-backend  --timeout=180s
kubectl -n opencs rollout status deploy/opencs-frontend --timeout=180s

# 10. POLICY + OBSERVABILITY
kubectl apply -f infrastructure/policies/kyverno-notebook-policy.yaml
kubectl apply -f infrastructure/policies/resourcequota.yaml
kubectl apply -f infrastructure/kubernetes/networkpolicy.yaml     # after workloads exist
kubectl apply -f infrastructure/monitoring/servicemonitor.yaml
kubectl apply -f infrastructure/monitoring/prometheus-rules.yaml
```

> Apply `networkpolicy.yaml` **after** the workloads are running. NetworkPolicy
> is an allow-list; applying default-deny first is safe, but the allow rules
> reference pod labels that must exist for traffic to flow, so ordering here
> trades a few seconds of unintended access for a much easier first install. On
> a cluster with existing traffic, apply it first and accept the brief outage.

### The Helm path

```bash
helm upgrade --install opencs infrastructure/helm/opencs \
  --namespace opencs --create-namespace \
  --values infrastructure/helm/opencs/values.yaml \
  --set global.origin=https://opencs.example.edu

# Then follow:
helm get notes opencs -n opencs
```

The chart renders the backend, frontend, ConfigMap, Secret (optionally),
ServiceAccount and Ingress. PostgreSQL, MinIO, JupyterHub and the dataset PVC are
applied from the raw manifests (steps 5-8) because they are stateful,
slow-upgrading, or owned by another chart -- keeping them out of the application
release means an app rollback can never roll back a database.

`helm template` is the fastest way to see what the chart would do:

```bash
helm template opencs infrastructure/helm/opencs --namespace opencs
helm lint infrastructure/helm/opencs
```

---

## Environment variable contract

Configuration crosses three boundaries: a ConfigMap (non-secret), a Secret
(credentials), and build-time frontend settings. Only the backend reads
`OPENCE_*`; the frontend is a static bundle whose API base is compiled in.

### Layer 1 -- `opencs-config` (ConfigMap, non-secret)

Consumed by the backend via `envFrom.configMapRef` (`backend/app/core/config.py`,
`env_prefix="OPENCE_"`). Also read by the `datasets-sync` and `minio-init` Jobs.

| Variable | Example | Notes |
| --- | --- | --- |
| `OPENCE_ENV` | `production` | Must be `production` in production; it enables strict startup validation. |
| `OPENCE_API_PREFIX` | `/api/v1` | Must match the Ingress `/api` path and the frontend's `VITE_API_BASE`. |
| `OPENCE_PUBLIC_ORIGIN` | `https://opencs.example.edu` | The single browser origin. Drives CORS and generated links. |
| `OPENCE_JUPYTERHUB_URL` | `https://opencs.example.edu` | Browser-facing Hub URL. |
| `OPENCE_JUPYTERHUB_API_URL` | `http://hub.opencs-hub.svc.cluster.local:8081/hub/api` | In-cluster Hub REST API. |
| `OPENCE_JUPYTERHUB_PUBLIC_URL` | `https://opencs.example.edu` | Used to build `/user/<name>/lab` links. |
| `OPENCE_NOTEBOOK_BACKEND` | `hub` | `hub` is required in production; `disabled` exists for development only. |
| `OPENCE_DATASET_MOUNT_PATH` | `/opt/opencs/datasets` | Path the kernel sees; the generated loading cell hard-codes it. |
| `OPENCE_DATASET_SERVING_DIR` | `/opt/opencs/datasets` | Path the backend reads for previews/snippets. Same tree, same mount. |
| `OPENCE_ENVIRONMENT_IMAGE` | `opencs/analytics:1.0.0` | Reported to the UI as the pinned notebook environment. |
| `OPENCE_MAX_ACTIVE_SESSIONS` | `450` | Admission ceiling: 400 target + 50 launch headroom. Keep in step with `policies/resourcequota.yaml`. |
| `OPENCE_RATE_LIMIT_ENABLED` | `true` | Per-principal sliding window for launch/evaluate. |
| `OPENCE_GRADER` | `docker` | Grading sandbox backend. |
| `OPENCE_COOKIE_SECURE` | `true` | **Required** in production; startup fails without it. |
| `OPENCE_AUTH_MODE` | `oidc` | `dev` password auth is refused in production. |
| `OPENCE_OIDC_ISSUER` | `https://idp.example.edu/realms/opencs` | Public issuer URL. |
| `OPENCE_S3_ENDPOINT` | `http://minio.opencs.svc.cluster.local:9000` | S3-compatible endpoint. |
| `OPENCE_S3_BUCKET` | `opencs-datasets` | Must match the bucket created by `minio-init`. |
| `OPENCE_S3_REGION` | `us-east-1` | MinIO ignores it but boto3 requires a value. |
| `OPENCE_GRADER_IMAGE` / `_TIMEOUT_SECONDS` / `_MEMORY` / `_CPUS` | `opencs/analytics:1.0.0` / `90` / `1g` / `1` | Grading sandbox envelope. |
| `OPENCE_RATE_LIMIT_LAUNCH_PER_MINUTE` | `10` | |
| `OPENCE_RATE_LIMIT_EVALUATE_PER_MINUTE` | `6` | |
| `OPENCE_NOTEBOOK_START_TIMEOUT_SECONDS` | `120` | Backend-side wait; keep below the Ingress read timeout. |

Setting a non-secret value in the Secret instead works, but it will not be
visible in `kubectl describe cm opencs-config` and the two sources would drift.

### Layer 2 -- `opencs-secrets` (Secret)

Consumed by the backend, the PostgreSQL StatefulSet and the MinIO StatefulSet.
Never in git, never in a Helm value you commit, never echoed into a log.

| Key | Consumed by | Notes |
| --- | --- | --- |
| `OPENCE_JWT_SECRET` | backend, JupyterHub | >= 32 chars. The same value is what makes SSO work: the Hub's OpenCS authenticator validates it. Weak values are rejected at production startup. |
| `OPENCE_JUPYTERHUB_API_TOKEN` | backend | Hub admin token. Held only by the backend process, never sent to a browser. |
| `OPENCE_DATABASE_URL` | backend | `postgresql+psycopg://opencs:<pw>@postgres.opencs.svc.cluster.local:5432/opencs`. Password must equal `POSTGRES_PASSWORD`. |
| `OPENCE_S3_ACCESS_KEY` / `_SECRET_KEY` | backend, datasets-sync Job | MinIO credentials for `opencs-datasets`. |
| `OPENCE_OIDC_CLIENT_SECRET` | backend | Paired with the public `OPENCE_OIDC_ISSUER`. |
| `POSTGRES_PASSWORD` | postgres StatefulSet | Must match the password inside `OPENCE_DATABASE_URL`. |
| `MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD` | minio StatefulSet, minio-init Job | MinIO root identity. For a stricter setup, keep root out of the backend and create a bucket-scoped MinIO service account instead. |

Prefer External Secrets / Sealed Secrets / Vault over `kubectl create secret` so
plaintext never touches a workstation.

### Layer 3 -- Frontend build-time

The frontend is a static React bundle served by nginx. It has no runtime config
endpoint, so these are baked in at image build time:

| Variable | Example | Notes |
| --- | --- | --- |
| `VITE_API_BASE` | `/api/v1` | Same-origin relative path; must match `OPENCE_API_PREFIX` and the Ingress `/api` path. |
| `VITE_NOTEBOOK_ORIGIN` | *(empty)* | Empty = same origin, which is the required production posture. |

### Layer 4 -- JupyterHub (`opencs-hub`)

The Hub has its own configuration surface (Zero to JupyterHub values) and reads
its own copy of `OPENCE_JWT_SECRET` plus an API token the backend shares. The
values this platform requires are documented in the `jupyterhub:` block of
`helm/opencs/values.yaml`:

- `proxy.service.type: ClusterIP` -- the OpenCS Ingress is the only browser entry
  point, so there is exactly one origin.
- `public_url` / `bind_url` = `OPENCE_PUBLIC_ORIGIN`.
- KubeSpawner image `opencs/analytics:1.0.0`, uid/gid 1000, with the `opencs-datasets`
  PVC mounted read-only at `/opt/opencs/datasets`.
- Idle cull after 30 minutes; `automountServiceAccountToken: false`.

---

## What each layer needs from you

| Layer | Required inputs | Fails how without them |
| --- | --- | --- |
| Namespaces | nothing | -- |
| StorageClass (RWX) | a shared-filesystem CSI driver | dataset PVC stays `Pending` forever |
| Datasets PVC | RWX class, 50Gi free | notebook pods cannot start (volume mount timeout) |
| Secrets | 9 keys (see table above) | backend refuses to start in production; postgres/minio fail to init |
| ConfigMap | a real origin + issuer | backend warns and, in production, refuses to start |
| PostgreSQL | PVC class, `POSTGRES_PASSWORD` | `/ready` fails, so no backend pod becomes Ready |
| MinIO | `MINIO_ROOT_*`, PVC class | dataset publish and object reads fail |
| JupyterHub | chart, OIDC config, API token | notebook launch returns 503 upstream unavailable |
| Backend/Frontend | secrets + config + dataset PVC | crash loop or unreachable UI |
| Monitoring | Prometheus Operator CRDs | `ServiceMonitor`/`PrometheusRule` are rejected as unknown kinds |
| Policies | Kyverno, PSA labels | no admission guardrails on student code |

---

## Health and verification

```bash
# Workload state
kubectl -n opencs     get deploy,sts,svc,ing,pvc,job
kubectl -n opencs-hub get deploy,sts,svc

# The two probes mean different things:
#   /health  liveness -- process is up, database NOT checked
#   /ready   readiness -- executes SELECT 1, so it gates traffic on PostgreSQL
kubectl -n opencs run curl-check --rm -it --restart=Never \
  --image=curlimages/curl:8.8.0 -- \
  curl -fsS http://opencs-backend.opencs.svc.cluster.local/health

# Metrics are exposed at /metrics and scraped every 30s by the ServiceMonitor.
kubectl -n opencs run curl-check --rm -it --restart=Never \
  --image=curlimages/curl:8.8.0 -- \
  curl -fsS http://opencs-backend.opencs.svc.cluster.local/metrics | head -40

# End-to-end through the single origin:
curl -sI https://opencs.example.edu/                # SPA shell
curl -s  https://opencs.example.edu/api/v1/config   # public runtime facts
curl -sI https://opencs.example.edu/hub/hub/login   # JupyterHub
```

## Capacity arithmetic worth remembering

- 450 concurrent single-user pods upper bound: **225 CPU / 900Gi** of *requests*
  in `opencs-hub` -- see `policies/resourcequota.yaml` for the derivation.
- 600 enrolled students x 5Gi home = **3TiB** of PVC storage.
- Per-user homes are RWO with one PVC each; the dataset tree is RWX and shared.
  Mixing those up is the single most common way to break a 400-user deployment:
  the notebook pods will mount-timeout, not error visibly.

## Where to read next

- `storage/README.md` -- dataset lifecycle in detail, plus the RWX trade-off.
- `policies/README.md` -- the four-layer enforcement model and the known gaps
  (containers are not VMs; read it before promising isolation to anyone).
- `../HLD.md` sections 10, 12, 13 and 16 -- storage design, capacity planning,
  security and deployment architecture.
