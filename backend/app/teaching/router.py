"""Persona read models: gradebook and grading queue (staff), home (student)."""

from __future__ import annotations

import datetime as dt
import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.service import get_current_user
from app.db.session import get_db
from app.teaching.service import TeachingService
from app.users.models import User

router = APIRouter(tags=["teaching"])


class GradebookAssignment(BaseModel):
    id: uuid.UUID
    title: str
    max_points: float
    weight: float
    due_at: dt.datetime | None = None
    is_visible: bool


class GradebookCell(BaseModel):
    assignment_id: uuid.UUID
    submission_id: uuid.UUID | None = None
    state: str
    score: float | None = None
    is_late: bool = False


class GradebookRow(BaseModel):
    user_id: uuid.UUID
    display_name: str
    email: str
    cells: list[GradebookCell]
    weighted_percent: float | None = None


class Gradebook(BaseModel):
    course_id: uuid.UUID
    assignments: list[GradebookAssignment]
    rows: list[GradebookRow]


class QueueRow(BaseModel):
    assignment_id: uuid.UUID
    assignment_title: str
    course_id: uuid.UUID
    course_code: str
    due_at: dt.datetime | None = None
    ungraded: int
    drafts: int
    late: int


class QueueResponse(BaseModel):
    items: list[QueueRow]


class HomeCourse(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    status: str


class DueItem(BaseModel):
    assignment_id: uuid.UUID
    title: str
    course_id: uuid.UUID
    course_code: str
    due_at: dt.datetime | None = None
    is_overdue: bool


class HomePost(BaseModel):
    id: uuid.UUID
    course_id: uuid.UUID
    course_code: str
    kind: str
    title: str
    excerpt: str
    is_read: bool
    published_at: dt.datetime


class HomeFeedback(BaseModel):
    submission_id: uuid.UUID
    assignment_id: uuid.UUID
    assignment_title: str
    course_id: uuid.UUID
    final_score: float | None = None
    max_points: float
    released_at: dt.datetime | None = None
    has_comments: bool


class StudentHome(BaseModel):
    courses: list[HomeCourse]
    due_soon: list[DueItem]
    posts: list[HomePost]
    feedback: list[HomeFeedback]


def _service(db: Session = Depends(get_db)) -> TeachingService:
    return TeachingService(db)


@router.get("/courses/{course_id}/gradebook", response_model=Gradebook)
def gradebook(
    course_id: str,
    user: User = Depends(get_current_user),
    service: TeachingService = Depends(_service),
):
    return Gradebook(**service.gradebook(user, course_id))


@router.get("/teaching/queue", response_model=QueueResponse)
def queue(user: User = Depends(get_current_user), service: TeachingService = Depends(_service)):
    return QueueResponse(items=[QueueRow(**row) for row in service.queue(user)])


@router.get("/me/home", response_model=StudentHome)
def home(user: User = Depends(get_current_user), service: TeachingService = Depends(_service)):
    return StudentHome(**service.home(user))
