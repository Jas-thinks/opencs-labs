from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel, Field

from app.courses.schemas import RosterRow


class CompletionOut(BaseModel):
    assigned: int = 0
    submitted: int = 0
    graded: int = 0


class TrendItem(BaseModel):
    assignment_id: uuid.UUID
    title: str
    score: float | None = None
    date: dt.datetime | None = None


class ScoresOut(BaseModel):
    average: float | None = None
    best: float | None = None
    trend: list[TrendItem] = Field(default_factory=list)


class CriterionMasteryOut(BaseModel):
    key: str
    label: str
    earned: float = 0
    max: float = 0
    percent: float | None = None


class TimeOnTaskRow(BaseModel):
    assignment_id: uuid.UUID
    title: str
    seconds: int = 0


class StudentAssignmentRow(BaseModel):
    id: uuid.UUID
    title: str
    status: str
    final_score: float | None = None
    max_points: float
    is_late: bool = False
    due_at: dt.datetime | None = None


class StudentDashboard(BaseModel):
    course_id: uuid.UUID | None = None
    completion: CompletionOut = Field(default_factory=CompletionOut)
    scores: ScoresOut = Field(default_factory=ScoresOut)
    criteria: list[CriterionMasteryOut] = Field(default_factory=list)
    time_on_task_seconds: int = 0
    time_on_task: list[TimeOnTaskRow] = Field(default_factory=list)
    late_count: int = 0
    ungraded_count: int = 0
    assignments: list[StudentAssignmentRow] = Field(default_factory=list)


class SubmissionDetail(BaseModel):
    submission_id: uuid.UUID
    assignment_id: uuid.UUID
    assignment_title: str
    attempt_number: int
    status: str
    is_late: bool
    final_score: float | None = None
    max_points: float
    submitted_at: dt.datetime
    graded_at: dt.datetime | None = None
    grade_revision: int | None = None
    published_at: dt.datetime | None = None


class StudentDrilldown(StudentDashboard):
    student: dict | None = None
    submissions: list[SubmissionDetail] = Field(default_factory=list)


class TeacherSummary(BaseModel):
    students: int = 0
    completion_rate: float = 0
    average_score: float | None = None
    late_rate: float = 0
    ungraded: int = 0


class TeacherAssignmentRow(BaseModel):
    id: uuid.UUID
    title: str
    max_points: float
    due_at: dt.datetime | None = None
    submitted: int = 0
    graded: int = 0
    average_score: float | None = None
    distribution: dict[str, int] = Field(default_factory=dict)


class TeacherCriterionRow(BaseModel):
    key: str
    label: str
    average_percent: float | None = None


class TeacherDashboard(BaseModel):
    course_id: uuid.UUID
    summary: TeacherSummary = Field(default_factory=TeacherSummary)
    assignments: list[TeacherAssignmentRow] = Field(default_factory=list)
    criteria: list[TeacherCriterionRow] = Field(default_factory=list)
    roster: list[RosterRow] = Field(default_factory=list)
    roster_total: int = 0
    roster_limit: int = 50
    roster_offset: int = 0
