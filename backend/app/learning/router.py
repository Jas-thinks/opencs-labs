"""Learning API: paths, lessons, progress and notebook activities."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.auth.service import get_current_user
from app.core.config import settings
from app.core.rate_limit import enforce_rate_limit
from app.db.session import get_db
from app.integrations.notebooks import NotebookBackend, get_notebook_backend
from app.learning.schemas import (
    LaunchResponse,
    LessonDetail,
    LessonProgressOut,
    PathsResponse,
    ProgressUpdate,
)
from app.learning.service import LearningService
from app.notebooks.schemas import NotebookOut
from app.notebooks.service import NotebookService
from app.users.models import User

router = APIRouter(prefix="/learning", tags=["learning"])


def _service(
    db: Session = Depends(get_db), backend: NotebookBackend = Depends(get_notebook_backend)
) -> LearningService:
    return LearningService(db, NotebookService(db, backend))


@router.get("/paths", response_model=PathsResponse)
def list_paths(user: User = Depends(get_current_user), service: LearningService = Depends(_service)):
    return service.paths(user)


@router.get("/modules")
def list_modules(user: User = Depends(get_current_user), service: LearningService = Depends(_service)):
    data = service.paths(user)
    return {
        "modules": [
            {**module, "path_slug": path["slug"], "path_title": path["title"]}
            for path in data["paths"]
            for module in path["modules"]
        ]
    }


@router.get("/lessons/{slug}", response_model=LessonDetail)
def lesson_detail(
    slug: str, user: User = Depends(get_current_user), service: LearningService = Depends(_service)
):
    return service.lesson_detail(user, slug)


@router.post("/lessons/{slug}/progress", response_model=LessonProgressOut)
def update_progress(
    slug: str,
    payload: ProgressUpdate,
    user: User = Depends(get_current_user),
    service: LearningService = Depends(_service),
):
    progress = service.update_progress(user, slug, payload.status, payload.last_section)
    return LessonProgressOut(
        status=progress.status,
        last_section=progress.last_section,
        completed_at=progress.completed_at,
    )


@router.post("/lessons/{slug}/launch", response_model=LaunchResponse)
def launch_lesson(
    slug: str,
    request: Request,
    user: User = Depends(get_current_user),
    service: LearningService = Depends(_service),
):
    enforce_rate_limit(request, "lesson-launch", settings.rate_limit_launch_per_minute)
    notebook_row, url = service.launch_activity(user, slug)
    return LaunchResponse(notebook=NotebookOut.model_validate(notebook_row), url=url)
