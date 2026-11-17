"""Analytics and dashboard endpoints."""

from __future__ import annotations

import csv
import datetime as dt
import io

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.analytics.schemas import (
    StudentDashboard,
    StudentDrilldown,
    TeacherDashboard,
)
from app.analytics.service import AnalyticsService
from app.auth.service import get_current_user
from app.db.session import get_db
from app.users.models import User

router = APIRouter(prefix="/analytics", tags=["analytics"])


def _service(db: Session = Depends(get_db)) -> AnalyticsService:
    return AnalyticsService(db)


@router.get("/me", response_model=StudentDashboard)
def my_dashboard(
    course_id: str | None = Query(default=None),
    user: User = Depends(get_current_user),
    service: AnalyticsService = Depends(_service),
):
    return service.student_dashboard(user, course_id)


@router.get("/courses/{course_id}", response_model=TeacherDashboard)
def course_dashboard(
    course_id: str,
    assignment_id: str | None = Query(default=None),
    date_from: dt.datetime | None = Query(default=None, alias="from"),
    date_to: dt.datetime | None = Query(default=None, alias="to"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    service: AnalyticsService = Depends(_service),
):
    return service.teacher_dashboard(
        user,
        course_id,
        limit=limit,
        offset=offset,
        assignment_id=assignment_id,
        date_from=date_from,
        date_to=date_to,
    )


@router.get(
    "/courses/{course_id}/students/{user_id}", response_model=StudentDrilldown
)
def student_drilldown(
    course_id: str,
    user_id: str,
    user: User = Depends(get_current_user),
    service: AnalyticsService = Depends(_service),
):
    return service.student_drilldown(user, course_id, user_id)


def _csv_safe(value: object) -> object:
    """Prevent spreadsheet formula injection in exported cells."""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@"):
        return "'" + value
    return value


@router.get("/courses/{course_id}/export.csv")
def export_csv(
    course_id: str,
    user: User = Depends(get_current_user),
    service: AnalyticsService = Depends(_service),
):
    rows = service.export_rows(user, course_id)
    buffer = io.StringIO()
    fieldnames = [
        "user_id",
        "display_name",
        "email",
        "role_in_course",
        "assigned",
        "submitted",
        "completed",
        "average_score",
        "late_count",
        "ungraded_count",
        "last_active_at",
    ]
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(
            {key: _csv_safe(row.get(key)) for key in fieldnames}
        )
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={
            "content-disposition": f'attachment; filename="course-{course_id}-grades.csv"'
        },
    )
