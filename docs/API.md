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
| POST | `/courses` | global instructor/admin | Create a class; the creator becomes its instructor |
| GET | `/courses/{course_id}` | member | Course detail (`join_code` shown to instructors only) |
| PATCH | `/courses/{course_id}` | instructor | Edit name/term/description; `status: archived` makes it read-only |
| GET | `/courses/{course_id}/roster` | staff | Roster with progress/grade summary (students) |
| GET | `/courses/{course_id}/members` | staff | Everyone in the class with their course role |
| POST | `/courses/{course_id}/members` | instructor | Add by email `{emails[], role_in_course}` → `{added, updated, unknown}` |
| POST | `/courses/{course_id}/enrollments` | instructor/admin | Bulk enroll/update |
| PATCH | `/courses/{course_id}/enrollments/{user_id}` | instructor/admin | Change `role_in_course` |
| DELETE | `/courses/{course_id}/enrollments/{user_id}` | instructor/admin | Remove a member |
| POST / DELETE | `/courses/{course_id}/join-code` | instructor | Rotate / disable the self-enrolment code |
| POST | `/courses/join` | authenticated | `{code}` → enrol as student (404 for unknown, disabled or archived) |
| GET | `/courses/{course_id}/gradebook` | staff | Students × assignments: state, score, weighted % (returned work) |

A class always keeps at least one instructor: removing or demoting the last one
returns `409 LAST_INSTRUCTOR`.

Course roles are `student`, `ta` and `instructor`. Non-members receive `404`;
members without the required role receive `403`. A global `admin` bypasses
course scoping.

`RosterRow`: `{ user_id, display_name, email, role_in_course, assigned,
submitted, completed, average_score, late_count, ungraded_count,
last_active_at }`.

## Assignments and rubrics

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/courses/{course_id}/assignments` | instructor/admin | Create assignment (adds a default "Overall" rubric) |
| GET | `/courses/{course_id}/assignments` | member | List. Students: visible only, with `my_submission`. Staff: all non-archived (`include_archived=true` for all), with `submission_count` |
| GET | `/assignments/{assignment_id}` | member | Detail |
| PATCH | `/assignments/{assignment_id}` | instructor/admin | Update (unpublishing with submissions → `409 HAS_SUBMISSIONS`) |
| DELETE | `/assignments/{assignment_id}` | instructor/admin | Delete; `409 HAS_SUBMISSIONS` if anyone submitted |
| POST | `/assignments/{assignment_id}/archive` · `/unarchive` | instructor/admin | Hide from students and dashboards, keep grades |
| POST | `/assignments/{assignment_id}/start` | enrolled student | Create/open my working copy of the starter notebook |
| PUT | `/assignments/{assignment_id}/rubric` | instructor/admin | Upsert rubric + criteria |
| GET | `/assignments/{assignment_id}/rubric` | member | Read (students get labels/max only) |

Create assignment:

```json
{ "title": "Iris selection", "exercise_slug": "pandas-select-iris",
  "kind": "practice", "due_at": "2026-12-01T23:59:00Z",
  "max_points": 100, "weight": 1, "allow_late": true,
  "late_penalty_pct": 10, "is_published": true,
  "publish_at": "2026-11-25T08:00:00Z", "topic": "Week 3",
  "starter_notebook_id": "…" }
```

A student sees an assignment when it is published, not archived and past
`publish_at`. `starter_notebook_id` is one of the instructor's notebooks; it is
snapshotted immutably and each student's copy has outputs cleared.

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
| GET | `/submissions/{id}/notebook` | owner or staff | Immutable snapshot document (`ETag`, immutable caching; `?download=1` for an attachment) |
| POST | `/submissions/{id}/grade` | staff | Save a grade revision; `release: false` keeps it a draft (rate limited) |
| POST | `/submissions/{id}/return` | staff | Return the latest draft to the student |
| POST | `/assignments/{id}/return` | staff | Return every draft for the assignment → `{returned}` |
| GET | `/submissions/{id}/grades` | owner or staff | Revisions, newest first (owners: released only) |
| GET | `/me/grades` | student | Returned grades with feedback (`course_id` optional) |

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
  "final_score": null,
  "override_reason": null,
  "release": false }
```

Every criterion must be scored exactly once and within `[0, max_points]`.
A regrade inserts a new revision; earlier revisions are never overwritten.
`final_score: null` uses the rubric total; a different value requires
`override_reason` (`409 OVERRIDE_REASON_REQUIRED`), which is stored per revision.

**Draft → return (ADR-010).** `release` defaults to `true` (publish on save, the
original behaviour). With `release: false` the revision is a staff-only draft:
students keep seeing their last returned grade and the status `submitted`/`graded`
they saw before. Returning sets `released_at`, updates the student-visible
score and sends an in-app notification. Staff `status` values are
`submitted | graded` (unreturned draft) `| returned`; the review queue accepts
`status=draft`.

## Course stream

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/courses/{id}/posts` | member | Feed: pinned first, newest first (`kind`, `cursor`, `limit`) |
| POST | `/courses/{id}/posts` | staff (instructor or TA) | Announcement or material |
| GET / PATCH / DELETE | `/posts/{id}` | member / author or instructor | Read, edit, soft-delete |
| POST | `/posts/{id}/read` | member | Mark read (idempotent) |
| GET | `/posts/{id}/readers` | staff | Read receipts: `{read[], unread[]}` |

```json
{ "kind": "material", "title": "Week 1 resources", "body": "Markdown…",
  "topic": "Week 1", "is_pinned": false, "status": "published",
  "publish_at": null,
  "attachments": [
    { "kind": "link", "target": "https://pandas.pydata.org/docs/" },
    { "kind": "dataset", "target": "iris" },
    { "kind": "lesson", "target": "intro-to-pandas" },
    { "kind": "exercise", "target": "pandas-select-iris" },
    { "kind": "assignment", "target": "<assignment id>" } ] }
```

Links must be `http(s)`. File attachments are not available yet (`422`).
Students see published posts whose `publish_at` has passed; staff also see
drafts and scheduled posts. The stream is one-way (no comments, ADR-010).

## Notifications and personal views

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/me/notifications` | authenticated | Inbox (`unread`, `cursor`, `limit`) |
| GET | `/me/notifications/count` | authenticated | `{unread}`; polled by the UI |
| POST | `/me/notifications/read` | authenticated | `{ids?}`; no ids marks all read |
| GET | `/me/home` | authenticated | Student home: due soon, latest posts, recent feedback |
| GET | `/teaching/queue` | staff | Ungraded and draft counts across my classes |

`GET /me` and the login response include
`teaching: {is_teacher, staff_course_count, student_course_count, can_create_courses}`.

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
