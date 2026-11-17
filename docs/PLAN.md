# PLAN.md — Student State, Grading, and Analytics Architecture for OpenCS Labs

> Status: design proposal after architecture interview.
> Scope: notebook storage, active-state autosave, manual grading, and analytics dashboards.
> Constraints confirmed by product owner:
> - **No Docker** in local development; everything runs as host processes.
> - Filesystem working copy for JupyterLab + **immutable snapshots in the existing SQL database**.
> - **Interval autosave with optimistic concurrency** (no collaborative CRDT/WebSocket editing).
> - **Rubric-based manual grading with published-on-save visibility**.
> - **Course-scoped TAs**, target ≤1,000 students / ≤200 concurrent.
> - **On-demand SQL analytics** (no warehouse/event stream).
> - **In-process background work with a DB outbox** (no Redis/Celery).

---

## 1. System architecture

```
┌──────────────────────────── Browser ────────────────────────────┐
│  React SPA (:5173)                    JupyterLab (:8888)         │
│  - learn/practice/dashboards          - edits working .ipynb     │
│  - submit, view grades                - OpenCS extension          │
│         │                                      │                 │
│         └──────────── /api/v1 (cookie) ────────┘                 │
└──────────────────────────────┬───────────────────────────────────┘
                               │ JSON / optimistic version
                    ┌──────────▼──────────┐
                    │ FastAPI monolith    │
                    │ (:8000)             │
                    │  auth · courses     │
                    │  notebooks · state  │
                    │  submissions/grades │
                    │  analytics          │
                    │  jobs (in-process)  │
                    └──────┬───────┬──────┘
                           │       │
             SQLAlchemy    │       │  filesystem (local mode)
                           │       │
                  ┌────────▼───┐   └──────────────┐
                  │ SQL DB     │   backend/data/  │
                  │ SQLite dev │   local-notebooks│
                  │ Postgres   │   /<hub_user>/   │
                  │ prod       │   *.ipynb        │
                  └────────────┘                  └──────────────┘
                     │
        ┌────────────┴─────────────────────────────┐
        │ notebook_blobs (content-addressed gzip)  │
        │ notebook_versions (immutable)            │
        │ assignments / rubrics                    │
        │ submissions / submission_grades          │
        │ grade_criterion_scores                   │
        │ notebook_sessions / jobs                 │
        └──────────────────────────────────────────┘
```

### Architectural principles

1. **Filesystem is the working copy; the DB is the system of record for history.** JupyterLab needs a real `.ipynb` on disk. Every meaningful save becomes an immutable, content-addressed version in SQL, so grading and analytics never depend on a mutable file.
2. **Content-addressed snapshots.** Identical documents deduplicate by SHA-256; a submission always points to an exact blob, so a TA grades exactly what the student submitted.
3. **No external services required locally.** Snapshots live in the SQL DB behind a `SnapshotStore` interface; an S3/MinIO adapter can be added later without changing callers. No Redis/Celery/Docker.
4. **Course-scoped authorization.** Global roles (`student|instructor|admin`) remain for identity; per-course `Enrollment.role_in_course` (`student|ta|instructor`) governs access to rosters, submissions, and grades.
5. **On-demand analytics over normalized tables** with targeted indexes and lightweight SQL views. Add rollups only if p95 exceeds the target.
6. **Everything is append-only where it matters.** Grades and submissions are revised by inserting new rows, never by overwriting history.

---

## 2. Notebook storage architecture

### 2.1 Working copy (filesystem)

- Local mode already writes `.ipynb` under `backend/data/local-notebooks/<hub_username>/<file_name>.ipynb` through `LocalNotebookBackend`.
- Hub mode continues to read/write through JupyterHub contents. The new snapshot service sits **above** the existing `NotebookBackend` protocol, so both modes share the same versioning behavior.
- File names remain server-generated and validated (`validate_file_name`); browsers never supply paths.

### 2.2 Immutable snapshots (database)

Two tables provide deduplication and history:

- `notebook_blobs` — one row per distinct document content.
  - `sha256` (PK), `size_bytes`, `encoding` (`gzip+json`), `data` (LargeBinary), `storage_kind` (`db|s3`), `storage_key` (nullable), `created_at`.
- `notebook_versions` — one row per saved revision of a notebook.
  - `notebook_id`, `version_number`, `blob_sha256`, `kind` (`autosave|checkpoint|submission|manual`), `created_by`, `created_at`.

