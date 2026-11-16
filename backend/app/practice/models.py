"""Practice exercises and attempts.

``Exercise.evaluation`` never leaves the backend through student-facing
responses. Hidden checks are only read by the grading service.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Exercise(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "exercises"

    slug: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    topic: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    difficulty: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    objective: Mapped[str] = mapped_column(String(1000), nullable=False, default="")
    instructions: Mapped[dict] = mapped_column(default=dict, nullable=False)
    dataset_slugs: Mapped[list] = mapped_column(default=list, nullable=False)
    starter_notebook: Mapped[dict] = mapped_column(default=dict, nullable=False)
    hints: Mapped[list] = mapped_column(default=list, nullable=False)
    evaluation: Mapped[dict] = mapped_column(default=dict, nullable=False)
    solution_code: Mapped[str | None] = mapped_column(String(8000))
    estimated_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=20)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_published: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    related_lesson_slug: Mapped[str | None] = mapped_column(String(120), index=True)


class PracticeAttempt(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "practice_attempts"
    __table_args__ = (
        UniqueConstraint("user_id", "exercise_id", "attempt_number", name="uq_attempt_user_exercise_number"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    exercise_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("exercises.id", ondelete="CASCADE"), nullable=False, index=True
    )
    notebook_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("notebooks.id", ondelete="SET NULL")
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="in_progress")
    score: Mapped[float | None] = mapped_column(Float)
    feedback: Mapped[dict] = mapped_column(default=dict, nullable=False)
    started_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    submitted_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    exercise: Mapped[Exercise] = relationship(lazy="joined")
