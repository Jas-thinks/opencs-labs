"""Course-scoped authorization.

Global roles remain for identity. Access to rosters, submissions, grading and
analytics is governed by ``Enrollment.role_in_course``. Non-members get 404 so
course existence is not disclosed; members without the required course role
get 403.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import Forbidden, NotFound
from app.courses.models import Course, Enrollment
from app.users.models import User

COURSE_ROLES = ("student", "ta", "instructor")
STAFF_ROLES = ("ta", "instructor", "staff")


def _course_uuid(course_id: str | uuid.UUID) -> uuid.UUID:
    try:
        return uuid.UUID(str(course_id))
    except (ValueError, TypeError) as exc:
        raise NotFound("course", str(course_id)) from exc


def get_course(db: Session, course_id: str | uuid.UUID) -> Course:
    course = db.get(Course, _course_uuid(course_id))
    if course is None:
        raise NotFound("course")
    return course


def course_role(db: Session, user: User, course_id: str | uuid.UUID) -> str | None:
    """Return the user's effective role in the course (``admin`` bypasses)."""
    if user.role == "admin":
        return "admin"
    enrollment = db.scalar(
        select(Enrollment).where(
            Enrollment.course_id == _course_uuid(course_id),
            Enrollment.user_id == user.id,
        )
    )
    return enrollment.role_in_course if enrollment else None


def require_course_member(db: Session, user: User, course_id: str | uuid.UUID) -> str:
    get_course(db, course_id)
    role = course_role(db, user, course_id)
    if role is None:
        raise NotFound("course")
    return role


def require_course_staff(db: Session, user: User, course_id: str | uuid.UUID) -> str:
    role = require_course_member(db, user, course_id)
    if role not in ("admin", *STAFF_ROLES):
        raise Forbidden("This action requires course staff access")
    return role


def require_course_instructor(db: Session, user: User, course_id: str | uuid.UUID) -> str:
    role = require_course_member(db, user, course_id)
    if role not in ("admin", "instructor", "staff"):
        raise Forbidden("This action requires the course instructor")
    return role


def teaching_summary(db: Session, user: User) -> dict:
    """Is this person a teacher anywhere? (global instructor/admin, or staff in
    any class: the seeded TA has global role 'student' but course role 'ta')."""
    rows = db.execute(
        select(Enrollment.role_in_course, func.count())
        .where(Enrollment.user_id == user.id)
        .group_by(Enrollment.role_in_course)
    ).all()
    counts = {role: int(count) for role, count in rows}
    staff = sum(count for role, count in counts.items() if role in STAFF_ROLES)
    is_global_teacher = user.role in ("instructor", "admin")
    return {
        "is_teacher": is_global_teacher or staff > 0,
        "staff_course_count": staff,
        "student_course_count": counts.get("student", 0),
        "can_create_courses": is_global_teacher,
    }