Version numbers are monotonic per notebook (`UNIQUE (notebook_id, version_number)`). Autosaves can be pruned; **submission versions are never pruned**.

### 2.3 Notebook metadata additions

`notebooks` gains:

| Column | Type | Purpose |
|---|---|---|
| `edit_version` | Integer, default 0 | Optimistic concurrency token |
| `content_sha256` | String(64) nullable | Hash of the last saved working copy |
| `current_version_id` | UUID nullable | Latest version (denormalized pointer) |
| `last_saved_at` | DateTime nullable | Last persisted snapshot |
| `last_activity_at` | DateTime nullable | Last heartbeat/autosave |

### 2.4 Retention and size

- Autosave versions are capped per notebook (default: last **20**, configurable).
- Submission versions are retained indefinitely (or per institutional policy).
- Blobs are garbage-collected only when no `notebook_versions` row references them.
- Notebooks are typically 10 KB–1 MB; gzip + SHA dedup keeps total storage modest at ≤1,000 students.

---

## 3. Active-state management (autosave)

### 3.1 Two complementary mechanisms

**A. Authoritative local watcher (no browser dependency)**

- An in-process asyncio task started with the app (every 10 s):
  1. Find `notebook_sessions` active in the last 15 minutes.
  2. Ask the `NotebookBackend` for the working-copy mtime/hash.
  3. If the hash differs from `notebooks.content_sha256`, read the document, create an `autosave` version (dedup by SHA), and update `notebooks`.
  4. Update `last_activity_at`.
- This guarantees autosave even if the JupyterLab tab never calls the API, and it works with JupyterLab's own save cycle.

**B. Explicit API + extension heartbeat (low latency, Hub-ready)**

- `PUT /api/v1/notebooks/{id}/autosave` accepts the document from the JupyterLab extension (or SPA).
- `POST /api/v1/notebooks/{id}/heartbeat` updates the session without writing content.
- Same service used by both mechanisms; writes are idempotent by SHA.

### 3.2 Optimistic concurrency

- Client sends `base_version` (the `edit_version` it last saw).
- Server:
  - If `base_version != notebooks.edit_version` → **409 `VERSION_CONFLICT`** with `current_version` and `latest_sha256`.
  - If content hash equals `content_sha256` → **200 `saved:false`** (no new version).
  - Otherwise insert blob (if new) + version, increment `edit_version`, return the new version.
- Because the watcher and extension read the same file, most conflicts are identical-content no-ops. On a real conflict, the client reloads the latest version and re-applies.

### 3.3 Sessions and time-on-task

`notebook_sessions`:

| Column | Notes |
|---|---|
| `id` | UUID PK |
| `notebook_id`, `user_id` | FKs, indexed |
| `client` | `jupyterlab` / `web` |
| `started_at` | first heartbeat |
| `last_seen_at` | updated on autosave/heartbeat |
| `ended_at` | set by the idle closer |

- A session is closed after **5 minutes** without a heartbeat. Time-on-task sums `min(last_seen - started, cap)` and ignores idle gaps, preventing inflated study time.
- JupyterLab's autosave interval is set to **30 s** via its settings/extension; the heartbeat is every 30 s.

### 3.4 JupyterLab integration details

- The existing extension already calls the API with `credentials: 'include'` and `apiBase()`.
- Extend it to:
  - Read `opencs.notebook_id`, `opencs.state_version`, and `opencs.api_base` from notebook metadata.
  - On document save/change (debounced), call the autosave endpoint; on 409, refresh `state_version`.
  - Send a heartbeat every 30 s while the notebook is open.
- Local mode uses `http://localhost:8888` for JupyterLab (not `127.0.0.1`) so the `localhost` session cookie applies; add `http://localhost:8888` to CORS with credentials.
- Notebook metadata carries only the public API base and IDs — no secrets.

---

## 4. Manual grading workflow

### 4.1 Course assignments

Add an `Assignment` that links a course to an exercise (or a free-form project):

- `course_id`, optional `exercise_id`, `kind` (`practice|project|exam`), `title`, `description`.
- `due_at`, `max_points`, `weight`, `allow_late`, `late_penalty_pct`, `is_published`, `created_by`.

This closes the current gap where exercises are global and attempts have no course context. Attempts and submissions now reference an assignment.

### 4.2 Rubrics

