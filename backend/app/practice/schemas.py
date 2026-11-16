from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from pydantic import BaseModel, Field

from app.notebooks.schemas import NotebookOut


class ExerciseSummary(BaseModel):
    id: uuid.UUID
    slug: str
    title: str
    topic: str
    difficulty: str
    objective: str
    estimated_minutes: int
    dataset_slugs: list[str] = Field(default_factory=list)
    has_automated_checks: bool = False
    completed: bool = False
    attempts: int = 0


class ExerciseListResponse(BaseModel):
    exercises: list[ExerciseSummary]
    total: int
    limit: int
    offset: int


class HintOut(BaseModel):
    index: int
    text: str


class ExerciseDetail(BaseModel):
    id: uuid.UUID
    slug: str
    title: str
    topic: str
    difficulty: str
    objective: str
    instructions: dict[str, Any]
    hints: list[HintOut]
    dataset_slugs: list[str]
    datasets: list[dict[str, Any]]
    has_automated_checks: bool
    related_lesson_slug: str | None = None
    estimated_minutes: int
    completed: bool = False
    attempts: int = 0


class AttemptOut(BaseModel):
    id: uuid.UUID
    exercise_id: uuid.UUID
    exercise_slug: str
    attempt_number: int
    status: str
    score: float | None = None
    started_at: dt.datetime
    submitted_at: dt.datetime | None = None
    completed_at: dt.datetime | None = None
    feedback: dict[str, Any] = Field(default_factory=dict)
    notebook: NotebookOut | None = None

    model_config = {"from_attributes": True}


class AttemptCreateResponse(BaseModel):
    attempt: AttemptOut
    notebook: NotebookOut
    url: str
    hints: list[HintOut]


class FeedbackResponse(BaseModel):
    attempt_id: uuid.UUID
    status: str
    passed: bool
    score: float | None = None
    tests: list[dict[str, Any]] = Field(default_factory=list)
    message: str | None = None
    evaluated_at: str | None = None


class TopicSummary(BaseModel):
    topic: str
    count: int
