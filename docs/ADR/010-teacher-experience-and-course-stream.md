# ADR-010: Distinct teacher experience, grade release and a one-way course stream

**Status:** Accepted (2026-11-19)
**Amends:** ADR-009 decision 5 ("published on save")

## Context

Teachers and students shared one navigation and one set of pages. Most of the
teacher capability (assignment authoring, rubrics, submission snapshots) already
existed in the API but had no UI, so in practice a teacher could not create a
gradable assignment, could not see the notebook they were grading, and was shown
a "submit work" form that the server always rejected. Teachers also had no way
to communicate with a class.

The HLD lists "social network, chat or discussion forum" as a non-goal
(HLD.md 204-206) and PLAN.md publishes grades on save (PLAN.md 194).

## Decisions

1. **Persona from the server.** `GET /me` (and the login response) carry a
   computed `teaching` block. A user is a teacher if their global role is
   `instructor`/`admin` **or** they hold any `ta`/`instructor` enrollment: the
   seeded TA has global role `student`, so the global role alone is wrong.
   Inside a class the course role always wins. The UI routes on this; every
   endpoint still enforces course-scoped permissions on its own.
2. **Draft -> return grading (D2).** A grade revision has `released_at`; `NULL`
   is a staff-only draft. Students, `GET /me/grades`, the student dashboard and
   class analytics read **released** revisions only. `submissions.final_score`
   is the released score; the draft score lives on the revision. Submission
   status: `submitted -> graded` (unreturned draft) `-> returned`. Students keep
   the old vocabulary (`submitted`/`graded`) and never see drafts.
   `GradeRequest.release` defaults to `true` so existing API clients keep
   publish-on-save. Existing grades were backfilled as released.
3. **Override audit.** `override_reason` is stored per revision and required
   whenever `final_score` differs from the rubric total (it was previously
   accepted and discarded).
4. **Assignment lifecycle.** Default single-criterion "Overall" rubric on
   creation (no `NO_RUBRIC` dead end); scheduled release via `publish_at`
   (evaluated at query time); delete only without submissions, otherwise
   archive (`archived_at`); unpublishing graded work is refused. Optional
   immutable starter snapshot that each student copies (outputs cleared).
5. **One-way course stream (D7).** Announcements and materials with links and
   in-app references (dataset, lesson, exercise, assignment), pinning,
   scheduling and read receipts. **No comments**, to stay inside the HLD
   non-goal. File uploads are deferred (D3); the schema reserves `kind='file'`.
   TAs may post (D1); the author or an instructor edits/deletes; deletes are soft.
6. **Notifications through the outbox.** `notifications` table; fan-out is one
   batched `INSERT ... SELECT` in the job worker (`notify_post`,
   `notify_grade`), never in the request. Scheduled posts are visible on time
   (query-time check); their notifications go out on the next maintenance tick.
   The UI polls an unread count; no WebSockets.
7. **Classes and people.** Instructors create classes (D5) and become their
   instructor; join codes for self-enrolment (D4); a class always keeps at least
   one instructor; archived classes are read-only and accept no joins.
8. **Topics (D6)** are free text on assignments and materials.

## Consequences

- One additive migration (`c3d4e5f6a7b8`); rolling deploys stay safe.
- All user-supplied timestamps are normalised to UTC on write (SQLite drops
  tzinfo without converting).
- Submitted notebooks are rendered read-only in the browser; `text/html`
  outputs go into a `sandbox=""` iframe so student output can never run script
  in a grader's session.

## Alternatives considered

- **Global role only for the persona** - wrong for course-scoped TAs.
- **Separate draft table** - duplicates the revision model; a nullable
  `released_at` keeps history in one append-only table.
- **Comment threads** - rejected (HLD non-goal); revisit with a new ADR.
- **Push notifications / WebSockets** - unnecessary at this scale; polling an
  indexed count is cheap.
