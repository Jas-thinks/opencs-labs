"""Assignments, rubrics, submissions and grade revisions."""

from __future__ import annotations

import re
import uuid
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.core.errors import Conflict, Forbidden, NotFound
from app.core.jobs import enqueue
from app.core.time import ensure_utc, now_utc
from app.courses.permissions import (
    course_role,
    get_course,
    require_course_instructor,
    require_course_member,
    require_course_staff,
)
from app.grading.models import (
    Assignment,
    GradeCriterionScore,
    Rubric,
    RubricCriterion,
    Submission,
    SubmissionGrade,
)
from app.notebooks.models import Notebook
from app.notebooks.service import NotebookService
from app.notebooks.versions import NotebookVersionService
from app.practice.models import Exercise, PracticeAttempt
from app.users.models import User

SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(value: str) -> str:
    return SLUG_RE.sub("-", (value or "").lower()).strip("-")[:120] or "assignment"


def _uuid(value: str, resource: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError) as exc:
        raise NotFound(resource, str(value)) from exc


STAFF_ROLES = ("admin", "ta", "instructor", "staff")


def is_visible_to_students(assignment: Assignment, now=None) -> bool:
    """Published, not archived, and past its scheduled release time."""
    if not assignment.is_published or assignment.archived_at is not None:
        return False
    publish_at = ensure_utc(assignment.publish_at)
    return publish_at is None or publish_at <= (now or now_utc())


def student_status(submission: Submission) -> str:
    """The status vocabulary students see (unchanged from before draft/return).

    'graded' once a grade has been returned; an unreturned draft is invisible,
    so the work still reads 'submitted'.
    """
    if submission.final_score is not None:
        return "graded"
    return "submitted"


def _starter_document(document: dict) -> dict:
    """A clean copy for a student: no outputs, no link to the author's notebook."""
    import copy

    clean = copy.deepcopy(document)
    for cell in clean.get("cells", []):
        if cell.get("cell_type") == "code":
            cell["outputs"] = []
            cell["execution_count"] = None
    metadata = dict(clean.get("metadata") or {})
    metadata.pop("opencs", None)
    clean["metadata"] = metadata
    return clean


