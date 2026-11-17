from __future__ import annotations

import datetime as dt
import uuid
from typing import Literal

from pydantic import BaseModel, Field

AssignmentKind = Literal["practice", "project", "exam"]
SubmissionStatus = Literal["submitted", "graded", "returned"]


class AssignmentCreate(BaseModel):
    title: str = Field(min_length=1, max_length=240)
    slug: str | None = Field(default=None, max_length=120)
    exercise_slug: str | None = Field(default=None, max_length=120)
    kind: AssignmentKind = "practice"
    description: str = Field(default="", max_length=2000)
    due_at: dt.datetime | None = None
    max_points: float = Field(default=100, gt=0)
    weight: float = Field(default=1, ge=0)
    allow_late: bool = True
    late_penalty_pct: int = Field(default=0, ge=0, le=100)
    is_published: bool = False


class AssignmentUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=240)
    slug: str | None = Field(default=None, max_length=120)
    exercise_slug: str | None = Field(default=None, max_length=120)
    kind: AssignmentKind | None = None
    description: str | None = Field(default=None, max_length=2000)
    due_at: dt.datetime | None = None
    max_points: float | None = Field(default=None, gt=0)
    weight: float | None = Field(default=None, ge=0)
    allow_late: bool | None = None
    late_penalty_pct: int | None = Field(default=None, ge=0, le=100)
    is_published: bool | None = None


class AssignmentOut(BaseModel):
    id: uuid.UUID
    course_id: uuid.UUID
    exercise_id: uuid.UUID | None = None
    exercise_slug: str | None = None
    slug: str
    kind: str
    title: str
    description: str
    due_at: dt.datetime | None = None
    max_points: float
    weight: float
    allow_late: bool
    late_penalty_pct: int
    is_published: bool
    created_by: uuid.UUID
    created_at: dt.datetime
    updated_at: dt.datetime


class AssignmentListResponse(BaseModel):
    assignments: list[AssignmentOut]


class RubricCriterionIn(BaseModel):
    id: uuid.UUID | None = None
    key: str = Field(min_length=1, max_length=60)
    label: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=1000)
    max_points: float = Field(ge=0)
    position: int = 0


class RubricUpsert(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    criteria: list[RubricCriterionIn] = Field(min_length=1, max_length=50)


class RubricCriterionOut(BaseModel):
    id: uuid.UUID
    key: str
    label: str
    description: str = ""
    max_points: float
    position: int


class RubricOut(BaseModel):
    id: uuid.UUID
    assignment_id: uuid.UUID
    title: str
    total_points: float
    criteria: list[RubricCriterionOut]


class SubmissionCreate(BaseModel):
    notebook_id: uuid.UUID


class NotebookVersionRef(BaseModel):
    version_number: int
    sha256: str


class StudentRef(BaseModel):
    id: uuid.UUID
    display_name: str


class SubmissionOut(BaseModel):
    id: uuid.UUID
    assignment_id: uuid.UUID
    user_id: uuid.UUID
    student: StudentRef | None = None
    notebook_id: uuid.UUID
    attempt_number: int
    status: str
    is_late: bool
    auto_score: float | None = None
    final_score: float | None = None
    score_source: str = "none"
    submitted_at: dt.datetime
    graded_at: dt.datetime | None = None
    notebook_version: NotebookVersionRef | None = None


class SubmissionListResponse(BaseModel):
    submissions: list[SubmissionOut]
    next_cursor: str | None = None


class GradeCriterionIn(BaseModel):
    criterion_id: uuid.UUID
    points: float = Field(ge=0)
    comment: str = Field(default="", max_length=4000)


class GradeRequest(BaseModel):
    criteria: list[GradeCriterionIn] = Field(min_length=1, max_length=50)
    feedback: str = Field(default="", max_length=20000)
    final_score: float | None = Field(default=None, ge=0)
    override_reason: str | None = Field(default=None, max_length=2000)


class CriterionScoreOut(BaseModel):
    criterion_id: uuid.UUID
    key: str
    label: str
    max_points: float
    points: float
    comment: str = ""


class GradeOut(BaseModel):
    id: uuid.UUID
    submission_id: uuid.UUID
    revision: int
    rubric_id: uuid.UUID
    total_points: float
    final_score: float | None = None
    feedback: str
    graded_by: uuid.UUID
    published_at: dt.datetime
    criteria: list[CriterionScoreOut] = Field(default_factory=list)


class GradeListResponse(BaseModel):
    grades: list[GradeOut]


class SubmissionDetailOut(SubmissionOut):
    latest_grade: GradeOut | None = None
    rubric: RubricOut | None = None


class MyGradeOut(BaseModel):
    submission_id: uuid.UUID
    assignment_id: uuid.UUID
    assignment_title: str
    course_id: uuid.UUID
    attempt_number: int
    is_late: bool
    final_score: float | None = None
    max_points: float
    published_at: dt.datetime | None = None
    revision: int | None = None


class MyGradesResponse(BaseModel):
    grades: list[MyGradeOut]
