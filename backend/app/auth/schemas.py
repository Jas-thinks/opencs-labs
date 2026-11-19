from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, Field

from app.core.validation import EmailAddress


class TeachingSummary(BaseModel):
    """Drives the teacher vs student experience in the UI. Computed server-side;
    every endpoint still enforces course-scoped permissions on its own."""

    is_teacher: bool = False
    staff_course_count: int = 0
    student_course_count: int = 0
    can_create_courses: bool = False


class UserOut(BaseModel):
    id: uuid.UUID
    email: EmailAddress
    display_name: str
    role: str
    hub_username: str
    preferences: dict = Field(default_factory=dict)
    teaching: TeachingSummary = Field(default_factory=TeachingSummary)

    model_config = {"from_attributes": True}


class LoginRequest(BaseModel):
    email: EmailAddress
    password: str = Field(min_length=1, max_length=200)


class LoginResponse(BaseModel):
    user: UserOut
    expires_in: int


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int


class PreferencesUpdate(BaseModel):
    theme: Literal["dark", "light", "system"] | None = None
    editor_font_size: int | None = Field(default=None, ge=10, le=28)
    default_notebook_profile: Literal["standard", "medium", "heavy"] | None = None
