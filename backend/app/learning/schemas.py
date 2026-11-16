from __future__ import annotations

import datetime as dt
import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.notebooks.schemas import NotebookOut


class LessonProgressOut(BaseModel):
    status: str = "not_started"
    last_section: str | None = None
    completed_at: dt.datetime | None = None


class LessonSummary(BaseModel):
    slug: str
    title: str
    summary: str
    objective: str
    estimated_minutes: int
    position: int
    status: str
    dataset_slugs: list[str] = Field(default_factory=list)
    exercise_slugs: list[str] = Field(default_factory=list)
    has_notebook_activity: bool = False


class ModuleSummary(BaseModel):
    slug: str
    title: str
    description: str
    position: int
    lessons: list[LessonSummary]
    total_lessons: int
    completed_lessons: int


class PathSummary(BaseModel):
    slug: str
    title: str
    description: str
    modules: list[ModuleSummary]
    total_lessons: int
    completed_lessons: int
    progress_percent: int


class PathsResponse(BaseModel):
    paths: list[PathSummary]
    total_lessons: int
    completed_lessons: int


class DatasetRef(BaseModel):
    slug: str
    title: str
    summary: str
    category: str
    format: str | None = None
    row_count: int | None = None


class ExerciseRef(BaseModel):
    slug: str
    title: str
    topic: str
    difficulty: str


class LessonDetail(BaseModel):
    slug: str
    title: str
    objective: str
    summary: str
    estimated_minutes: int
    content: dict[str, Any]
    progress: LessonProgressOut
    datasets: list[DatasetRef]
    exercises: list[ExerciseRef]
    module: dict[str, str]
    path: dict[str, str]
    navigation: dict[str, str | None]
    has_notebook_activity: bool
    version: int


class ProgressUpdate(BaseModel):
    status: Literal["in_progress", "completed"]
    last_section: str | None = Field(default=None, max_length=120)


class LaunchResponse(BaseModel):
    notebook: NotebookOut
    url: str
    created: bool = True
