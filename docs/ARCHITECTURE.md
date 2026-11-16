# OpenCS Labs — architecture

The full design baseline is [`../HLD.md`](../HLD.md). This page is the map of
how the implementation is organised and how a request flows.

## Components

```
                      ┌───────────────────────── browser ─────────────────────────┐
                      │  React SPA (frontend/)        JupyterLab + OpenCS extension │
                      └───────────┬───────────────────────────┬────────────────────┘
                                  │ /api/v1                   │ /user/<name>/
                      ┌───────────▼───────────┐   ┌───────────▼────────────────────┐
                      │  frontend (nginx)     │   │  JupyterHub proxy              │
                      │  proxies /api →       │   │  (opencs_auth validates JWT)   │
                      └───────────┬───────────┘   └───────────┬────────────────────┘
                                  │                           │ spawns
                      ┌───────────▼───────────┐   ┌───────────▼────────────────────┐
                      │  backend (FastAPI)    │   │  per-user notebook pod         │
                      │  auth/users/learning  │   │  opencs/analytics:1.0.0        │
                      │  practice/datasets/   │◄──┤  PVC /home/opencs              │
                      │  notebooks            │   │  RO /opt/opencs/datasets       │
                      └───┬───────────┬───────┘   └────────────────────────────────┘
                          │           │
              ┌───────────▼──┐   ┌────▼─────────┐   ┌────────────────────────────┐
              │ PostgreSQL   │   │ MinIO (S3)   │   │ grading sandbox (docker/Job)│
              │ metadata     │   │ datasets     │   │ opencs/analytics:1.0.0      │
              └──────────────┘   └──────────────┘   └────────────────────────────┘
```

## Backend modules

A modular monolith: one deployable app, one database, but each feature owns
its models, schemas, service and router.

| Module | Responsibility |
|---|---|
| `app/core` | config, errors, security, logging, metrics, rate limiting, validation |
| `app/db` | engine/session, declarative base, model registry |
| `app/auth` | login, session issuance, current-user dependencies, role gates |
| `app/users` | user model, profile and preferences |
| `app/courses` | course and enrollment models |
| `app/learning` | paths, modules, lessons, progress, notebook activity launch |
| `app/practice` | exercise catalogue, attempts, evaluation, feedback |
| `app/datasets` | manifests, catalogue, preview, snippet composition |
| `app/notebooks` | notebook metadata, ipynb helpers, storage orchestration |
| `app/integrations` | JupyterHub client, notebook backend seam, grader |

The `integrations` layer is the only place that talks to infrastructure. Tests
replace it with fakes, which is why the suite runs with no cluster.

## The notebook request path

1. `POST /learning/lessons/{slug}/launch` or `POST /practice/exercises/{slug}/attempts`.
2. The service asks the notebook backend whether the user's server is ready;
   if not, it checks capacity and requests a spawn, then polls until ready.
3. Cells are composed server-side (intro markdown + authored code) and written
   through the user's server API using a scoped token minted by the Hub.
4. Metadata is recorded in PostgreSQL; the notebook body lives in Jupyter
   storage only.
5. The response carries the open URL, which the browser opens in a new tab.

## The dataset request path

1. `GET /datasets/{slug}/snippet` resolves the published manifest and the
   current version.
2. The absolute path is composed from `OPENCE_DATASET_MOUNT_PATH` and the
   manifest's relative path — no browser input.
3. The response sets `auto_execute: false` and returns readable pandas code.
4. The student pastes it (web UI) or the extension inserts it (JupyterLab);
   neither executes it.

## Frontend structure

```
src/
├── api/            typed client + OpenAPI-derived types
├── app/            AuthContext, routes, layout, useAsync
├── components/     ui primitives, block renderer, SVG chart
├── features/
│   ├── auth/       login
│   ├── learning/   catalogue + lesson reader
│   ├── practice/   catalogue + exercise workspace
│   ├── datasets/   catalogue + dataset detail
│   └── notebooks/  workspace management
├── styles/         tokens + layout
└── test/           vitest + testing-library
```

## Content pipeline

```
content/*.yaml ──► validate_content.py ──► seed.py ──► PostgreSQL ──► API ──► UI
```

Lessons carry a fixed seven-stage structure (explore → understand → inspect →
execute → visualize → debug → practice). The validator enforces it, so a
malformed lesson fails CI rather than a student's screen.

## Dataset pipeline

```
fetch_datasets.py ──► datasets/serving/ + manifests
                             │
                    sync_datasets.py (re-verify sha256)
                             ├──► MinIO (durable copy)
                             └──► RO volume at /opt/opencs/datasets (all pods)
```
