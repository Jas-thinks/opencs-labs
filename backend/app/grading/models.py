"""Course work, rubrics, submissions and append-only grade revisions."""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, utcnow

ASSIGNMENT_KINDS = ("practice", "project", "exam")
COURSE_ROLES = ("student", "ta", "instructor")


class Assignment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "assignments"
    __table_args__ = (
        UniqueConstraint("course_id", "slug", name="uq_assignment_course_slug"),
        Index("ix_assignments_course_published", "course_id", "is_published"),
    )

    course_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("courses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    exercise_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("exercises.id", ondelete="SET NULL"), index=True
    )
    slug: Mapped[str] = mapped_column(String(120), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="practice")
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    description: Mapped[str] = mapped_column(String(2000), nullable=False, default="")
    due_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    max_points: Mapped[float] = mapped_column(Float, nullable=False, default=100.0)
    weight: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    allow_late: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    late_penalty_pct: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_published: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_by: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id"), nullable=False
    )

    rubric: Mapped["Rubric | None"] = relationship(
        back_populates="assignment", uselist=False, cascade="all, delete-orphan"
    )


class Rubric(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "rubrics"

    assignment_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("assignments.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    total_points: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    created_by: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id"), nullable=False
    )

    assignment: Mapped[Assignment] = relationship(back_populates="rubric")
    criteria: Mapped[list["RubricCriterion"]] = relationship(
        back_populates="rubric", order_by="RubricCriterion.position", cascade="all, delete-orphan"
    )


class RubricCriterion(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "rubric_criteria"
    __table_args__ = (UniqueConstraint("rubric_id", "key", name="uq_rubric_criterion_key"),)

    rubric_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("rubrics.id", ondelete="CASCADE"), nullable=False, index=True
    )
    key: Mapped[str] = mapped_column(String(60), nullable=False)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(String(1000), nullable=False, default="")
    max_points: Mapped[float] = mapped_column(Float, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    rubric: Mapped[Rubric] = relationship(back_populates="criteria")


class Submission(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "submissions"
    __table_args__ = (
        UniqueConstraint(
            "assignment_id", "user_id", "attempt_number", name="uq_submission_attempt"
        ),
        Index("ix_submissions_assignment_user", "assignment_id", "user_id"),
        Index("ix_submissions_assignment_status", "assignment_id", "status"),
        Index("ix_submissions_user_submitted", "user_id", "submitted_at"),
    )

    assignment_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("assignments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    notebook_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("notebooks.id"), nullable=False, index=True
    )
    notebook_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("notebook_versions.id"), nullable=False
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="submitted")
    is_late: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    auto_score: Mapped[float | None] = mapped_column(Float)
    final_score: Mapped[float | None] = mapped_column(Float)
    score_source: Mapped[str] = mapped_column(String(16), nullable=False, default="none")
    submitted_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    graded_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class SubmissionGrade(UUIDPrimaryKeyMixin, Base):
    """One grading revision. Corrections insert a new row; history is never edited."""

    __tablename__ = "submission_grades"
    __table_args__ = (
        UniqueConstraint("submission_id", "revision", name="uq_submission_grade_revision"),
        Index("ix_submission_grades_submission_revision", "submission_id", "revision"),
    )

    submission_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("submissions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    rubric_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("rubrics.id"), nullable=False
    )
    total_points: Mapped[float] = mapped_column(Float, nullable=False)
    feedback: Mapped[str] = mapped_column(Text, nullable=False, default="")
    graded_by: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    published_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


class GradeCriterionScore(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "grade_criterion_scores"
    __table_args__ = (
        UniqueConstraint(
            "submission_grade_id", "criterion_id", name="uq_grade_criterion"
        ),
        Index("ix_grade_criterion_scores_criterion", "criterion_id"),
    )

    submission_grade_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("submission_grades.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    criterion_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("rubric_criteria.id"), nullable=False
    )
    points: Mapped[float] = mapped_column(Float, nullable=False)
    comment: Mapped[str] = mapped_column(Text, nullable=False, default="")
