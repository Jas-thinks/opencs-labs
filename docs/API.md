# OpenCS Labs — API reference

Base path: `OPENCE_API_PREFIX` (default `/api/v1`). All application endpoints
require an authenticated session: either the `opencs_session` HttpOnly cookie
set by `POST /auth/login`, or an `Authorization: Bearer <token>` header from
`POST /auth/token`.

Errors are structured and stable:

```json
{ "error": { "code": "NOT_FOUND", "message": "dataset not found", "details": {} } }
```

Common codes: `UNAUTHENTICATED` (401), `FORBIDDEN` (403), `NOT_FOUND` (404),
`CONFLICT` / `NO_AUTOMATED_CHECKS` / `NO_NOTEBOOK` (409), `VALIDATION_ERROR`
(422), `CAPACITY_EXHAUSTED` / `UPSTREAM_UNAVAILABLE` (503).

Interactive documentation is served at `GET /api/docs`.

---

## Authentication

| Method | Path | Purpose |
|---|---|---|
| POST | `/auth/login` | Dev-mode email+password sign-in; sets the session cookie |
| POST | `/auth/token` | Exchange credentials for a bearer token (CLI, load tests) |
| POST | `/auth/logout` | Clear the session cookie |
| GET  | `/auth/mode` | The configured auth mode (`dev` / `oidc`) |

`LoginResponse`: `{ user: UserOut, expires_in: number }`

## Profile

| Method | Path | Purpose |
|---|---|---|
| GET | `/me` | Current user and role |
| GET | `/me/preferences` | Allowed preferences |
| PATCH | `/me/preferences` | Update `theme`, `editor_font_size`, `default_notebook_profile` |
| GET | `/me/courses` | Course memberships |

`UserOut`: `{ id, email, display_name, role, hub_username, preferences }`

## Learning

| Method | Path | Purpose |
|---|---|---|
| GET  | `/learning/paths` | Published paths with modules, lessons and progress |
| GET  | `/learning/modules` | Flat module list with `path_slug` |
| GET  | `/learning/lessons/{slug}` | Full lesson content and progress |
| POST | `/learning/lessons/{slug}/progress` | `{ status, last_section? }` |
| POST | `/learning/lessons/{slug}/launch` | Create the lesson notebook and return its URL |

`LessonDetail.content` is the authored `stages` array (seven stages:
explore, understand, inspect, execute, visualize, debug, practice), plus
`takeaways` and `glossary`. Blocks may be `markdown`, `code`, `output`,
`table`, `chart`, `callout`, `steps`, `mistakes`, `checklist`.

## Practice

| Method | Path | Purpose |
|---|---|---|
| GET  | `/practice/exercises` | Filter by `topic`, `difficulty` (Easy/Medium/Hard), `q` |
| GET  | `/practice/topics` | Topic counts |
| GET  | `/practice/progress` | Per-topic attempts and completions |
| GET  | `/practice/exercises/{slug}` | Exercise detail, hints, datasets |
| POST | `/practice/exercises/{slug}/attempts` | Start an attempt; creates the starter notebook |
| GET  | `/practice/attempts/{id}` | Own attempt status |
| POST | `/practice/attempts/{id}/evaluate` | Run automated checks in the sandbox |
| GET  | `/practice/attempts/{id}/feedback` | Retrieve stored feedback |

`AttemptCreateResponse`: `{ attempt, notebook, url, hints }`.
Evaluation returns `FeedbackResponse`: `{ attempt_id, status, passed, score,
tests, message, evaluated_at }`. Solution code is never serialised.

## Dataset catalogue

| Method | Path | Purpose |
|---|---|---|
| GET | `/datasets` | Search/list (`q`, `category`, `tag`, `limit`, `offset`) |
| GET | `/datasets/categories` | Category counts |
| GET | `/datasets/{slug}` | Detail: schema, preview, versions, licence |
| GET | `/datasets/{slug}/preview` | Bounded live preview (`limit` ≤ 100) |
| GET | `/datasets/{slug}/snippet` | Validated loading code (**never executes**) |
| GET | `/datasets/{slug}/versions` | Version history with checksums |

`SnippetResponse`:

```json
{
  "dataset_id": "iris",
  "version": 1,
  "language": "python",
  "cell_type": "code",
  "auto_execute": false,
  "code": "import pandas as pd\n\n# Iris (v1) — read-only OpenCS dataset\ndf = pd.read_csv('/opt/opencs/datasets/iris/v1/iris.csv')\ndf.head()",
  "path": "/opt/opencs/datasets/iris/v1/iris.csv",
  "read_only": true
}
```

`auto_execute` is always `false`. The path is composed server-side from the
manifest; the browser cannot contribute a path segment.

## Notebooks

| Method | Path | Purpose |
|---|---|---|
| GET    | `/notebooks/server` | Current user's server state |
| POST   | `/notebooks/server/start` | Request a spawn (rate limited) |
| POST   | `/notebooks/server/stop` | Request a shutdown |
| GET    | `/notebooks` | Own notebook metadata (adopts files from JupyterLab) |
| POST   | `/notebooks` | Create a notebook (`{ title }`) |
| PATCH  | `/notebooks/{id}` | Rename |
| DELETE | `/notebooks/{id}` | Delete (204) |
| GET    | `/notebooks/{id}/open` | Authorized open URL |
| GET    | `/notebooks/{id}/download` | Download the `.ipynb` |

`ServerStateOut`: `{ running, ready, status, pending, url }`.

Ownership is enforced on every operation; another user's notebook is reported
as `404`, indistinguishable from missing.

## Operations

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Liveness |
| GET | `/ready` | Readiness (checks the database) |
| GET | `/metrics` | Prometheus metrics |
| GET | `/config` | Non-secret runtime facts for the UI |

## Rate limits

`server/start`, `notebooks/{id}/open`, lesson launch and practice attempt
start are limited per user; evaluation is limited more tightly. Limits are
configured by `OPENCE_RATE_LIMIT_*` and applied per backend process (see
`docs/TECHNICAL_DECISIONS.md`).