- `rubrics` (one per assignment; optional reuse later).
- `rubric_criteria` (key, label, description, max_points, position).
- Total points = sum of criteria maxima; validation enforces `0 ≤ points ≤ max_points`.

### 4.3 Submissions

- Student clicks **Submit** in the SPA (or extension).
- Server reads the current working copy, creates a `notebook_versions` row with `kind=submission` (blob reused if identical), and creates a `Submission`:
  - `assignment_id`, `user_id`, `notebook_id`, `notebook_version_id`.
  - `attempt_number`, `submitted_at`, `is_late`, `status` (`submitted|graded|returned`).
  - `auto_score` (if automated checks ran), `final_score`, `score_source` (`auto|manual|none`).
- Resubmission until the due date creates a new attempt; after the due date submissions are accepted only if `allow_late`, flagged late.

### 4.4 Grade publication

- `submission_grades` stores each grading revision:
  - `submission_id`, `revision`, `rubric_id`, `total_points`, `feedback`, `graded_by`, `published_at`.
- `grade_criterion_scores` stores per-criterion points and comments, enabling rubric analytics.
- Grades are **published immediately on save**; a correction creates a new revision. The latest revision is what students and dashboards read.
- Manual grading coexists with automated checks: `auto_score` is retained, `final_score`/`score_source` record the TA override. A TA may accept or override the automated mark.

### 4.5 Permission matrix

| Action | Student | Course TA | Course Instructor | Admin |
|---|---|---|---|---|
| View own submissions/grades | ✅ | ✅ | ✅ | ✅ |
| Submit / resubmit until due | ✅ | — | — | — |
| View course roster | — | ✅ | ✅ | ✅ |
| View all submissions in course | — | ✅ | ✅ | ✅ |
| Create/edit assignments & rubrics | — | — | ✅ | ✅ |
| Grade / regrade submissions | — | ✅ | ✅ | ✅ |
| View course analytics | — | ✅ | ✅ | ✅ |
| View any student drill-down | — | ✅ | ✅ | ✅ |
| Manage enrollments/roles | — | — | ✅ | ✅ |

Course staff are resolved from `Enrollment.role_in_course`; a global `admin` bypasses course scoping. Students receive 404 (not 403) for resources they do not own, preserving the existing non-disclosure behavior.

---

## 5. Analytics and dashboards data model

### 5.1 Source-of-truth tables

No separate analytics store. Dashboards query:

- `assignments`, `enrollments`, `submissions`, `submission_grades`, `grade_criterion_scores`.
- `practice_attempts` (automated results, linked to assignments).
- `notebook_sessions` (time-on-task; idle capped).
- `lesson_progress` and `notebooks` (learning activity).

### 5.2 SQL views (not materialized)

Create ordinary views in the migration for reuse and testability:

- `v_latest_submission` — per `(assignment_id, user_id)`, highest `attempt_number`.
- `v_latest_grade` — per `submission_id`, highest `revision`.
- `v_student_assignment` — student × assignment with status, score, late, graded_at.
- `v_criterion_mastery` — per student/criterion, earned vs max points.

Indexes (critical for on-demand queries):

- `submissions (assignment_id, user_id)`, `(assignment_id, status)`, `(user_id, submitted_at)`.
- `submission_grades (submission_id, revision DESC)`.
- `grade_criterion_scores (criterion_id)`.
- `enrollments (course_id, role_in_course)`.
- `notebook_sessions (user_id, started_at)`, `(notebook_id, last_seen_at)`.
- `notebook_versions (notebook_id, version_number)`, `(kind)`.

### 5.3 Student dashboard

`GET /api/v1/analytics/me?course_id=` returns:

- Completion: assigned vs submitted vs graded.
- Scores: latest/final per assignment, average, best, trend ordered by due/submitted date.
- Rubric mastery: average earned/max per criterion.
- Time-on-task: total and per assignment (idle-capped).
- Late count and ungraded submissions.

### 5.4 Teacher dashboard

`GET /api/v1/analytics/courses/{course_id}` returns:

- Summary: student count, completion rate, class average, late rate, ungraded queue size.
- Per-assignment: submitted/graded counts, average, score distribution buckets (0–59, 60–69, …).
- Per-criterion class averages.
- Roster rows: student, completion, average, late count, ungraded count, last active.
- Filters: `assignment_id`, date range; pagination for the roster.

### 5.5 Drill-down

