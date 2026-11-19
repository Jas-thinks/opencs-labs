# OpenCS Labs — architecture

**Strict rule: no Docker.** The production deployment uses native systemd
services, Python virtualenvs, Nginx, PostgreSQL and a custom
SSH/systemd JupyterHub spawner. Do not use Docker, DockerSpawner, Swarm, or
`/var/run/docker.sock` in the 11-server topology.

The full design baseline is [`../HLD.md`](../HLD.md). This page is the map of
how the implementation is organised and how a request flows.

## Components

```
                      ┌───────────────────────── browser ─────────────────────────┐
                      │  React SPA (frontend/)        JupyterLab + OpenCS extension │
                      └───────────┬───────────────────────────┬────────────────────┘
                                  │ /api/v1                   │ /user/<name>/
                      ┌───────────▼───────────┐   ┌───────────▼────────────────────┐
                      │  lb-1 (nginx)         │   │  JupyterHub + CHP              │
                      │  static + /api proxy  │   │  (opencs_auth validates JWT)   │
                      └───────────┬───────────┘   └───────────┬────────────────────┘
                                  │                           │ SSH/systemd
                      ┌───────────▼───────────┐   ┌───────────▼────────────────────┐
                      │  api-1..3 (FastAPI)   │   │  per-user systemd JupyterLab   │
                      │  auth/users/learning  │   │  notebook-venv (no container)  │
                      │  practice/datasets/   │◄──┤  NFS /home/opencs              │
                      │  notebooks            │   │  RO /opt/opencs/datasets       │
                      └───┬───────────┬───────┘   └────────────────────────────────┘
                          │           │
              ┌───────────▼──┐   ┌────▼─────────┐   ┌────────────────────────────┐
              │ PostgreSQL   │   │ NAS / NFS    │   │ systemd-run grading sandbox │
              │ primary +    │   │ homes,       │   │ notebook-venv, no network   │
              │ standby +    │   │ datasets,    │   │ no Docker                   │
              │ read replica │   │ backups      │   │                            │
              └──────────────┘   └──────────────┘   └────────────────────────────┘
```

## Deployment topology (no Docker)

```
1  lb-1        Nginx static frontend + TLS + /api, /hub, /user proxy
3  api-1..3    FastAPI (uvicorn workers) + opencs-worker outbox
3  db-1..3     PostgreSQL primary + synchronous standby + async read replica
4  nb-1..nb-4  JupyterHub + per-user systemd JupyterLab + systemd-run grading
5  spare-1..5  unassigned; promote to nb-5..nb-9 for 500 standard sessions
---
11 assigned, 5 spare
```

`n_1 = 3`, `n_2 = 4`, `1 + 3 + 3 + 4 = 11 ≤ 16`. The four notebook nodes
support ~224 standard 2 GB sessions, ~56 8 GB sessions or ~28 16 GB sessions;
500 standard sessions require promoting `nb-5..nb-9`. See `PLAN_2.md` for the
capacity verdict and `DEPLOYMENT.md` for the native systemd runbook.

## Backend modules

A modular monolith: one deployable app, one database, but each feature owns
its models, schemas, service and router.

| Module | Responsibility |
|---|---|
| `app/core` | config, errors, security, logging, metrics, rate limiting, validation |
| `app/db` | engine/session, declarative base, model registry |
| `app/auth` | login, session issuance, current-user dependencies, role gates |
| `app/users` | user model, profile and preferences |
| `app/courses` | classes, enrollments, course-scoped permissions, members, join codes |
| `app/grading` | assignments (lifecycle, starter notebooks), rubrics, submissions, draft/returned grade revisions |
| `app/analytics` | student and class dashboards, drill-down, CSV export (released grades only) |
| `app/stream` | one-way course stream: announcements, materials, attachments, read receipts (ADR-010) |
| `app/notifications` | in-app inbox; fan-out runs in the job worker |
| `app/teaching` | persona read models: gradebook, grading queue, student home |
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
4. Metadata is recorded in PostgreSQL; the working notebook body lives in
   Jupyter storage, and immutable snapshots are stored in
   `notebook_blobs`/`notebook_versions` for grading and analytics.
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
├── app/            AuthContext (persona + mode), role-aware routes and layout, useAsync
├── components/     ui primitives, block renderer, SVG chart, NotebookView (sandboxed), kit
├── features/
│   ├── auth/       login
│   ├── classes/    class list, course shell + Stream/Classwork/People/Grades/Insights tabs,
│   │               assignment editor (rubric builder) and student assignment page
│   ├── grading/    grading workspace, to-grade queue, student progress, analytics
│   ├── home/       student home
│   ├── notifications/ bell + inbox
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
                             ├──► MinIO (optional durable copy)
                             └──► RO mount at /opt/opencs/datasets (all notebook nodes)
```
