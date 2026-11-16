"""Practice API."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.auth.service import get_current_user
from app.core.config import settings
from app.core.rate_limit import enforce_rate_limit
from app.db.session import get_db
from app.integrations.grader import NotebookGrader, get_grader
from app.integrations.notebooks import NotebookBackend, get_notebook_backend
from app.notebooks.schemas import NotebookOut
from app.notebooks.service import NotebookService
from app.practice.schemas import (
    AttemptCreateResponse,
    AttemptOut,
    ExerciseDetail,
    ExerciseListResponse,
    ExerciseSummary,
    FeedbackResponse,
    HintOut,
    TopicSummary,
)
from app.practice.service import PracticeService
from app.users.models import User

router = APIRouter(prefix="/practice", tags=["practice"])


def _service(
    db: Session = Depends(get_db),
    backend: NotebookBackend = Depends(get_notebook_backend),
    grader: NotebookGrader = Depends(get_grader),
) -> PracticeService:
    return PracticeService(db, NotebookService(db, backend), grader)


def _summary(exercise, stats: dict | None) -> ExerciseSummary:
    stats = stats or {}
    return ExerciseSummary(
        id=exercise.id,
        slug=exercise.slug,
        title=exercise.title,
        topic=exercise.topic,
        difficulty=exercise.difficulty,
        objective=exercise.objective,
        estimated_minutes=exercise.estimated_minutes,
        dataset_slugs=exercise.dataset_slugs or [],
        has_automated_checks=bool((exercise.evaluation or {}).get("tests")),
        completed=bool(stats.get("completed")),
        attempts=int(stats.get("attempts", 0)),
    )


@router.get("/exercises", response_model=ExerciseListResponse)
def list_exercises(
    topic: str | None = Query(default=None, max_length=120),
    difficulty: str | None = Query(default=None, pattern="^(Easy|Medium|Hard)$"),
    q: str | None = Query(default=None, max_length=120),
    limit: int = Query(default=24, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=2000),
    user: User = Depends(get_current_user),
    service: PracticeService = Depends(_service),
):
    rows, total = service.list(
        user, topic=topic, difficulty=difficulty, q=q, limit=limit, offset=offset
    )
    stats = service._attempt_stats(user)
    return ExerciseListResponse(
        exercises=[_summary(row, stats.get(str(row.id))) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/topics", response_model=list[TopicSummary])
def topics(_: User = Depends(get_current_user), service: PracticeService = Depends(_service)):
    return service.topics()


@router.get("/progress")
def progress(user: User = Depends(get_current_user), service: PracticeService = Depends(_service)):
    return service.progress(user)


@router.get("/exercises/{slug}", response_model=ExerciseDetail)
def exercise_detail(
    slug: str, user: User = Depends(get_current_user), service: PracticeService = Depends(_service)
):
    return service.detail(user, slug)


@router.post("/exercises/{slug}/attempts", response_model=AttemptCreateResponse, status_code=201)
def create_attempt(
    slug: str,
    request: Request,
    user: User = Depends(get_current_user),
    service: PracticeService = Depends(_service),
):
    enforce_rate_limit(request, "practice-launch", settings.rate_limit_launch_per_minute)
    attempt, notebook_row, url, hints = service.create_attempt(user, slug)
    return AttemptCreateResponse(
        attempt=AttemptOut.model_validate(attempt),
        notebook=NotebookOut.model_validate(notebook_row),
        url=url,
        hints=[HintOut(**hint) for hint in hints],
    )


@router.get("/attempts/{attempt_id}", response_model=AttemptOut)
def get_attempt(
    attempt_id: str,
    user: User = Depends(get_current_user),
    service: PracticeService = Depends(_service),
):
    return AttemptOut.model_validate(service.get_attempt(user, attempt_id))


@router.post("/attempts/{attempt_id}/evaluate", response_model=FeedbackResponse)
def evaluate_attempt(
    attempt_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    service: PracticeService = Depends(_service),
):
    enforce_rate_limit(request, "practice-evaluate", settings.rate_limit_evaluate_per_minute)
    attempt = service.evaluate(user, attempt_id)
    feedback = attempt.get("feedback") or {}
    return FeedbackResponse(
        attempt_id=attempt["id"],
        status=attempt["status"],
        passed=attempt["status"] == "passed",
        score=attempt.get("score"),
        tests=feedback.get("tests", []),
        message=feedback.get("error"),
        evaluated_at=feedback.get("evaluated_at"),
    )


@router.get("/attempts/{attempt_id}/feedback", response_model=FeedbackResponse)
def attempt_feedback(
    attempt_id: str,
    user: User = Depends(get_current_user),
    service: PracticeService = Depends(_service),
):
    return service.feedback(user, attempt_id)
