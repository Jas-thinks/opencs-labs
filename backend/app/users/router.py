"""Current-user endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth.schemas import PreferencesUpdate, TeachingSummary, UserOut
from app.courses.permissions import teaching_summary
from app.auth.service import get_current_user
from app.db.session import get_db
from app.users.models import User

router = APIRouter(tags=["users"])


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    out = UserOut.model_validate(user)
    out.teaching = TeachingSummary(**teaching_summary(db, user))
    return out


@router.get("/me/preferences")
def get_preferences(user: User = Depends(get_current_user)):
    return {"preferences": user.preferences or {}}


@router.patch("/me/preferences")
def update_preferences(
    payload: PreferencesUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    merged = dict(user.preferences or {})
    for key, value in payload.model_dump(exclude_unset=True).items():
        if value is not None:
            merged[key] = value
    user.preferences = merged
    db.add(user)
    db.commit()
    return {"preferences": merged}


@router.get("/me/courses")
def my_courses(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from sqlalchemy import select

    from app.courses.models import Course, Enrollment

    rows = db.execute(
        select(Course, Enrollment.role_in_course)
        .join(Enrollment, Enrollment.course_id == Course.id)
        .where(Enrollment.user_id == user.id)
        .order_by(Course.created_at)
    ).all()
    return {
        "courses": [
            {
                "id": str(course.id),
                "name": course.name,
                "code": course.code,
                "term": course.term,
                "status": course.status,
                "role_in_course": role,
            }
            for course, role in rows
        ]
    }
