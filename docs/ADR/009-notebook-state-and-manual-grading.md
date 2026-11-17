# ADR-009: Notebook state, manual grading and analytics

**Status:** Accepted

## Context

Students edit notebooks in JupyterLab while the web app needs a durable record
for grading, resubmission and analytics. The working `.ipynb` file is mutable
and lives on a per-user filesystem or inside JupyterHub; grading and dashboards
must not depend on it. The deployment must also stay simple: no Docker locally,
no Redis/Celery, and a target of ~1,000 students with ~200 concurrent sessions.

## Decision

1. **Filesystem is the working copy; SQL is the system of record.** The
   existing `NotebookBackend` still reads/writes `.ipynb` files. A snapshot
   service sits above it and stores every meaningful save as an immutable
   version.
2. **Content-addressed snapshots.** Documents are canonicalised to compact,
   key-sorted JSON, SHA-256 hashed and gzip-compressed into `notebook_blobs`.
   Identical documents deduplicate. `notebook_versions` rows are immutable;
   submission versions are never pruned.
3. **Interval autosave with optimistic concurrency.** The JupyterLab extension
   sends `PUT /notebooks/{id}/autosave` with a `base_version`. A stale version
   with changed content returns `409 VERSION_CONFLICT`; identical content is a
   successful no-op. An in-process watcher polls active sessions and snapshots
   out-of-band file changes as a backstop.
4. **Course-scoped roles.** Global roles identify a person. Per-course
   `Enrollment.role_in_course` (`student|ta|instructor`) governs rosters,
   submissions, grading and analytics. Non-members receive `404` rather than
   leaking course existence.
5. **Rubric-based manual grading, published on save.** `submission_grades` and
   `grade_criterion_scores` are append-only. A correction inserts a new
   revision; the latest revision is what students and dashboards read.
   Automated scores are retained and a TA may override them.
6. **On-demand SQL analytics.** Dashboards query the normalized tables with
   targeted indexes and four reporting views. No warehouse or event stream.
   Rollups can be added later behind the same API contract.
7. **DB outbox + in-process worker.** Jobs (`prune_autosaves`,
   `close_idle_sessions`, `notify_grade`) are inserted in the business
   transaction and processed by an asyncio task with retry/backoff. No
   external broker.

## Consequences

**Positive**

- Grading is reproducible: a submission points at an exact, immutable blob.
- Storage stays modest at the target scale through SHA deduplication and
  autosave retention.
- The stack remains two processes (FastAPI + JupyterLab) plus a database.
- Grade history and resubmissions are auditable by construction.

**Negative / costs**

- Two save paths (extension and watcher) must stay idempotent by content hash.
- Autosave adds database writes; retention and pruning are required.
- Analytics queries must be indexed and measured as the dataset grows.

## Alternatives considered

- **Only the mutable file, no snapshots.** Rejected: a student edit after the
  due date would change what a TA grades.
- **Collaborative CRDT editing / WebSockets.** Rejected for this scope; the
  interval-plus-optimistic-lock model is simpler and sufficient.
- **Redis/Celery.** Rejected: another service to operate and no local Docker.
- **Materialized analytics store.** Rejected: on-demand SQL meets the latency
  target at <= 1,000 students; rollups remain an escape hatch.
