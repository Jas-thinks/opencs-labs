"""On-demand analytics over the normalized grading tables.

No warehouse, no event stream, no materialized views required at the target
scale (<= 1,000 students). Queries are indexed and parameterised.
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections import defaultdict
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.analytics.schemas import (
    CompletionOut,
    CriterionMasteryOut,
    ScoresOut,
    StudentAssignmentRow,
    StudentDashboard,
    StudentDrilldown,
    SubmissionDetail,
    TeacherAssignmentRow,
    TeacherCriterionRow,
    TeacherDashboard,
    TeacherSummary,
    TimeOnTaskRow,
    TrendItem,
)
from app.core.errors import NotFound
from app.core.time import ensure_utc, now_utc, seconds_between
from app.courses.models import Course, Enrollment
from app.courses.permissions import (
    course_role,
    get_course,
    require_course_member,
    require_course_staff,
)
from app.courses.schemas import RosterRow
from app.courses.service import CourseService
from app.grading.models import (
    Assignment,
    GradeCriterionScore,
    RubricCriterion,
    Submission,
    SubmissionGrade,
)
from app.grading.service import student_status
from app.notebooks.models import NotebookSession
from app.users.models import User

SESSION_CAP_SECONDS = 2 * 60 * 60
BUCKETS = ("0-59", "60-69", "70-79", "80-89", "90-100")


def _percent(value: float, maximum: float) -> float | None:
    if maximum <= 0:
        return None
    return round((value / maximum) * 100, 1)


class AnalyticsService:
    def __init__(self, db: Session) -> None:
        self.db = db

    # -- course resolution ----------------------------------------------
    def _resolve_course(self, user: User, course_id: str | None) -> Course | None:
        if course_id:
            course = get_course(self.db, course_id)
            require_course_member(self.db, user, course.id)
            return course
        return self.db.scalar(
            select(Course)
            .join(Enrollment, Enrollment.course_id == Course.id)
            .where(Enrollment.user_id == user.id)
            .order_by(Course.created_at)
            .limit(1)
        )

    def _assignments(self, course_id: uuid.UUID) -> list[Assignment]:
        """Assignments students can currently see (published, not archived,
        past their scheduled release). Drafts never skew class analytics."""
        from app.grading.service import is_visible_to_students

        now = now_utc()
        rows = self.db.scalars(
            select(Assignment)
            .where(
                Assignment.course_id == course_id,
                Assignment.is_published.is_(True),
                Assignment.archived_at.is_(None),
            )
            .order_by(Assignment.created_at)
        )
        return [assignment for assignment in rows if is_visible_to_students(assignment, now)]

    def _latest_submissions(
        self,
        assignment_ids: list[uuid.UUID],
        *,
        user_id: uuid.UUID | None = None,
    ) -> dict[tuple[uuid.UUID, uuid.UUID], Submission]:
        if not assignment_ids:
            return {}
        stmt = select(Submission).where(Submission.assignment_id.in_(assignment_ids))
        if user_id is not None:
            stmt = stmt.where(Submission.user_id == user_id)
        latest: dict[tuple[uuid.UUID, uuid.UUID], Submission] = {}
        for submission in self.db.scalars(stmt):
            key = (submission.assignment_id, submission.user_id)
            current = latest.get(key)
            if current is None or submission.attempt_number > current.attempt_number:
                latest[key] = submission
        return latest

    def _latest_grades(self, submission_ids: list[uuid.UUID]) -> dict[uuid.UUID, SubmissionGrade]:
        if not submission_ids:
            return {}
        latest: dict[uuid.UUID, SubmissionGrade] = {}
        for grade in self.db.scalars(
            select(SubmissionGrade).where(
                SubmissionGrade.submission_id.in_(submission_ids),
                # Unreturned drafts are staff-only and must not move averages.
                SubmissionGrade.released_at.is_not(None),
            )
        ):
            current = latest.get(grade.submission_id)
            if current is None or grade.revision > current.revision:
                latest[grade.submission_id] = grade
        return latest

    def _sessions_seconds(
        self, notebook_ids: set[uuid.UUID], user_id: uuid.UUID
    ) -> int:
        if not notebook_ids:
            return 0
        sessions = self.db.scalars(
            select(NotebookSession).where(
                NotebookSession.user_id == user_id,
                NotebookSession.notebook_id.in_(notebook_ids),
            )
        )
        total = 0.0
        for session in sessions:
            end = ensure_utc(session.ended_at) or ensure_utc(session.last_seen_at)
            total += min(seconds_between(session.started_at, end), SESSION_CAP_SECONDS)
        return int(round(total))

    # -- student dashboard ----------------------------------------------
    def student_dashboard(self, user: User, course_id: str | None = None) -> StudentDashboard:
        course = self._resolve_course(user, course_id)
        if course is None:
            return StudentDashboard()
        assignments = self._assignments(course.id)
        assignment_ids = [assignment.id for assignment in assignments]
        latest = self._latest_submissions(assignment_ids, user_id=user.id)

        graded = [s for s in latest.values() if s.final_score is not None]
        scores = [float(s.final_score) for s in graded]
        latest_grades = self._latest_grades([s.id for s in graded])
        criteria = self._student_criteria(list(latest_grades.values()))

        notebook_ids = {s.notebook_id for s in latest.values()}
        total_seconds = self._sessions_seconds(notebook_ids, user.id)

        by_assignment = {assignment.id: assignment for assignment in assignments}
        rows = []
        for submission in latest.values():
            assignment = by_assignment[submission.assignment_id]
            rows.append(
                StudentAssignmentRow(
                    id=assignment.id,
                    title=assignment.title,
                    status=student_status(submission),
                    final_score=submission.final_score,
                    max_points=assignment.max_points,
                    is_late=submission.is_late,
                    due_at=assignment.due_at,
                )
            )
        for assignment in assignments:
            if assignment.id not in latest:
                rows.append(
                    StudentAssignmentRow(
                        id=assignment.id,
                        title=assignment.title,
                        status="not_started",
                        max_points=assignment.max_points,
                        due_at=assignment.due_at,
                    )
                )

        time_rows = []
        for assignment in assignments:
            assignment_notebooks = {
                s.notebook_id
                for s in latest.values()
                if s.assignment_id == assignment.id
            }
            time_rows.append(
                TimeOnTaskRow(
                    assignment_id=assignment.id,
                    title=assignment.title,
                    seconds=self._sessions_seconds(assignment_notebooks, user.id),
                )
            )

        trend = [
            TrendItem(
                assignment_id=submission.assignment_id,
                title=by_assignment[submission.assignment_id].title,
                score=submission.final_score,
                date=submission.submitted_at
                or by_assignment[submission.assignment_id].due_at,
            )
            for submission in sorted(
                (s for s in latest.values() if s.final_score is not None),
                key=lambda s: ensure_utc(s.submitted_at) or ensure_utc(s.graded_at),
            )
        ]

        return StudentDashboard(
            course_id=course.id,
            completion=CompletionOut(
                assigned=len(assignments),
                submitted=len(latest),
                graded=len(graded),
            ),
            scores=ScoresOut(
                average=round(sum(scores) / len(scores), 2) if scores else None,
                best=round(max(scores), 2) if scores else None,
                trend=trend,
            ),
            criteria=criteria,
            time_on_task_seconds=total_seconds,
            time_on_task=sorted(time_rows, key=lambda r: r.seconds, reverse=True),
            late_count=sum(1 for s in latest.values() if s.is_late),
            ungraded_count=sum(1 for s in latest.values() if s.final_score is None),
            assignments=sorted(rows, key=lambda r: r.title),
        )

    def _student_criteria(
        self, grades: list[SubmissionGrade]
    ) -> list[CriterionMasteryOut]:
        grade_ids = [grade.id for grade in grades]
        if not grade_ids:
            return []
        rows = self.db.execute(
            select(GradeCriterionScore, RubricCriterion)
            .join(RubricCriterion, RubricCriterion.id == GradeCriterionScore.criterion_id)
            .where(GradeCriterionScore.submission_grade_id.in_(grade_ids))
        ).all()
        totals: dict[tuple[str, str], dict[str, float]] = defaultdict(
            lambda: {"earned": 0.0, "max": 0.0}
        )
        for score, criterion in rows:
            bucket = totals[(criterion.key, criterion.label)]
            bucket["earned"] += float(score.points)
            bucket["max"] += float(criterion.max_points)
        return [
            CriterionMasteryOut(
                key=key,
                label=label,
                earned=round(values["earned"], 2),
                max=round(values["max"], 2),
                percent=_percent(values["earned"], values["max"]),
            )
            for (key, label), values in sorted(totals.items())
        ]

    # -- teacher dashboard ----------------------------------------------
    def teacher_dashboard(
        self,
        user: User,
        course_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
        assignment_id: str | None = None,
        date_from: dt.datetime | None = None,
        date_to: dt.datetime | None = None,
    ) -> TeacherDashboard:
        course = get_course(self.db, course_id)
        require_course_staff(self.db, user, course.id)

        student_count = int(
            self.db.scalar(
                select(func.count())
                .select_from(Enrollment)
                .where(
                    Enrollment.course_id == course.id,
                    Enrollment.role_in_course == "student",
                )
            )
            or 0
        )
        assignments = self._assignments(course.id)
        selected = assignments
        if assignment_id:
            selected = [a for a in assignments if str(a.id) == str(assignment_id)]

        latest = self._latest_submissions([a.id for a in assignments])
        if date_from is not None or date_to is not None:
            latest = {
                key: submission
                for key, submission in latest.items()
                if self._in_range(submission.submitted_at, date_from, date_to)
            }
        graded = [s for s in latest.values() if s.final_score is not None]
        scores = [float(s.final_score) for s in graded]
        latest_grades = self._latest_grades([s.id for s in graded])

        assignments_out = []
        for assignment in selected:
            subs = [
                s for s in latest.values() if s.assignment_id == assignment.id
            ]
            assignment_graded = [s for s in subs if s.final_score is not None]
            distribution = {bucket: 0 for bucket in BUCKETS}
            for submission in assignment_graded:
                pct = _percent(
                    float(submission.final_score or 0), assignment.max_points
                )
                if pct is None:
                    continue
                if pct < 60:
                    distribution["0-59"] += 1
                elif pct < 70:
                    distribution["60-69"] += 1
                elif pct < 80:
                    distribution["70-79"] += 1
                elif pct < 90:
                    distribution["80-89"] += 1
                else:
                    distribution["90-100"] += 1
            averages = [
                float(s.final_score) for s in assignment_graded if s.final_score is not None
            ]
            assignments_out.append(
                TeacherAssignmentRow(
                    id=assignment.id,
                    title=assignment.title,
                    max_points=assignment.max_points,
                    due_at=assignment.due_at,
                    submitted=len(subs),
                    graded=len(assignment_graded),
                    average_score=round(sum(averages) / len(averages), 2)
                    if averages
                    else None,
                    distribution=distribution,
                )
            )

        denominator = student_count * len(assignments)
        completion_rate = (
            round(len(latest) / denominator, 3) if denominator else 0.0
        )
        late_rate = (
            round(
                sum(1 for s in latest.values() if s.is_late) / len(latest), 3
            )
            if latest
            else 0.0
        )

        roster_data = CourseService(self.db).roster(
            user, str(course.id), limit=limit, offset=offset
        )

        return TeacherDashboard(
            course_id=course.id,
            summary=TeacherSummary(
                students=student_count,
                completion_rate=completion_rate,
                average_score=round(sum(scores) / len(scores), 2) if scores else None,
                late_rate=late_rate,
                ungraded=sum(1 for s in latest.values() if s.final_score is None),
            ),
            assignments=assignments_out,
            criteria=self._class_criteria(list(latest_grades.values())),
            roster=[RosterRow(**row) for row in roster_data["rows"]],
            roster_total=roster_data["total"],
            roster_limit=roster_data["limit"],
            roster_offset=roster_data["offset"],
        )

    @staticmethod
    def _in_range(
        value,
        date_from: dt.datetime | None,
        date_to: dt.datetime | None,
    ) -> bool:
        moment = ensure_utc(value)
        if moment is None:
            return False
        if date_from is not None and moment < ensure_utc(date_from):
            return False
        if date_to is not None and moment > ensure_utc(date_to):
            return False
        return True

    def _class_criteria(
        self, grades: list[SubmissionGrade]
    ) -> list[TeacherCriterionRow]:
        grade_ids = [grade.id for grade in grades]
        if not grade_ids:
            return []
        rows = self.db.execute(
            select(GradeCriterionScore, RubricCriterion)
            .join(RubricCriterion, RubricCriterion.id == GradeCriterionScore.criterion_id)
            .where(GradeCriterionScore.submission_grade_id.in_(grade_ids))
        ).all()
        totals: dict[tuple[str, str], dict[str, float]] = defaultdict(
            lambda: {"earned": 0.0, "max": 0.0}
        )
        for score, criterion in rows:
            bucket = totals[(criterion.key, criterion.label)]
            bucket["earned"] += float(score.points)
            bucket["max"] += float(criterion.max_points)
        return [
            TeacherCriterionRow(
                key=key,
                label=label,
                average_percent=_percent(values["earned"], values["max"]),
            )
            for (key, label), values in sorted(totals.items())
        ]

    # -- drill-down ------------------------------------------------------
    def student_drilldown(
        self, user: User, course_id: str, student_id: str
    ) -> StudentDrilldown:
        course = get_course(self.db, course_id)
        is_self = str(user.id) == str(student_id)
        if not is_self:
            require_course_staff(self.db, user, course.id)
        else:
            require_course_member(self.db, user, course.id)

        try:
            student_uuid = uuid.UUID(str(student_id))
        except (ValueError, TypeError) as exc:
            raise NotFound("student", str(student_id)) from exc
        student = self.db.get(User, student_uuid)
        if student is None:
            raise NotFound("student")
        role = course_role(self.db, student, course.id)
        if role != "student":
            raise NotFound("student")

        dashboard = self.student_dashboard(student, str(course.id))
        assignments = {a.id: a for a in self._assignments(course.id)}
        latest = self._latest_submissions(list(assignments), user_id=student.id)
        rows = []
        for submission in latest.values():
            assignment = assignments[submission.assignment_id]
            grade = self.db.scalar(
                select(SubmissionGrade)
                .where(SubmissionGrade.submission_id == submission.id)
                .order_by(SubmissionGrade.revision.desc())
                .limit(1)
            )
            rows.append(
                SubmissionDetail(
                    submission_id=submission.id,
                    assignment_id=assignment.id,
                    assignment_title=assignment.title,
                    attempt_number=submission.attempt_number,
                    status=submission.status,
                    is_late=submission.is_late,
                    final_score=submission.final_score,
                    max_points=assignment.max_points,
                    submitted_at=submission.submitted_at,
                    graded_at=submission.graded_at,
                    grade_revision=grade.revision if grade else None,
                    published_at=grade.published_at if grade else None,
                )
            )
        return StudentDrilldown(
            **dashboard.model_dump(),
            student={
                "id": student.id,
                "display_name": student.display_name,
                "email": student.email,
            },
            submissions=sorted(rows, key=lambda row: row.submitted_at, reverse=True),
        )

    # -- export ----------------------------------------------------------
    def export_rows(
        self, user: User, course_id: str, *, row_cap: int = 5000
    ) -> list[dict[str, Any]]:
        course = get_course(self.db, course_id)
        require_course_staff(self.db, user, course.id)
        roster = CourseService(self.db).roster(
            user, str(course.id), limit=row_cap, offset=0
        )
        return roster["rows"]
