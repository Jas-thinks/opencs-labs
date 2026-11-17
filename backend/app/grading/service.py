"""Assignments, rubrics, submissions and grade revisions."""

from __future__ import annotations

import re
import uuid
from typing import Any

from sqlalchemy import delete, func, select
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
from app.notebooks.service import NotebookService
from app.notebooks.versions import NotebookVersionService
from app.practice.models import Exercise
from app.users.models import User

SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(value: str) -> str:
    return SLUG_RE.sub("-", (value or "").lower()).strip("-")[:120] or "assignment"


def _uuid(value: str, resource: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError) as exc:
        raise NotFound(resource, str(value)) from exc


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

    def _assignment_out(self, assignment: Assignment, exercise_slugs: dict | None = None) -> dict:
        slugs = exercise_slugs if exercise_slugs is not None else self._exercise_slugs(
            [assignment.exercise_id] if assignment.exercise_id else []
        )
        return {
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
    def list_assignments(self, user: User, course_id: str) -> list[dict]:
        course = get_course(self.db, course_id)
        role = require_course_member(self.db, user, course.id)
        stmt = select(Assignment).where(Assignment.course_id == course.id)
        if role == "student":
            stmt = stmt.where(Assignment.is_published.is_(True))
        assignments = list(self.db.scalars(stmt.order_by(Assignment.created_at)))
        slugs = self._exercise_slugs(
            [a.exercise_id for a in assignments if a.exercise_id]
        )
        return [self._assignment_out(a, slugs) for a in assignments]

    def get_assignment(self, user: User, assignment_id: str) -> dict:
        assignment = self.get_assignment_row(assignment_id)
        role = course_role(self.db, user, assignment.course_id)
        if role is None:
            raise NotFound("assignment")
        if role == "student" and not assignment.is_published:
            raise NotFound("assignment")
        return self._assignment_out(assignment)

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
            due_at=payload.due_at,
            max_points=payload.max_points,
            weight=payload.weight,
            allow_late=payload.allow_late,
            late_penalty_pct=payload.late_penalty_pct,
            is_published=payload.is_published,
            created_by=user.id,
        )
        self.db.add(assignment)
        self.db.commit()
        self.db.refresh(assignment)
        return self._assignment_out(assignment)

    def update_assignment(self, user: User, assignment_id: str, payload) -> dict:
        assignment = self.get_assignment_row(assignment_id)
        require_course_instructor(self.db, user, assignment.course_id)
        data = payload.model_dump(exclude_unset=True)
        if "exercise_slug" in data:
            assignment.exercise_id = self._resolve_exercise(data.pop("exercise_slug"))
        desired_slug = data.pop("slug", None)
        if desired_slug and desired_slug != assignment.slug:
            assignment.slug = self._unique_slug(
                assignment.course_id, desired_slug, exclude_id=assignment.id
            )
        for field, value in data.items():
            setattr(assignment, field, value)
        self.db.commit()
        self.db.refresh(assignment)
        return self._assignment_out(assignment)

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
        if not assignment.is_published:
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
        return self._submission_out(submission, student=user, version=version)

    def _submission_out(
        self,
        submission: Submission,
        *,
        student: User | None = None,
        version=None,
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
            "status": submission.status,
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
        self._submission_access(user, submission)
        student = self.db.get(User, submission.user_id)
        version = self._version_row(submission)
        return self._submission_out(submission, student=student, version=version)

    def get_submission_detail(self, user: User, submission_id: str) -> dict:
        submission = self._load_submission(submission_id)
        self._submission_access(user, submission)
        student = self.db.get(User, submission.user_id)
        version = self._version_row(submission)
        data = self._submission_out(submission, student=student, version=version)
        rubric = self.db.scalar(
            select(Rubric).where(Rubric.assignment_id == submission.assignment_id)
        )
        data["rubric"] = self.get_rubric(user, str(submission.assignment_id)) if rubric else None
        latest = self.db.scalar(
            select(SubmissionGrade)
            .where(SubmissionGrade.submission_id == submission.id)
            .order_by(SubmissionGrade.revision.desc())
            .limit(1)
        )
        data["latest_grade"] = self._grade_out(latest) if latest is not None else None
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
        submission.final_score = final_score
        submission.status = "graded"
        submission.graded_at = now
        submission.score_source = "manual"
        enqueue(
            self.db,
            "notify_grade",
            {"submission_id": str(submission.id), "user_id": str(submission.user_id)},
        )
        self.db.commit()
        self.db.refresh(grade)
        return self._grade_out(grade, criteria)

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
            "final_score": submission.final_score if submission else None,
            "feedback": grade.feedback,
            "graded_by": grade.graded_by,
            "published_at": grade.published_at,
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
        self._submission_access(user, submission)
        grades = list(
            self.db.scalars(
                select(SubmissionGrade)
                .where(SubmissionGrade.submission_id == submission.id)
                .order_by(SubmissionGrade.revision.desc())
            )
        )
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
            latest = self.db.scalar(
                select(SubmissionGrade)
                .where(SubmissionGrade.submission_id == submission.id)
                .order_by(SubmissionGrade.revision.desc())
                .limit(1)
            )
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
                    "published_at": latest.published_at if latest else submission.graded_at,
                    "revision": latest.revision if latest else None,
                }
            )
        return results
