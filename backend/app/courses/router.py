"""Course list, detail, roster and enrollment endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth.service import get_current_user
from app.courses.schemas import (
    CourseListResponse,
    CourseOut,
    EnrollmentOut,
    EnrollmentsRequest,
    EnrollmentsResponse,
    EnrollmentUpdate,
    RosterResponse,
    RosterRow,
)
from app.courses.service import CourseService
from app.db.session import get_db
from app.users.models import User

router = APIRouter(prefix="/courses", tags=["courses"])


def _service(db: Session = Depends(get_db)) -> CourseService:
    return CourseService(db)


@router.get("", response_model=CourseListResponse)
def list_courses(
    user: User = Depends(get_current_user), service: CourseService = Depends(_service)
):
    return CourseListResponse(courses=[CourseOut(**row) for row in service.list_courses(user)])


@router.get("/{course_id}", response_model=CourseOut)
def get_course(
    course_id: str,
    user: User = Depends(get_current_user),
    service: CourseService = Depends(_service),
):
    return CourseOut(**service.get_course_for_user(user, course_id))


@router.get("/{course_id}/roster", response_model=RosterResponse)
def roster(
    course_id: str,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    service: CourseService = Depends(_service),
):
    data = service.roster(user, course_id, limit=limit, offset=offset)
    return RosterResponse(
        course_id=data["course_id"],
        rows=[RosterRow(**row) for row in data["rows"]],
        total=data["total"],
        limit=data["limit"],
        offset=data["offset"],
    )


@router.post("/{course_id}/enrollments", response_model=EnrollmentsResponse)
def upsert_enrollments(
    course_id: str,
    payload: EnrollmentsRequest,
    user: User = Depends(get_current_user),
    service: CourseService = Depends(_service),
):
    rows = service.upsert_enrollments(user, course_id, payload.enrollments)
    return EnrollmentsResponse(enrollments=[EnrollmentOut(**row) for row in rows])


@router.patch("/{course_id}/enrollments/{user_id}", response_model=EnrollmentOut)
def update_enrollment(
    course_id: str,
    user_id: str,
    payload: EnrollmentUpdate,
    user: User = Depends(get_current_user),
    service: CourseService = Depends(_service),
):
    row = service.update_enrollment(user, course_id, user_id, payload.role_in_course)
    return EnrollmentOut(**row)