`GET /api/v1/analytics/courses/{course_id}/students/{user_id}` returns the student dashboard shape for that student, plus per-assignment submission/grade detail. Staff only (or self).

### 5.6 Freshness and performance

- Grades are visible immediately because queries read the latest committed revision.
- On-demand SQL is sufficient for ≤1,000 students. If p95 exceeds ~300 ms:
  - Add daily rollup tables populated by the job worker (Phase 6), behind the same API contract.
- CSV export streams from the same query with a row cap and `text/csv`.

---

## 6. Database schema (new/changed)

### 6.1 New tables

```sql
-- Content-addressed notebook documents
notebook_blobs (
  sha256        VARCHAR(64) PRIMARY KEY,
  size_bytes    BIGINT NOT NULL,
  encoding      VARCHAR(16) NOT NULL DEFAULT 'gzip+json',
  data          BLOB NULL,                 -- NULL when storage_kind='s3'
  storage_kind  VARCHAR(16) NOT NULL DEFAULT 'db',
  storage_key   VARCHAR(512) NULL,
  created_at    TIMESTAMP NOT NULL
);

-- Immutable notebook revisions
notebook_versions (
  id              UUID PRIMARY KEY,
  notebook_id     UUID NOT NULL REFERENCES notebooks(id) ON DELETE CASCADE,
  version_number  INTEGER NOT NULL,
  blob_sha256     VARCHAR(64) NOT NULL REFERENCES notebook_blobs(sha256),
  kind            VARCHAR(16) NOT NULL,    -- autosave|checkpoint|submission|manual
  created_by      UUID NULL REFERENCES users(id) ON DELETE SET NULL,
  created_at      TIMESTAMP NOT NULL,
  UNIQUE (notebook_id, version_number)
);

-- Presence / time-on-task
notebook_sessions (
  id            UUID PRIMARY KEY,
  notebook_id   UUID NOT NULL REFERENCES notebooks(id) ON DELETE CASCADE,
  user_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  client        VARCHAR(20) NOT NULL DEFAULT 'jupyterlab',
  started_at    TIMESTAMP NOT NULL,
  last_seen_at  TIMESTAMP NOT NULL,
  ended_at      TIMESTAMP NULL
);

-- Course work definition
assignments (
  id                UUID PRIMARY KEY,
  course_id         UUID NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
  exercise_id       UUID NULL REFERENCES exercises(id) ON DELETE SET NULL,
  slug              VARCHAR(120) NOT NULL,
  kind              VARCHAR(20) NOT NULL DEFAULT 'practice',
  title             VARCHAR(240) NOT NULL,
  description       VARCHAR(2000) NOT NULL DEFAULT '',
  due_at            TIMESTAMP NULL,
  max_points        DOUBLE PRECISION NOT NULL DEFAULT 100,
  weight            DOUBLE PRECISION NOT NULL DEFAULT 1,
  allow_late        BOOLEAN NOT NULL DEFAULT TRUE,
  late_penalty_pct  INTEGER NOT NULL DEFAULT 0,
  is_published      BOOLEAN NOT NULL DEFAULT FALSE,
  created_by        UUID NOT NULL REFERENCES users(id),
  created_at        TIMESTAMP NOT NULL,
  updated_at        TIMESTAMP NOT NULL,
  UNIQUE (course_id, slug)
);

rubrics (
  id            UUID PRIMARY KEY,
  assignment_id UUID NOT NULL UNIQUE REFERENCES assignments(id) ON DELETE CASCADE,
  title         VARCHAR(200) NOT NULL,
  total_points  DOUBLE PRECISION NOT NULL DEFAULT 0,
  created_by    UUID NOT NULL REFERENCES users(id),
  created_at    TIMESTAMP NOT NULL,
  updated_at    TIMESTAMP NOT NULL
);

rubric_criteria (
  id          UUID PRIMARY KEY,
  rubric_id   UUID NOT NULL REFERENCES rubrics(id) ON DELETE CASCADE,
  key         VARCHAR(60) NOT NULL,
  label       VARCHAR(200) NOT NULL,
  description VARCHAR(1000) NOT NULL DEFAULT '',
  max_points  DOUBLE PRECISION NOT NULL,
  position    INTEGER NOT NULL DEFAULT 0,
  UNIQUE (rubric_id, key)
);

submissions (
  id                  UUID PRIMARY KEY,
  assignment_id       UUID NOT NULL REFERENCES assignments(id) ON DELETE CASCADE,
  user_id             UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  notebook_id         UUID NOT NULL REFERENCES notebooks(id),
  notebook_version_id UUID NOT NULL REFERENCES notebook_versions(id),
  attempt_number      INTEGER NOT NULL DEFAULT 1,
  status              VARCHAR(20) NOT NULL DEFAULT 'submitted',
  is_late             BOOLEAN NOT NULL DEFAULT FALSE,
  auto_score          DOUBLE PRECISION NULL,
  final_score         DOUBLE PRECISION NULL,
  score_source        VARCHAR(16) NOT NULL DEFAULT 'none',
  submitted_at        TIMESTAMP NOT NULL,
  graded_at           TIMESTAMP NULL,
  UNIQUE (assignment_id, user_id, attempt_number)
);

submission_grades (
  id            UUID PRIMARY KEY,
  submission_id UUID NOT NULL REFERENCES submissions(id) ON DELETE CASCADE,
  revision      INTEGER NOT NULL,
  rubric_id     UUID NOT NULL REFERENCES rubrics(id),
  total_points  DOUBLE PRECISION NOT NULL,
  feedback      TEXT NOT NULL DEFAULT '',
  graded_by     UUID NOT NULL REFERENCES users(id),
  published_at  TIMESTAMP NOT NULL,
  UNIQUE (submission_id, revision)
);

grade_criterion_scores (
  id                  UUID PRIMARY KEY,
  submission_grade_id UUID NOT NULL REFERENCES submission_grades(id) ON DELETE CASCADE,
  criterion_id        UUID NOT NULL REFERENCES rubric_criteria(id),
  points              DOUBLE PRECISION NOT NULL,
  comment             TEXT NOT NULL DEFAULT '',
  UNIQUE (submission_grade_id, criterion_id)
);

jobs (
  id          UUID PRIMARY KEY,
  kind        VARCHAR(40) NOT NULL,
  payload     JSON NOT NULL,
  status      VARCHAR(16) NOT NULL DEFAULT 'pending',
  attempts    INTEGER NOT NULL DEFAULT 0,
  run_at      TIMESTAMP NOT NULL,
  locked_at   TIMESTAMP NULL,
  last_error  TEXT NULL,
  created_at  TIMESTAMP NOT NULL
);
```

