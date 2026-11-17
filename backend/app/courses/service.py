"""Course catalogue, rosters and enrollment management."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import NotFound
from app.courses.models import Course, Enrollment
from app.courses.permissions import (
    get_course,
    require_course_instructor,
    require_course_member,
    require_course_staff,
)
from app.grading.models import Assignment, Submission
from app.notebooks.models import Notebook
from app.users.models import User


class CourseService:
    def __init__(self, db: Session) -> None:
        self.db = db

    # -- catalogue -------------------------------------------------------
    def list_courses(self, user: User) -> list[dict]:
        if user.role == "admin":
            rows = self.db.execute(select(Course).order_by(Course.created_at)).scalars()
            return [self._course_out(course, "admin") for course in rows]
        rows = self.db.execute(
            select(Course, Enrollment.role_in_course)
            .join(Enrollment, Enrollment.course_id == Course.id)
            .where(Enrollment.user_id == user.id)
            .order_by(Course.created_at)
        ).all()
        return [self._course_out(course, role) for course, role in rows]

    def get_course_for_user(self, user: User, course_id: str) -> dict:
        course = get_course(self.db, course_id)
        role = require_course_member(self.db, user, course.id)
        return self._course_out(course, role)

    @staticmethod
    def _course_out(course: Course, role: str) -> dict:
        return {
            "id": course.id,
            "name": course.name,
            "code": course.code,
            "term": course.term,
            "status": course.status,
            "description": course.description,
            "role_in_course": role,
        }

    # -- roster ----------------------------------------------------------
    def roster(self, user: User, course_id: str, *, limit: int = 50, offset: int = 0) -> dict:
        course = get_course(self.db, course_id)
        require_course_staff(self.db, user, course.id)

        base = (
            select(User, Enrollment.role_in_course)
            .join(Enrollment, Enrollment.user_id == User.id)
            .where(
                Enrollment.course_id == course.id,
                Enrollment.role_in_course == "student",
            )
        )
        total = self.db.scalar(
            select(func.count())
            .select_from(Enrollment)
            .where(
                Enrollment.course_id == course.id,
                Enrollment.role_in_course == "student",
            )
        ) or 0
        page = self.db.execute(
            base.order_by(User.display_name).limit(limit).offset(offset)
        ).all()
        rows = self._roster_rows(course.id, page)
        return {
            "course_id": course.id,
            "rows": rows,
            "total": int(total),
            "limit": limit,
            "offset": offset,
        }

    def _roster_rows(self, course_id: uuid.UUID, page: list[tuple[User, str]]) -> list[dict]:
        user_ids = [student.id for student, _ in page]
        if not user_ids:
            return []
        assignment_ids = list(
            self.db.scalars(
                select(Assignment.id).where(
                    Assignment.course_id == course_id,
                    Assignment.is_published.is_(True),
                )
            )
        )
        submissions = self.db.scalars(
            select(Submission).where(
                Submission.user_id.in_(user_ids),
                Submission.assignment_id.in_(assignment_ids) if assignment_ids else False,
            )
        ).all()
        latest: dict[tuple[uuid.UUID, uuid.UUID], Submission] = {}
        for submission in submissions:
            key = (submission.user_id, submission.assignment_id)
            current = latest.get(key)
            if current is None or submission.attempt_number > current.attempt_number:
                latest[key] = submission

        activity = dict(
            self.db.execute(
                select(Notebook.user_id, func.max(Notebook.last_activity_at))
                .where(Notebook.user_id.in_(user_ids))
                .group_by(Notebook.user_id)
            ).all()
        )

        rows = []
        for student, role in page:
            student_submissions = [
                submission
                for (user_id, _), submission in latest.items()
                if user_id == student.id
            ]
            graded = [s for s in student_submissions if s.final_score is not None]
            average = (
                round(sum(float(s.final_score) for s in graded) / len(graded), 2)
                if graded
                else None
            )
            rows.append(
                {
                    "user_id": student.id,
                    "display_name": student.display_name,
                    "email": student.email,
                    "role_in_course": role,
                    "assigned": len(assignment_ids),
                    "submitted": len(student_submissions),
                    "completed": len(graded),
                    "average_score": average,
                    "late_count": sum(1 for s in student_submissions if s.is_late),
                    "ungraded_count": sum(
                        1 for s in student_submissions if s.final_score is None
                    ),
                    "last_active_at": activity.get(student.id),
                }
            )
        return rows

    # -- enrollments -----------------------------------------------------
    def upsert_enrollments(self, user: User, course_id: str, inputs: list) -> list[dict]:
        course = get_course(self.db, course_id)
        require_course_instructor(self.db, user, course.id)
        results: list[dict] = []
        for item in inputs:
            target = self._resolve_user(item)
            enrollment = self.db.scalar(
                select(Enrollment).where(
                    Enrollment.course_id == course.id,
                    Enrollment.user_id == target.id,
                )
            )
            if enrollment is None:
                enrollment = Enrollment(
                    course_id=course.id,
                    user_id=target.id,
                    role_in_course=item.role_in_course,
                )
                self.db.add(enrollment)
            else:
                enrollment.role_in_course = item.role_in_course
            results.append(
                {
                    "user_id": target.id,
                    "email": target.email,
                    "display_name": target.display_name,
                    "role_in_course": item.role_in_course,
                }
            )
        self.db.commit()
        return results

    def _resolve_user(self, item) -> User:
        target = None
        if item.user_id is not None:
            target = self.db.get(User, item.user_id)
        elif item.email:
            target = self.db.scalar(select(User).where(User.email == item.email.lower()))
        if target is None:
            raise NotFound("user", str(item.user_id or item.email))
        return target

    def update_enrollment(self, user: User, course_id: str, target_user_id: str, role: str) -> dict:
        course = get_course(self.db, course_id)
        require_course_instructor(self.db, user, course.id)
        try:
            target_uuid = uuid.UUID(str(target_user_id))
        except ValueError as exc:
            raise NotFound("enrollment", target_user_id) from exc
        enrollment = self.db.scalar(
            select(Enrollment).where(
                Enrollment.course_id == course.id,
                Enrollment.user_id == target_uuid,
            )
        )
        if enrollment is None:
            raise NotFound("enrollment", target_user_id)
        enrollment.role_in_course = role
        self.db.commit()
        target = self.db.get(User, target_uuid)
        return {
            "user_id": target.id,
            "email": target.email,
            "display_name": target.display_name,
            "role_in_course": role,
        }
