# OpenCS Labs

A multi-user platform for teaching and practising Data Analysis and Data
Science through **persistent, isolated Jupyter notebooks**.

Students move through three connected experiences:

- **Learn** — guided, visual, seven-stage lessons that end in a runnable notebook.
- **Practice** — structured exercises in the student's own isolated notebook, with hints and automated checks.
- **Notebooks** — a persistent JupyterLab workspace, plus a curated dataset catalogue whose loading cells are inserted *but never auto-executed*.

Notebook execution is provided by **JupyterHub + KubeSpawner + Kubernetes**.
The application is a FastAPI modular monolith plus a React SPA.

The architecture baseline is [`HLD.md`](./HLD.md). It is the source of truth;
deviations are recorded in [`docs/ADR`](./docs/ADR).

---

## Quick start (containers)

```bash
cp .env.example .env          # adjust secrets if you like
make up                       # builds and starts the whole stack
```

| Service   | URL                          |
|-----------|------------------------------|
| App       | http://localhost:5173        |
| API docs  | http://localhost:8000/api/docs |
| JupyterHub| http://localhost:8001        |
| MinIO     | http://localhost:9001        |

Demo accounts (development only, password `opencs-demo`):

| Email                     | Role         |
|---------------------------|--------------|
| `student@opencs.local`    | student      |
| `student2@opencs.local`   | student      |
| `ta@opencs.local`         | course TA    |
| `instructor@opencs.local` | instructor   |
| `admin@opencs.local`      | administrator|

`make up` needs Docker. The notebook image is built by `make build-image`; the
compose stack pulls `opencs/analytics:1.0.0`, so build it first if you want a
working JupyterHub:

```bash
make build-image             # opencs/analytics:1.0.0
make up
```

## Quick start (local processes)

```bash
make install                 # venv + backend deps + frontend deps
make fetch-datasets          # prove the dataset library (already committed)
make migrate                 # alembic upgrade head
make seed                    # demo users, curriculum, exercises, datasets
make backend                 # :8000  (one terminal)
make frontend                # :5173  (another terminal)
```

The backend defaults to SQLite when `OPENCE_DATABASE_URL` is unset, so this
works without PostgreSQL. Notebook features need a reachable JupyterHub — point
`OPENCE_JUPYTERHUB_*` at one, or run `make up`.

## Repository layout

```
backend/            FastAPI modular monolith (auth, users, learning, practice,
                    datasets, notebooks) + Alembic migrations + tests
frontend/           React + TypeScript SPA (Vite)
content/            Lessons (YAML) and exercises (YAML) — the curriculum
datasets/           Manifests + read-only serving tree
notebook-image/     Pinned analytics image + smoke tests + grading runner
jupyterhub/         Hub config, OpenCS authenticator, image
jupyterlab-extension/ Dataset cell-insertion extension (ADR-008)
infrastructure/     Kubernetes manifests, Helm chart, monitoring, policies
scripts/            fetch/sync datasets, seed, validate content
tests/load/         Measured load-test harness
docs/               ADRs and operational documentation
```

## Testing

```bash
make test            # backend (pytest) + frontend (vitest)
make validate        # curriculum/exercise content validation
make check           # everything CI runs
make test-env        # notebook image smoke tests (needs Docker)
make test-security
make test-integration
make loadtest        # against a running stack; reports measured numbers only
```

## The one rule that shapes everything

**Dataset selection inserts a code cell; it never executes it.** The cell runs
only when the student presses Run, inside their own kernel. This is enforced in
four places: the snippet API (`auto_execute: false`), the JupyterLab extension
(which refuses `auto_execute: true` and contains no `requestExecute` call), the
CI check that greps for that call, and the UI copy.

## Images

| Image | Built by | Contains |
|---|---|---|
| `opencs/analytics:1.0.0` | `notebook-image/build.sh` | pinned Python data stack, JupyterLab, the OpenCS extension, `grade_runner.py` |
| `opencs/backend:1.0.0` | `backend/Dockerfile` | FastAPI app, migrations, entrypoint |
| `opencs/frontend:1.0.0` | `frontend/Dockerfile` | static SPA on nginx with an `/api` proxy |
| `opencs/jupyterhub:1.0.0` | `jupyterhub/Dockerfile` | Hub, KubeSpawner, DockerSpawner, authenticator, idle-culler |

The analytics image builds the JupyterLab extension in a discarded Node stage,
so the runtime image carries no Node.js.

## Documentation

- [`HLD.md`](./HLD.md) — architecture baseline
- [`docs/ADR`](./docs/ADR) — architecture decision records
- [`docs/API.md`](./docs/API.md) — endpoint reference
- [`docs/SECURITY.md`](./docs/SECURITY.md) — threat model and controls
- [`docs/OPERATIONS.md`](./docs/OPERATIONS.md) — deploy, backup, recovery
- [`docs/LOAD_TEST_PLAN.md`](./docs/LOAD_TEST_PLAN.md) — 400-user validation plan
- [`docs/TECHNICAL_DECISIONS.md`](./docs/TECHNICAL_DECISIONS.md) — implementation-level decisions

## Known limitations

- The 400-concurrent-user target is a **capacity target**. The load harness
  reports measured results; no readiness claim is made without running it.
- `license_status: review-required` datasets (titanic, tips, california-housing,
  diabetes) need redistribution terms confirmed before production.
- Production uses Kubernetes; the Compose stack is for development and small
  deployments and uses DockerSpawner instead of KubeSpawner.