### 6.2 Changes to existing tables

- `notebooks`: add `edit_version`, `content_sha256`, `current_version_id`, `last_saved_at`, `last_activity_at`.
- `practice_attempts`: add `assignment_id` (nullable FK, indexed) to attach automated results to course work. Optionally add `submission_id` if attempts are the primary submission path.
- `enrollments.role_in_course`: enforce `student|ta|instructor` in the service/schema layer (existing string column; no migration required).

### 6.3 Circular references

`notebooks.current_version_id` and `notebooks → notebook_versions → notebooks` form a cycle. Add the FK with `use_alter=True` in SQLAlchemy/Alembic, or omit the FK and validate in the service. Recommended: keep it as a plain UUID column with an index, updated transactionally.

---

## 7. API contracts

All endpoints are under `/api/v1`, use the existing session cookie/bearer auth, and return the existing structured error envelope: `{"error": {"code", "message", "details"}}`.

### 7.1 Notebook state

#### `PUT /notebooks/{notebook_id}/autosave` — owner
```json
Request:  { "base_version": 12, "document": { ...ipynb... } }
200:      { "version": 13, "saved": true, "sha256": "…", "saved_at": "2026-…" }
200:      { "version": 12, "saved": false, "sha256": "…" }        // unchanged
409:      { "error": { "code": "VERSION_CONFLICT",
                      "details": { "current_version": 13, "latest_sha256": "…" } } }
```
- Rate-limited (default 12/min/notebook).
- Rejects documents that are not valid `.ipynb` JSON.

#### `POST /notebooks/{notebook_id}/heartbeat` — owner
```json
200: { "version": 13, "last_saved_at": "…", "session_id": "…" }
```

#### `GET /notebooks/{notebook_id}/versions?kind=submission&limit=50` — owner or course staff (if referenced by a submission)
```json
200: { "versions": [ { "version_number": 7, "kind": "submission",
                       "sha256": "…", "size_bytes": 12345, "created_at": "…" } ] }
```

#### `GET /notebooks/{notebook_id}/versions/{version}/download` — owner or course staff
Returns `application/x-ipynb+json` with the exact blob bytes.