class GradingService:
    def __init__(self, db: Session, notebook_service: NotebookService | None = None) -> None:
        self.db = db
        self.notebook_service = notebook_service or NotebookService(db)

    # -- lookups ---------------------------------------------------------
    def get_assignment_row(self, assignment_id: str) -> Assignment:
        assignment = self.db.get(Assignment, _uuid(assignment_id, "assignment"))
        if assignment is None:
            raise NotFound("assignment")
        return assignment

    def _exercise_slugs(self, exercise_ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
        if not exercise_ids:
            return {}
        rows = self.db.execute(
            select(Exercise.id, Exercise.slug).where(Exercise.id.in_(exercise_ids))
        ).all()
        return {exercise_id: slug for exercise_id, slug in rows}

    def _assignment_out(
        self,
        assignment: Assignment,
        exercise_slugs: dict | None = None,
        *,
        submission_count: int | None = None,
        my_submission: Submission | None = None,
    ) -> dict:
        slugs = exercise_slugs if exercise_slugs is not None else self._exercise_slugs(
            [assignment.exercise_id] if assignment.exercise_id else []
        )
        return {
            "topic": assignment.topic,
            "publish_at": assignment.publish_at,
            "archived_at": assignment.archived_at,
            "is_visible": is_visible_to_students(assignment),
            "has_starter": assignment.starter_version_id is not None,
            "submission_count": submission_count,
            "my_submission": (
                {
                    "id": my_submission.id,
                    "attempt_number": my_submission.attempt_number,
                    "status": student_status(my_submission),
                    "is_late": my_submission.is_late,
                    "final_score": my_submission.final_score,
                    "submitted_at": my_submission.submitted_at,
                }
                if my_submission is not None
                else None
            ),
            "id": assignment.id,
            "course_id": assignment.course_id,
            "exercise_id": assignment.exercise_id,
            "exercise_slug": slugs.get(assignment.exercise_id),
            "slug": assignment.slug,
            "kind": assignment.kind,
            "title": assignment.title,
            "description": assignment.description,
            "due_at": assignment.due_at,
            "max_points": assignment.max_points,
            "weight": assignment.weight,
            "allow_late": assignment.allow_late,
            "late_penalty_pct": assignment.late_penalty_pct,
            "is_published": assignment.is_published,
            "created_by": assignment.created_by,
            "created_at": assignment.created_at,
            "updated_at": assignment.updated_at,
        }

    # -- assignments -----------------------------------------------------
    def _submission_counts(self, assignment_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
        """Distinct students who submitted, per assignment."""
        if not assignment_ids:
            return {}
        rows = self.db.execute(
            select(Submission.assignment_id, func.count(func.distinct(Submission.user_id)))
            .where(Submission.assignment_id.in_(assignment_ids))
            .group_by(Submission.assignment_id)
        ).all()
        return {assignment_id: int(count) for assignment_id, count in rows}

    def _my_latest(self, user: User, assignment_ids: list[uuid.UUID]) -> dict[uuid.UUID, Submission]:
        if not assignment_ids:
            return {}
        latest: dict[uuid.UUID, Submission] = {}
        for submission in self.db.scalars(
            select(Submission).where(
                Submission.user_id == user.id, Submission.assignment_id.in_(assignment_ids)
            )
        ):
            current = latest.get(submission.assignment_id)
            if current is None or submission.attempt_number > current.attempt_number:
                latest[submission.assignment_id] = submission
        return latest

    def list_assignments(
        self, user: User, course_id: str, *, include_archived: bool = False
    ) -> list[dict]:
        course = get_course(self.db, course_id)
        role = require_course_member(self.db, user, course.id)
        stmt = select(Assignment).where(Assignment.course_id == course.id)
        if role == "student" or not include_archived:
            stmt = stmt.where(Assignment.archived_at.is_(None))
        assignments = list(self.db.scalars(stmt.order_by(Assignment.created_at)))
        slugs = self._exercise_slugs([a.exercise_id for a in assignments if a.exercise_id])
        ids = [a.id for a in assignments]
        if role == "student":
            # Scheduled release is evaluated in Python: timezone-aware
            # comparison is reliable across SQLite and PostgreSQL this way.
            now = now_utc()
            assignments = [a for a in assignments if is_visible_to_students(a, now)]
            mine = self._my_latest(user, [a.id for a in assignments])
            return [
                self._assignment_out(a, slugs, my_submission=mine.get(a.id)) for a in assignments
            ]
        counts = self._submission_counts(ids)
        return [
            self._assignment_out(a, slugs, submission_count=counts.get(a.id, 0))
            for a in assignments
        ]

    def get_assignment(self, user: User, assignment_id: str) -> dict:
        assignment = self.get_assignment_row(assignment_id)
        role = course_role(self.db, user, assignment.course_id)
        if role is None:
            raise NotFound("assignment")
        if role == "student":
            if not is_visible_to_students(assignment):
                raise NotFound("assignment")
            mine = self._my_latest(user, [assignment.id])
            return self._assignment_out(assignment, my_submission=mine.get(assignment.id))
        counts = self._submission_counts([assignment.id])
        return self._assignment_out(assignment, submission_count=counts.get(assignment.id, 0))

    def _unique_slug(self, course_id: uuid.UUID, desired: str, exclude_id=None) -> str:
        base = slugify(desired)
        candidate = base
        index = 2
        while True:
            stmt = select(Assignment.id).where(
                Assignment.course_id == course_id, Assignment.slug == candidate
            )
            if exclude_id is not None:
                stmt = stmt.where(Assignment.id != exclude_id)
            if self.db.scalar(stmt) is None:
                return candidate
            candidate = f"{base}-{index}"
            index += 1

    def _resolve_exercise(self, exercise_slug: str | None) -> uuid.UUID | None:
        if not exercise_slug:
            return None
        exercise = self.db.scalar(select(Exercise).where(Exercise.slug == exercise_slug))
        if exercise is None:
            raise NotFound("exercise", exercise_slug)
        return exercise.id

    def create_assignment(self, user: User, course_id: str, payload) -> dict:
        course = get_course(self.db, course_id)
        require_course_instructor(self.db, user, course.id)
        exercise_id = self._resolve_exercise(payload.exercise_slug)
        slug = (
            self._unique_slug(course.id, payload.slug)
            if payload.slug
            else self._unique_slug(course.id, payload.title)
        )
        assignment = Assignment(
            course_id=course.id,
            exercise_id=exercise_id,
            slug=slug,
            kind=payload.kind,
            title=payload.title,
            description=payload.description,
            due_at=ensure_utc(payload.due_at),
            max_points=payload.max_points,
            weight=payload.weight,
            allow_late=payload.allow_late,
            late_penalty_pct=payload.late_penalty_pct,
            is_published=payload.is_published,
            topic=(payload.topic or None),
            publish_at=ensure_utc(payload.publish_at),
            created_by=user.id,
        )
        if payload.starter_notebook_id is not None:
            assignment.starter_version_id = self._snapshot_starter(user, payload.starter_notebook_id)
        self.db.add(assignment)
        self.db.flush()
        # A default single-criterion rubric means a new assignment can be
        # graded immediately; the instructor can refine it until grades exist.
        rubric = Rubric(
            assignment_id=assignment.id,
            title="Overall",
            total_points=assignment.max_points,
            created_by=user.id,
        )
        self.db.add(rubric)
        self.db.flush()
        self.db.add(
            RubricCriterion(
                rubric_id=rubric.id,
                key="overall",
                label="Overall",
                description="",
                max_points=assignment.max_points,
                position=0,
            )
        )
        self.db.commit()
        self.db.refresh(assignment)
        return self._assignment_out(assignment, submission_count=0)

    def _snapshot_starter(self, user: User, notebook_id: uuid.UUID) -> uuid.UUID:
        notebook = self.notebook_service.get_owned(user, str(notebook_id))
        version, _ = self.notebook_service.snapshot_working_copy(
            user, notebook, kind="manual", actor_id=user.id, commit=False
        )
        if version is None:
            raise Conflict("STARTER_UNAVAILABLE", "The starter notebook could not be snapshotted")
        return version.id

    def _has_submissions(self, assignment_id: uuid.UUID) -> bool:
        return (
            self.db.scalar(
                select(Submission.id).where(Submission.assignment_id == assignment_id).limit(1)
            )
            is not None
        )

    def _sync_default_rubric(self, assignment: Assignment) -> None:
        """Keep the auto-created 'Overall' criterion equal to max_points until used."""
        rubric = self.db.scalar(select(Rubric).where(Rubric.assignment_id == assignment.id))
        if rubric is None:
            return
        criteria = list(
            self.db.scalars(select(RubricCriterion).where(RubricCriterion.rubric_id == rubric.id))
        )
        if len(criteria) != 1 or criteria[0].key != "overall":
            return
        used = self.db.scalar(
            select(GradeCriterionScore.id)
            .where(GradeCriterionScore.criterion_id == criteria[0].id)
            .limit(1)
        )
        if used is None:
            criteria[0].max_points = assignment.max_points
            rubric.total_points = assignment.max_points

    def update_assignment(self, user: User, assignment_id: str, payload) -> dict:
        assignment = self.get_assignment_row(assignment_id)
        require_course_instructor(self.db, user, assignment.course_id)
        data = payload.model_dump(exclude_unset=True)
        if data.get("is_published") is False and assignment.is_published:
            if self._has_submissions(assignment.id):
                raise Conflict(
                    "HAS_SUBMISSIONS",
                    "Students have already submitted work. Archive the assignment instead of unpublishing it.",
                )
        starter_id = data.pop("starter_notebook_id", None)
        if data.pop("clear_starter", False):
            assignment.starter_version_id = None
        elif starter_id is not None:
            assignment.starter_version_id = self._snapshot_starter(user, starter_id)
        if "topic" in data:
            data["topic"] = data["topic"] or None
        # Store UTC: SQLite drops tzinfo without converting.
        for field in ("due_at", "publish_at"):
            if field in data:
                data[field] = ensure_utc(data[field])
        if "exercise_slug" in data:
            assignment.exercise_id = self._resolve_exercise(data.pop("exercise_slug"))
        desired_slug = data.pop("slug", None)
        if desired_slug and desired_slug != assignment.slug:
            assignment.slug = self._unique_slug(
                assignment.course_id, desired_slug, exclude_id=assignment.id
            )
        for field, value in data.items():
            setattr(assignment, field, value)
        if "max_points" in data:
            self._sync_default_rubric(assignment)
        self.db.commit()
        self.db.refresh(assignment)
        counts = self._submission_counts([assignment.id])
        return self._assignment_out(assignment, submission_count=counts.get(assignment.id, 0))

    def delete_assignment(self, user: User, assignment_id: str) -> None:
        assignment = self.get_assignment_row(assignment_id)
        require_course_instructor(self.db, user, assignment.course_id)
        if self._has_submissions(assignment.id):
            raise Conflict(
                "HAS_SUBMISSIONS",
                "This assignment has submissions and cannot be deleted. Archive it instead.",
            )
        self.db.execute(
            update(PracticeAttempt)
            .where(PracticeAttempt.assignment_id == assignment.id)
            .values(assignment_id=None)
        )
        self.db.delete(assignment)
        self.db.commit()

    def set_archived(self, user: User, assignment_id: str, archived: bool) -> dict:
        assignment = self.get_assignment_row(assignment_id)
        require_course_instructor(self.db, user, assignment.course_id)
        assignment.archived_at = now_utc() if archived else None
        self.db.commit()
        self.db.refresh(assignment)
        counts = self._submission_counts([assignment.id])
        return self._assignment_out(assignment, submission_count=counts.get(assignment.id, 0))

    def start_assignment(self, user: User, assignment_id: str) -> dict:
        """Give a student their own working copy of the assignment notebook."""
        assignment = self.get_assignment_row(assignment_id)
        role = course_role(self.db, user, assignment.course_id)
        if role is None or not is_visible_to_students(assignment):
            raise NotFound("assignment")
        if role != "student":
            raise Forbidden("Only enrolled students start assignments")
        source_ref = f"assignment:{assignment.id}"
        existing = self.db.scalar(
            select(Notebook)
            .where(Notebook.user_id == user.id, Notebook.source_ref == source_ref)
            .order_by(Notebook.created_at.desc())
            .limit(1)
        )
        created = False
        if existing is None:
            document = None
            if assignment.starter_version_id is not None:
                _, starter = NotebookVersionService(self.db).load_version_by_id(
                    assignment.starter_version_id
                )
                document = _starter_document(starter)
            existing = self.notebook_service.create(
                user,
                title=assignment.title,
                kind="assignment",
                source_ref=source_ref,
                notebook=document,
            )
            created = True
        notebook, url = self.notebook_service.open(user, str(existing.id))
        return {"notebook_id": notebook.id, "title": notebook.title, "url": url, "created": created}

    # -- rubrics ---------------------------------------------------------
    def get_rubric(self, user: User, assignment_id: str) -> dict:
        assignment = self.get_assignment_row(assignment_id)
        role = course_role(self.db, user, assignment.course_id)
        if role is None or (role == "student" and not assignment.is_published):
            raise NotFound("assignment")
        rubric = self.db.scalar(select(Rubric).where(Rubric.assignment_id == assignment.id))
        if rubric is None:
            raise NotFound("rubric")
        criteria = list(
            self.db.scalars(
                select(RubricCriterion)
                .where(RubricCriterion.rubric_id == rubric.id)
                .order_by(RubricCriterion.position, RubricCriterion.key)
            )
        )
        hide_descriptions = role == "student"
        return {
            "id": rubric.id,
            "assignment_id": rubric.assignment_id,
            "title": rubric.title,
            "total_points": rubric.total_points,
            "criteria": [
                {
                    "id": criterion.id,
                    "key": criterion.key,
                    "label": criterion.label,
                    "description": "" if hide_descriptions else criterion.description,
                    "max_points": criterion.max_points,
                    "position": criterion.position,
                }
                for criterion in criteria
            ],
        }

    def upsert_rubric(self, user: User, assignment_id: str, payload) -> dict:
        assignment = self.get_assignment_row(assignment_id)
        require_course_instructor(self.db, user, assignment.course_id)

        keys = [criterion.key for criterion in payload.criteria]
        if len(keys) != len(set(keys)):
            raise Conflict("DUPLICATE_CRITERION_KEY", "Rubric criterion keys must be unique")

        rubric = self.db.scalar(select(Rubric).where(Rubric.assignment_id == assignment.id))
        if rubric is None:
            rubric = Rubric(
                assignment_id=assignment.id,
                title=payload.title,
                total_points=0,
                created_by=user.id,
            )
            self.db.add(rubric)
            self.db.flush()
        else:
            rubric.title = payload.title

        existing = list(
            self.db.scalars(
                select(RubricCriterion).where(RubricCriterion.rubric_id == rubric.id)
            )
        )
        existing_ids = {criterion.id for criterion in existing}
        used = 0
        if existing_ids:
            used = int(
                self.db.scalar(
                    select(func.count())
                    .select_from(GradeCriterionScore)
                    .where(GradeCriterionScore.criterion_id.in_(existing_ids))
                )
                or 0
            )

        if used:
            # Grade history references these criteria. Update in place and
            # forbid structural changes that would orphan scores.
            by_id = {criterion.id: criterion for criterion in existing}
            provided_ids = {
                criterion.id for criterion in payload.criteria if criterion.id is not None
            }
            if provided_ids != existing_ids:
                raise Conflict(
                    "RUBRIC_IN_USE",
                    "This rubric has grades attached; criteria cannot be added or removed",
                )
            for incoming in payload.criteria:
                criterion = by_id[incoming.id]
                criterion.key = incoming.key
                criterion.label = incoming.label
                criterion.description = incoming.description
                criterion.max_points = incoming.max_points
                criterion.position = incoming.position
        else:
            self.db.execute(
                delete(RubricCriterion).where(RubricCriterion.rubric_id == rubric.id)
            )
            for incoming in payload.criteria:
                self.db.add(
                    RubricCriterion(
                        rubric_id=rubric.id,
                        key=incoming.key,
                        label=incoming.label,
                        description=incoming.description,
                        max_points=incoming.max_points,
                        position=incoming.position,
                    )
                )

        self.db.flush()
        total = float(
            self.db.scalar(
                select(func.coalesce(func.sum(RubricCriterion.max_points), 0)).where(
                    RubricCriterion.rubric_id == rubric.id
                )
            )
            or 0
        )
        rubric.total_points = total
        self.db.commit()
        self.db.refresh(rubric)
        return self.get_rubric(user, str(assignment.id))

    # -- submissions -----------------------------------------------------
    def submit(self, user: User, assignment_id: str, notebook_id: uuid.UUID) -> dict:
        assignment = self.get_assignment_row(assignment_id)
        if not is_visible_to_students(assignment):
            raise NotFound("assignment")
        role = course_role(self.db, user, assignment.course_id)
        if role is None:
            raise NotFound("assignment")
        if role != "student":
            raise Forbidden("Only enrolled students can submit work")

        notebook = self.notebook_service.get_owned(user, notebook_id)

        attempt_number = int(
            self.db.scalar(
                select(func.max(Submission.attempt_number)).where(
                    Submission.assignment_id == assignment.id,
                    Submission.user_id == user.id,
                )
            )
            or 0
        ) + 1

        now = now_utc()
        due_at = ensure_utc(assignment.due_at)
        is_late = bool(due_at is not None and now > due_at)
        if is_late and not assignment.allow_late:
            raise Conflict(
                "ASSIGNMENT_CLOSED",
                "The due date has passed and late submissions are not accepted",
                details={"due_at": assignment.due_at.isoformat() if assignment.due_at else None},
            )

        version, _ = self.notebook_service.snapshot_working_copy(
            user,
            notebook,
            kind="submission",
            actor_id=user.id,
            commit=False,
        )
        submission = Submission(
            assignment_id=assignment.id,
            user_id=user.id,
            notebook_id=notebook.id,
            notebook_version_id=version.id,
            attempt_number=attempt_number,
            status="submitted",
            is_late=is_late,
            score_source="none",
            submitted_at=now,
        )
        self.db.add(submission)
        self.db.commit()
        self.db.refresh(submission)
        return self._submission_out(submission, student=user, version=version, for_owner=True)

    def _submission_out(
        self,
        submission: Submission,
        *,
        student: User | None = None,
        version=None,
        for_owner: bool = False,
    ) -> dict:
        if version is None:
            version = self._version_row(submission)
        if student is None:
            student = self.db.get(User, submission.user_id)
        return {
            "id": submission.id,
            "assignment_id": submission.assignment_id,
            "user_id": submission.user_id,
            "student": (
                {"id": student.id, "display_name": student.display_name}
                if student is not None
                else None
            ),
            "notebook_id": submission.notebook_id,
            "attempt_number": submission.attempt_number,
            "status": student_status(submission) if for_owner else submission.status,
            "has_draft": (not for_owner) and submission.status == "graded",
            "is_late": submission.is_late,
            "auto_score": submission.auto_score,
            "final_score": submission.final_score,
            "score_source": submission.score_source,
            "submitted_at": submission.submitted_at,
            "graded_at": submission.graded_at,
            "notebook_version": (
                {"version_number": version.version_number, "sha256": version.blob_sha256}
                if version is not None
                else None
            ),
        }

    def list_submissions(
        self,
        user: User,
        assignment_id: str,
        *,
        status: str | None = None,
        late: bool | None = None,
        cursor: str | None = None,
        limit: int = 50,
    ) -> dict:
        assignment = self.get_assignment_row(assignment_id)
        require_course_staff(self.db, user, assignment.course_id)
        offset = 0
        if cursor:
            try:
                offset = max(0, int(cursor))
            except ValueError as exc:
                raise Conflict("INVALID_CURSOR", "The pagination cursor is invalid") from exc
        stmt = (
            select(Submission, User)
            .join(User, User.id == Submission.user_id)
            .where(Submission.assignment_id == assignment.id)
        )
        if status == "draft":
            status = "graded"
        if status:
            stmt = stmt.where(Submission.status == status)
        if late is not None:
            stmt = stmt.where(Submission.is_late.is_(late))
        total = int(
            self.db.scalar(
                select(func.count()).select_from(Submission).where(
                    Submission.assignment_id == assignment.id,
                    *(
                        [Submission.status == status]
                        if status
                        else []
                    ),
                    *(
                        [Submission.is_late.is_(late)]
                        if late is not None
                        else []
                    ),
                )
            )
            or 0
        )
        rows = self.db.execute(
            stmt.order_by(Submission.submitted_at.desc(), Submission.id)
            .limit(limit)
            .offset(offset)
        ).all()
        next_offset = offset + len(rows)
        return {
            "submissions": [
                self._submission_out(submission, student=student) for submission, student in rows
            ],
            "next_cursor": str(next_offset) if next_offset < total else None,
        }

    def _load_submission(self, submission_id: str) -> Submission:
        submission = self.db.get(Submission, _uuid(submission_id, "submission"))
        if submission is None:
            raise NotFound("submission")
        return submission

    def _submission_access(self, user: User, submission: Submission) -> str:
        if submission.user_id == user.id:
            return "owner"
        assignment = self.db.get(Assignment, submission.assignment_id)
        if assignment is None:
            raise NotFound("submission")
        role = course_role(self.db, user, assignment.course_id)
        if role in ("admin", "ta", "instructor", "staff"):
            return "staff"
        raise NotFound("submission")

    def get_submission(self, user: User, submission_id: str) -> dict:
        submission = self._load_submission(submission_id)
        access = self._submission_access(user, submission)
        student = self.db.get(User, submission.user_id)
        version = self._version_row(submission)
        return self._submission_out(
            submission, student=student, version=version, for_owner=access == "owner"
        )

    def _latest_revision(self, submission_id: uuid.UUID, *, released_only: bool):
        stmt = select(SubmissionGrade).where(SubmissionGrade.submission_id == submission_id)
        if released_only:
            stmt = stmt.where(SubmissionGrade.released_at.is_not(None))
        return self.db.scalar(stmt.order_by(SubmissionGrade.revision.desc()).limit(1))

    def get_submission_detail(self, user: User, submission_id: str) -> dict:
        submission = self._load_submission(submission_id)
        access = self._submission_access(user, submission)
        owner = access == "owner"
        student = self.db.get(User, submission.user_id)
        version = self._version_row(submission)
        assignment = self.db.get(Assignment, submission.assignment_id)
        data = self._submission_out(submission, student=student, version=version, for_owner=owner)
        rubric = self.db.scalar(
            select(Rubric).where(Rubric.assignment_id == submission.assignment_id)
        )
        data["rubric"] = self.get_rubric(user, str(submission.assignment_id)) if rubric else None
        latest = self._latest_revision(submission.id, released_only=owner)
        data["latest_grade"] = self._grade_out(latest) if latest is not None else None
        data["assignment_title"] = assignment.title if assignment else None
        data["max_points"] = assignment.max_points if assignment else None
        data["attempts"] = [
            {
                "id": row.id,
                "attempt_number": row.attempt_number,
                "submitted_at": row.submitted_at,
                "is_late": row.is_late,
            }
            for row in self.db.scalars(
                select(Submission)
                .where(
                    Submission.assignment_id == submission.assignment_id,
                    Submission.user_id == submission.user_id,
                )
                .order_by(Submission.attempt_number)
            )
        ]
        return data

    def _version_row(self, submission: Submission):
        from app.notebooks.models import NotebookVersion

        return self.db.get(NotebookVersion, submission.notebook_version_id)

    def submission_notebook(self, user: User, submission_id: str) -> tuple[Submission, dict]:
        submission = self._load_submission(submission_id)
        self._submission_access(user, submission)
        _, document = NotebookVersionService(self.db).load_version_by_id(
            submission.notebook_version_id
        )
        return submission, document

    def submission_notebook_file(self, user: User, submission_id: str):
        """Snapshot document plus its content hash and a safe download name."""
        submission = self._load_submission(submission_id)
        self._submission_access(user, submission)
        version, document = NotebookVersionService(self.db).load_version_by_id(
            submission.notebook_version_id
        )
        student = self.db.get(User, submission.user_id)
        assignment = self.db.get(Assignment, submission.assignment_id)
        stem = "-".join(
            part
            for part in (
                slugify(student.display_name if student else "student"),
                assignment.slug if assignment else "assignment",
                f"attempt{submission.attempt_number}",
            )
            if part
        )
        return submission, document, version.blob_sha256, stem

    # -- grading ---------------------------------------------------------
    def grade(self, user: User, submission_id: str, payload) -> dict:
        submission = self._load_submission(submission_id)
        assignment = self.db.get(Assignment, submission.assignment_id)
        if assignment is None:
            raise NotFound("assignment")
        require_course_staff(self.db, user, assignment.course_id)

        rubric = self.db.scalar(select(Rubric).where(Rubric.assignment_id == assignment.id))
        if rubric is None:
            raise Conflict(
                "NO_RUBRIC",
                "Create a rubric for this assignment before grading submissions",
            )
        criteria = {
            criterion.id: criterion
            for criterion in self.db.scalars(
                select(RubricCriterion).where(RubricCriterion.rubric_id == rubric.id)
            )
        }
        provided: dict[uuid.UUID, Any] = {}
        for item in payload.criteria:
            criterion = criteria.get(item.criterion_id)
            if criterion is None:
                raise Conflict(
                    "UNKNOWN_CRITERION",
                    "The submission was graded against a criterion that is not in this rubric",
                    details={"criterion_id": str(item.criterion_id)},
                )
            if item.criterion_id in provided:
                raise Conflict(
                    "DUPLICATE_CRITERION",
                    "Each rubric criterion may only be scored once",
                )
            if item.points > criterion.max_points + 1e-9:
                raise Conflict(
                    "POINTS_OUT_OF_RANGE",
                    "Criterion points exceed the rubric maximum",
                    details={
                        "criterion_id": str(criterion.id),
                        "max_points": criterion.max_points,
                    },
                )
            provided[item.criterion_id] = item
        missing = set(criteria) - set(provided)
        if missing:
            raise Conflict(
                "INCOMPLETE_GRADING",
                "Every rubric criterion must be scored",
                details={"missing_criteria": [str(cid) for cid in missing]},
            )

        total_points = round(sum(item.points for item in provided.values()), 2)
        final_score = (
            round(float(payload.final_score), 2)
            if payload.final_score is not None
            else total_points
        )
        override_reason = (payload.override_reason or "").strip() or None
        if abs(final_score - total_points) > 1e-9 and not override_reason:
            raise Conflict(
                "OVERRIDE_REASON_REQUIRED",
                "Give a reason when the final score differs from the rubric total",
                details={"rubric_total": total_points, "final_score": final_score},
            )
        revision = int(
            self.db.scalar(
                select(func.max(SubmissionGrade.revision)).where(
                    SubmissionGrade.submission_id == submission.id
                )
            )
            or 0
        ) + 1
        now = now_utc()
        grade = SubmissionGrade(
            submission_id=submission.id,
            revision=revision,
            rubric_id=rubric.id,
            total_points=total_points,
            feedback=payload.feedback,
            graded_by=user.id,
            published_at=now,
            final_score=final_score,
            override_reason=override_reason if abs(final_score - total_points) > 1e-9 else None,
        )
        self.db.add(grade)
        self.db.flush()
        for criterion_id, item in provided.items():
            self.db.add(
                GradeCriterionScore(
                    submission_grade_id=grade.id,
                    criterion_id=criterion_id,
                    points=item.points,
                    comment=item.comment,
                )
            )
        if payload.release:
            self._release(submission, grade, now)
        else:
            # Draft: staff-only. The student keeps seeing the last returned
            # grade (submission.final_score) until this revision is returned.
            submission.status = "graded"
        self.db.commit()
        self.db.refresh(grade)
        return self._grade_out(grade, criteria)

    def _release(self, submission: Submission, grade: SubmissionGrade, now) -> None:
        grade.released_at = now
        submission.final_score = (
            grade.final_score if grade.final_score is not None else grade.total_points
        )
        submission.status = "returned"
        submission.graded_at = now
        submission.score_source = "manual"
        enqueue(
            self.db,
            "notify_grade",
            {"submission_id": str(submission.id), "user_id": str(submission.user_id)},
        )

    def return_submission(self, user: User, submission_id: str) -> dict:
        submission = self._load_submission(submission_id)
        assignment = self.db.get(Assignment, submission.assignment_id)
        if assignment is None:
            raise NotFound("assignment")
        require_course_staff(self.db, user, assignment.course_id)
        latest = self._latest_revision(submission.id, released_only=False)
        if latest is None:
            raise Conflict("NOT_GRADED", "Grade this submission before returning it")
        if latest.released_at is not None:
            raise Conflict("ALREADY_RETURNED", "The latest grade has already been returned")
        self._release(submission, latest, now_utc())
        self.db.commit()
        self.db.refresh(latest)
        return self._grade_out(latest)

    def return_all(self, user: User, assignment_id: str) -> int:
        """Return every submission whose latest revision is still a draft."""
        assignment = self.get_assignment_row(assignment_id)
        require_course_staff(self.db, user, assignment.course_id)
        now = now_utc()
        returned = 0
        for submission in self.db.scalars(
            select(Submission).where(
                Submission.assignment_id == assignment.id, Submission.status == "graded"
            )
        ):
            latest = self._latest_revision(submission.id, released_only=False)
            if latest is not None and latest.released_at is None:
                self._release(submission, latest, now)
                returned += 1
        self.db.commit()
        return returned

    def _grade_out(self, grade: SubmissionGrade, criteria: dict | None = None) -> dict:
        if criteria is None:
            criteria = {
                criterion.id: criterion
                for criterion in self.db.scalars(
                    select(RubricCriterion).where(RubricCriterion.rubric_id == grade.rubric_id)
                )
            }
        scores = list(
            self.db.scalars(
                select(GradeCriterionScore).where(
                    GradeCriterionScore.submission_grade_id == grade.id
                )
            )
        )
        submission = self.db.get(Submission, grade.submission_id)
        return {
            "id": grade.id,
            "submission_id": grade.submission_id,
            "revision": grade.revision,
            "rubric_id": grade.rubric_id,
            "total_points": grade.total_points,
            "final_score": (
                grade.final_score
                if grade.final_score is not None
                else (submission.final_score if submission else None)
            ),
            "override_reason": grade.override_reason,
            "feedback": grade.feedback,
            "graded_by": grade.graded_by,
            "published_at": grade.published_at,
            "released_at": grade.released_at,
            "state": "released" if grade.released_at is not None else "draft",
            "criteria": [
                {
                    "criterion_id": score.criterion_id,
                    "key": criteria[score.criterion_id].key
                    if score.criterion_id in criteria
                    else "",
                    "label": criteria[score.criterion_id].label
                    if score.criterion_id in criteria
                    else "",
                    "max_points": criteria[score.criterion_id].max_points
                    if score.criterion_id in criteria
                    else 0,
                    "points": score.points,
                    "comment": score.comment,
                }
                for score in scores
            ],
        }

    def list_grades(self, user: User, submission_id: str) -> list[dict]:
        submission = self._load_submission(submission_id)
        access = self._submission_access(user, submission)
        stmt = select(SubmissionGrade).where(SubmissionGrade.submission_id == submission.id)
        if access == "owner":
            stmt = stmt.where(SubmissionGrade.released_at.is_not(None))
        grades = list(self.db.scalars(stmt.order_by(SubmissionGrade.revision.desc())))
        return [self._grade_out(grade) for grade in grades]

    def my_grades(self, user: User, course_id: str | None = None) -> list[dict]:
        stmt = (
            select(Submission, Assignment)
            .join(Assignment, Assignment.id == Submission.assignment_id)
            .where(Submission.user_id == user.id)
        )
        if course_id:
            course = get_course(self.db, course_id)
            require_course_member(self.db, user, course.id)
            stmt = stmt.where(Assignment.course_id == course.id)
        rows = self.db.execute(stmt.order_by(Submission.submitted_at.desc())).all()
        results = []
        for submission, assignment in rows:
            latest = self._latest_revision(submission.id, released_only=True)
            if latest is None and submission.final_score is None:
                continue
            results.append(
                {
                    "submission_id": submission.id,
                    "assignment_id": assignment.id,
                    "assignment_title": assignment.title,
                    "course_id": assignment.course_id,
                    "attempt_number": submission.attempt_number,
                    "is_late": submission.is_late,
                    "final_score": submission.final_score,
                    "max_points": assignment.max_points,
                    "published_at": latest.released_at if latest else submission.graded_at,
                    "revision": latest.revision if latest else None,
                    "feedback": latest.feedback if latest else "",
                }
            )
        return results
