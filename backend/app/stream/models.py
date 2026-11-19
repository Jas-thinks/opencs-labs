"""Course stream: announcements and course materials (one-way; ADR-010)."""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, utcnow

POST_KINDS = ("announcement", "material")
POST_STATUSES = ("draft", "published")
ATTACHMENT_KINDS = ("link", "dataset", "lesson", "exercise", "assignment", "file")


class CoursePost(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "course_posts"
    __table_args__ = (
        Index("ix_course_posts_feed", "course_id", "deleted_at", "status", "publish_at"),
    )

    course_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("courses.id", ondelete="CASCADE"), nullable=False
    )
    author_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="announcement")
    title: Mapped[str] = mapped_column(String(240), nullable=False, default="")
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    topic: Mapped[str | None] = mapped_column(String(120))
    is_pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="published")
    # Scheduled visibility (query-time). NULL = visible as soon as published.
    publish_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    # When the post actually became visible and notifications were fanned out.
    published_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    edited_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    attachments: Mapped[list["CoursePostAttachment"]] = relationship(
        back_populates="post",
        order_by="CoursePostAttachment.position",
        cascade="all, delete-orphan",
    )


class CoursePostAttachment(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "course_post_attachments"

    post_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("course_posts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    ref_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))
    # External http(s) URL for links; in-app path for internal references.
    url: Mapped[str | None] = mapped_column(Text)
    label: Mapped[str] = mapped_column(String(240), nullable=False, default="")
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    post: Mapped[CoursePost] = relationship(back_populates="attachments")


class PostRead(Base):
    __tablename__ = "post_reads"

    post_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("course_posts.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    read_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