### 7.2 Courses and roster

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/courses` | authenticated | Courses the user is enrolled in / staffs |
| GET | `/courses/{course_id}` | member | Course detail |
| GET | `/courses/{course_id}/roster` | staff | Roster with progress/grade summary |
| POST | `/courses/{course_id}/enrollments` | instructor/admin | Bulk enroll/update |
| PATCH | `/courses/{course_id}/enrollments/{user_id}` | instructor/admin | Change `role_in_course` |

Roster row:
```json
{ "user_id": "…", "display_name": "…", "email": "…", "role_in_course": "student",
  "completed": 4, "assigned": 6, "average_score": 82.5,
  "late_count": 1, "ungraded_count": 0, "last_active_at": "…" }
```

### 7.3 Assignments and rubrics

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/courses/{course_id}/assignments` | instructor/admin | Create assignment |
| GET | `/courses/{course_id}/assignments` | member | List assignments |
| GET | `/assignments/{assignment_id}` | member | Detail (students see due date, max points; not rubric hidden answers) |
| PATCH | `/assignments/{assignment_id}` | instructor/admin | Update |
| PUT | `/assignments/{assignment_id}/rubric` | instructor/admin | Upsert rubric + criteria |
| GET | `/assignments/{assignment_id}/rubric` | staff; students get criteria labels/max only | Read rubric |

Create assignment:
```json
{ "title": "Iris selection", "exercise_slug": "pandas-select-iris",
  "kind": "practice", "due_at": "2026-12-01T23:59:00Z",
  "max_points": 100, "weight": 1, "allow_late": true, "late_penalty_pct": 10 }
```

Rubric upsert:
```json
{ "title": "Iris rubric",
  "criteria": [
    { "key": "filter",  "label": "Correct filter", "max_points": 40, "position": 1 },
    { "key": "derive",  "label": "Derived column", "max_points": 40, "position": 2 },
    { "key": "style",   "label": "Readable code",  "max_points": 20, "position": 3 }
  ] }
```

### 7.4 Submissions and grading

#### `POST /assignments/{assignment_id}/submissions` — enrolled student
```json
Request:  { "notebook_id": "…" }
201:      { "id": "…", "attempt_number": 1, "status": "submitted",
          "is_late": false, "submitted_at": "…",
          "notebook_version": { "version_number": 9, "sha256": "…" } }
409:      ASSIGNMENT_CLOSED (late not allowed)
```

#### `GET /assignments/{assignment_id}/submissions?status=submitted&late=false&cursor=…` — staff
```json
200: { "submissions": [ { "id": "…", "student": { "id", "display_name" },
                          "attempt_number", "submitted_at", "is_late",
                          "status", "auto_score", "final_score" } ],
       "next_cursor": null }
```

#### `GET /submissions/{submission_id}` — owner or staff
Returns submission, snapshot metadata, automated score, latest grade, rubric.

#### `GET /submissions/{submission_id}/notebook` — owner or staff
Returns the immutable snapshot document (`application/json`).

#### `POST /submissions/{submission_id}/grade` — staff
```json
Request: {
  "criteria": [
    { "criterion_id": "…", "points": 38, "comment": "Good filter, misses .copy()" },
    { "criterion_id": "…", "points": 40, "comment": "" },
    { "criterion_id": "…", "points": 18, "comment": "Add spacing" }
  ],
  "feedback": "Nice work overall.",
  "final_score": null,          // optional TA override; null = weighted rubric total
  "override_reason": null
}
200: { "revision": 1, "total_points": 96, "final_score": 96,
       "published_at": "…", "graded_by": "…" }
```
- Rejects points outside `[0, max_points]` and unknown criteria.
- Publishing is immediate; a regrade creates revision 2, etc.

#### `GET /submissions/{submission_id}/grades` — owner or staff
Returns all revisions, newest first.

#### `GET /me/grades?course_id=…` — student
Returns published grades for the student's submissions.

