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
| PUT    | `/notebooks/{id}/autosave` | Snapshot the document (`{ base_version, document }`) |
| POST   | `/notebooks/{id}/heartbeat` | Presence/heartbeat (`{ client }`) |
| GET    | `/notebooks/{id}/versions` | Immutable revisions (`kind`, `limit`) |
| GET    | `/notebooks/{id}/versions/{n}/download` | Download an exact revision |

`ServerStateOut`: `{ running, ready, status, pending, url }`.

Ownership is enforced on every operation; another user's notebook is reported
as `404`, indistinguishable from missing. Course staff may read revisions of a
notebook that was submitted to their course.

### Autosave and versions

`PUT /notebooks/{id}/autosave` returns:

```json
{ "version": 13, "saved": true, "sha256": "…", "saved_at": "…", "version_number": 7 }
```

Identical content is a successful no-op (`saved: false`) even with a stale
`base_version`. Changed content with a stale `base_version` returns
`409 VERSION_CONFLICT` with `details.current_version` and
`details.latest_sha256`; reload the latest version and re-apply. Autosave is
rate limited to 12 requests/minute per notebook.

## Courses and roster

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/courses` | authenticated | Courses you are enrolled in or staff |
| GET | `/courses/{course_id}` | member | Course detail |
| GET | `/courses/{course_id}/roster` | staff | Roster with progress/grade summary |
| POST | `/courses/{course_id}/enrollments` | instructor/admin | Bulk enroll/update |
| PATCH | `/courses/{course_id}/enrollments/{user_id}` | instructor/admin | Change `role_in_course` |

Course roles are `student`, `ta` and `instructor`. Non-members receive `404`;
members without the required role receive `403`. A global `admin` bypasses
course scoping.

`RosterRow`: `{ user_id, display_name, email, role_in_course, assigned,
submitted, completed, average_score, late_count, ungraded_count,
last_active_at }`.

## Assignments and rubrics

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/courses/{course_id}/assignments` | instructor/admin | Create assignment |
| GET | `/courses/{course_id}/assignments` | member | List (students see published only) |
| GET | `/assignments/{assignment_id}` | member | Detail |
| PATCH | `/assignments/{assignment_id}` | instructor/admin | Update |
| PUT | `/assignments/{assignment_id}/rubric` | instructor/admin | Upsert rubric + criteria |
| GET | `/assignments/{assignment_id}/rubric` | member | Read (students get labels/max only) |

Create assignment:

```json
{ "title": "Iris selection", "exercise_slug": "pandas-select-iris",
  "kind": "practice", "due_at": "2026-12-01T23:59:00Z",
  "max_points": 100, "weight": 1, "allow_late": true,
  "late_penalty_pct": 10, "is_published": true }
```

Rubric upsert:

```json
{ "title": "Iris rubric",
  "criteria": [
    { "key": "filter", "label": "Correct filter", "max_points": 40, "position": 1 },
    { "key": "derive", "label": "Derived column", "max_points": 40, "position": 2 },
    { "key": "style",  "label": "Readable code",  "max_points": 20, "position": 3 }
  ] }
```

A rubric that already has grades attached cannot add or remove criteria; it can
only update labels, descriptions and maxima in place.

## Submissions and grading

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/assignments/{id}/submissions` | enrolled student | Submit a notebook snapshot |
| GET | `/assignments/{id}/submissions` | staff | Review queue (`status`, `late`, `cursor`) |
| GET | `/submissions/{id}` | owner or staff | Submission detail |
| GET | `/submissions/{id}/notebook` | owner or staff | Immutable snapshot document |
| POST | `/submissions/{id}/grade` | staff | Publish a grade revision (rate limited) |
| GET | `/submissions/{id}/grades` | owner or staff | All revisions, newest first |
| GET | `/me/grades` | student | Published grades (`course_id` optional) |

Submit: `{ "notebook_id": "…" }` → `201 SubmissionOut`. Late submissions are
flagged when `allow_late` is true and rejected with `409 ASSIGNMENT_CLOSED`
otherwise. Each attempt creates a new immutable `submission` notebook version.

`GET /submissions/{id}` returns the submission, snapshot metadata, the latest
grade revision and the rubric (criterion descriptions are hidden from students).

Grade:

```json
{ "criteria": [
    { "criterion_id": "…", "points": 38, "comment": "Misses .copy()" },
    { "criterion_id": "…", "points": 40, "comment": "" },
    { "criterion_id": "…", "points": 18, "comment": "Add spacing" }
  ],
  "feedback": "Nice work overall.",
  "final_score": null }
```

Every criterion must be scored exactly once and within `[0, max_points]`.
Publishing is immediate. A regrade inserts revision 2; earlier revisions are
never overwritten. `final_score: null` uses the rubric total; a non-null value
is the TA override.

## Analytics

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/analytics/me?course_id=` | student | Personal dashboard |
| GET | `/analytics/courses/{id}?assignment_id=&from=&to=` | staff | Class dashboard |
| GET | `/analytics/courses/{id}/students/{user_id}` | staff or self | Drill-down |
| GET | `/analytics/courses/{id}/export.csv` | staff | CSV roster export |

Student dashboard: completion counts, latest/best/average scores with trend,
per-criterion mastery, idle-capped time on task, late/ungraded counts and a
per-assignment table.

Teacher dashboard: summary (students, completion rate, class average, late
rate, ungraded queue), per-assignment submitted/graded counts and score
distribution, class criterion averages, and a paginated roster. Everything is
computed on demand from the normalized tables.

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
