from __future__ import annotations

import datetime as dt
import uuid
from typing import Literal

from pydantic import BaseModel, Field, model_validator

CourseRole = Literal["student", "ta", "instructor"]


class CourseOut(BaseModel):
    id: uuid.UUID
    name: str
    code: str
    term: str
    status: str
    description: str = ""
    role_in_course: str
    # Instructor-only: the active self-enrolment code (None when disabled).
    join_code: str | None = None


class CourseCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    code: str = Field(min_length=1, max_length=40, pattern=r"^[A-Za-z0-9][A-Za-z0-9 ._-]*$")
    term: str = Field(min_length=1, max_length=40)
    description: str = Field(default="", max_length=1000)


class CourseUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    term: str | None = Field(default=None, min_length=1, max_length=40)
    description: str | None = Field(default=None, max_length=1000)
    status: Literal["active", "archived"] | None = None


class JoinRequest(BaseModel):
    code: str = Field(min_length=4, max_length=12)


class MemberOut(BaseModel):
    user_id: uuid.UUID
    email: str
    display_name: str
    role_in_course: str
    joined_at: dt.datetime | None = None


class MembersResponse(BaseModel):
    members: list[MemberOut]


class AddMembersRequest(BaseModel):
    emails: list[str] = Field(min_length=1, max_length=1000)
    role_in_course: CourseRole = "student"


class AddMembersResponse(BaseModel):
    added: list[MemberOut]
    updated: list[MemberOut]
    unknown: list[str]


class CourseListResponse(BaseModel):
    courses: list[CourseOut]


class RosterRow(BaseModel):
    user_id: uuid.UUID
    display_name: str
    email: str
    role_in_course: str
    assigned: int = 0
    submitted: int = 0
    completed: int = 0
    average_score: float | None = None
    late_count: int = 0
    ungraded_count: int = 0
    last_active_at: dt.datetime | None = None


class RosterResponse(BaseModel):
    course_id: uuid.UUID
    rows: list[RosterRow]
    total: int
    limit: int
    offset: int


class EnrollmentInput(BaseModel):
    user_id: uuid.UUID | None = None
    email: str | None = None
    role_in_course: CourseRole = "student"

    @model_validator(mode="after")
    def _require_identity(self) -> "EnrollmentInput":
        if self.user_id is None and not self.email:
            raise ValueError("either user_id or email is required")
        return self


class EnrollmentUpdate(BaseModel):
    role_in_course: CourseRole


class EnrollmentOut(BaseModel):
    user_id: uuid.UUID
    email: str
    display_name: str
    role_in_course: str


class EnrollmentsRequest(BaseModel):
    enrollments: list[EnrollmentInput] = Field(min_length=1, max_length=1000)


class EnrollmentsResponse(BaseModel):
    enrollments: list[EnrollmentOut]