### 7.5 Analytics

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/analytics/me?course_id=` | student | Personal dashboard |
| GET | `/analytics/courses/{course_id}?assignment_id=&from=&to=` | staff | Class dashboard |
| GET | `/analytics/courses/{course_id}/students/{user_id}` | staff or self | Drill-down |
| GET | `/analytics/courses/{course_id}/export.csv` | staff | CSV export |

Student response shape:
```json
{ "course_id": "…",
  "completion": { "assigned": 6, "submitted": 5, "graded": 4 },
  "scores": { "average": 82.5, "best": 96, "trend": [ { "assignment_id", "title", "score", "date" } ] },
  "criteria": [ { "key": "filter", "label": "Correct filter", "earned": 34, "max": 40, "percent": 85 } ],
  "time_on_task_seconds": 5400,
  "late_count": 1,
  "assignments": [ { "id", "title", "status", "final_score", "max_points", "is_late" } ] }
```

Teacher response shape:
```json
{ "course_id": "…",
  "summary": { "students": 120, "completion_rate": 0.83, "average_score": 78.4,
               "late_rate": 0.12, "ungraded": 7 },
  "assignments": [ { "id", "title", "submitted": 110, "graded": 103,
                     "average_score": 79.1,
                     "distribution": { "0-59": 5, "60-69": 12, "70-79": 30,
                                       "80-89": 41, "90-100": 22 } } ],
  "criteria": [ { "key", "label", "average_percent" } ],
  "roster": [ /* roster rows */ ] }
```

---

## 8. Background jobs and outbox

`jobs` rows are inserted in the same transaction as the business change, then processed by an in-process worker started on app startup:

- **Claim**: `UPDATE jobs SET status='running', locked_at=now() WHERE id = (SELECT id … status='pending' AND run_at<=now() ORDER BY run_at LIMIT 1) RETURNING *` (SQLite: short transaction with `BEGIN IMMEDIATE`).
- **Retry**: exponential backoff, max attempts, `last_error` recorded; stuck `running` jobs reclaimed after 10 minutes.
- **Job kinds**:
  - `prune_autosaves` — keep the newest N autosave versions per notebook; never touch `submission`.
  - `close_idle_sessions` — close sessions with `last_seen_at < now() - 5 min`.
  - `notify_grade` — insert an in-app notification row (or send email later).
  - `recompute_rollups` — optional, only if the dashboard latency target is missed.
- FastAPI `BackgroundTasks` may enqueue, but the DB worker is the reliable path (survives restarts).

---

## 9. Step-by-step implementation plan

### Phase 0 — Documentation
1. Save this document as `docs/PLAN.md`.
2. Add an ADR (`docs/ADR/009-notebook-state-and-manual-grading.md`) recording the decisions: DB snapshots, optimistic autosave, course-scoped TAs, on-demand analytics, no external queue.

### Phase 1 — Schema and domain models
1. Add Alembic migration with all new tables, columns, constraints, indexes, and SQL views.
2. Add SQLAlchemy models:
   - `app/grading/models.py` — Assignment, Rubric, RubricCriterion, Submission, SubmissionGrade, GradeCriterionScore.
   - `app/notebooks/models.py` — NotebookBlob, NotebookVersion, NotebookSession (+ new Notebook columns).
   - `app/core/jobs.py` — Job model/worker.
3. Update `Notebook`, `PracticeAttempt` relationships.
4. Add seed data: a course, an enrollment per demo user, one assignment, a default rubric.

### Phase 2 — Snapshot storage and active state
1. `app/notebooks/snapshots.py`: `SnapshotStore` protocol + `DbSnapshotStore` (zlib+gzip JSON, SHA-256, dedup). Optional `S3SnapshotStore` later.
2. `NotebookVersionService`: `create_version(notebook, document, kind, actor)`, `list_versions`, `load_version`, `prune_autosaves`.
3. Extend `NotebookService` with `snapshot_working_copy()`, reading via the existing `NotebookBackend`.
4. Autosave + heartbeat endpoints/services with optimistic locking and rate limits.
5. Start the watcher task in `app/main.py`: poll active sessions, snapshot changed files.
6. Configure local JupyterLab autosave to 30 s; pass `opencs.notebook_id`/`api_base` in notebook metadata; add `http://localhost:8888` to CORS.
7. Extend the JupyterLab extension: save observer + heartbeat.
8. Tests: dedup, conflict 409, unchanged no-op, pruning, ownership, watcher.

### Phase 3 — Courses, assignments, rubrics
1. Add `app/courses/router.py` (list/detail/roster/enrollments) + service.
2. Add assignment/rubric CRUD under `app/grading/router.py` with instructor-only guards.
3. Permission dependencies: `require_course_member`, `require_course_staff`, `require_course_instructor`.
4. Extend `GET /me/courses` / frontend types to include `role_in_course`.

### Phase 4 — Submissions and manual grading
1. `Submit` service: read working copy → create submission version → create Submission with attempt/late logic.
2. Review queue + submission detail + snapshot download endpoints.
3. Grade endpoint: validate rubric, insert `submission_grades` + `grade_criterion_scores`, update `submissions.final_score/status`, enqueue `notify_grade`.
4. Student grade endpoints (`/me/grades`, per submission).
5. Frontend: Submit button + status, instructor grading screen, student grade view.
6. Tests: permissions matrix, late policy, immutability, revision history, immediate visibility.

### Phase 5 — Analytics
1. Add SQL views in migration; add `app/analytics/service.py` with parameterized aggregate queries.
2. Implement `/analytics/me`, `/analytics/courses/{id}`, drill-down, CSV export.
3. Frontend: student dashboard cards/trend/rubric mastery; teacher dashboard summary, distributions, roster table with drill-down.
4. Tests: seed a known dataset and assert exact aggregates; permission isolation; empty-data states.

### Phase 6 — Jobs, retention, notifications
1. Implement the DB outbox worker and register it on startup.
2. Job handlers: prune autosaves, close idle sessions, notify grade, optional rollups.
3. Add retention settings and cleanup tests.
4. Optional: in-app notification table + UI badge.

### Phase 7 — Hardening
1. Rate-limit autosave/grade; cap document size; validate notebook JSON.
2. `EXPLAIN` the dashboard queries; add indexes if needed.
3. Load test 200 concurrent autosaves + 1k-student aggregates.
4. Backup/restore drill: SQLite/Postgres dump includes blobs.
5. Update `docs/API.md` and `docs/SECURITY.md`.

---

## 10. Testing strategy

- **Unit**: snapshot dedup/SHA, version conflict, late computation, rubric validation, permission matrix, analytics math.
- **Integration (FastAPI TestClient)**: student submits → TA grades → student sees grade; roster and dashboards reflect it; cross-course access denied; snapshot remains unchanged after a regrade.
- **Autosave**: concurrent PUTs with stale `base_version` → 409; unchanged document → no new version; watcher creates a version from an out-of-band file change.
- **Analytics**: fixed fixture (2 courses, N students, mixed late/graded) with asserted counts, averages, distributions.
- **Performance**: 1,000 students × 20 assignments (~20k submissions) seeded; dashboard p95 target < 300 ms.
- **Security**: TA cannot create assignments/change rubrics; students get 404 for others' submissions; CSV export restricted.

---

## 11. Risks and mitigations

| Risk | Mitigation |
|---|---|
| SQLite `JSON`/`BLOB` semantics differ from Postgres | Use SQLAlchemy `JSON` + `LargeBinary`; test both backends; Alembic renders per-dialect types. |
| Autosave volume bloats storage | SHA dedup + cap autosave versions (20) + prune job; submissions retained. |
| Watcher vs extension conflicts | Idempotent by SHA; 409 with latest version; client refreshes. |
| JupyterLab cookie/CORS in local mode | Use `localhost:8888`, add it to CORS with credentials, carry `api_base` in notebook metadata. |
| DB grows with blobs | Monitor; `SnapshotStore` interface allows moving blobs to S3/object storage without changing versions/APIs. |
| Dashboard latency at upper scale | Indexed on-demand queries; optional nightly rollups behind the same API. |
| Course scoping bugs leak data | Central permission dependencies; integration tests for every role/course combination. |
| Grade disputes | Immutable submissions + append-only grade revisions with grader/timestamp. |

---

## 12. Decisions recorded from the interview

| Topic | Decision |
|---|---|
| Docker | Not used locally; host processes only |
| Snapshot storage | SQL DB, content-addressed gzip blobs; FS working copy |
| Autosave | Interval HTTP (15–30 s) with optimistic `base_version`; watcher backstop |
| Manual grading | Rubric criteria + points + comments; automated score retained, TA override |
| Submission policy | Resubmit until due; late flagged; configurable penalty |
| Grade visibility | Published immediately on save; revisions for corrections |
| Course model | Assignments link course → exercise with due date/max points/rubric |
| TA scope | Per-course (`role_in_course`), instructor creates assignments/rubrics |
| Analytics | On-demand SQL over normalized tables + views |
| Background work | In-process worker + DB outbox; no Redis/Celery |
| Scale target | ≤1,000 students, ≤200 concurrent |
