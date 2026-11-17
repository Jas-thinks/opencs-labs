"""Notebook metadata, immutable snapshots and presence sessions.

The notebook *file* lives in the student's Jupyter home on persistent
storage. The ``notebooks`` table is the ownership index used for
authorization; ``notebook_versions`` is the append-only history of saved
documents and ``notebook_blobs`` is the content-addressed store those
versions point at. ``file_name`` is generated server-side; no browser-supplied
path is ever used to resolve storage.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, utcnow


class Notebook(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "notebooks"
    __table_args__ = (UniqueConstraint("user_id", "file_name", name="uq_notebook_user_file"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    file_name: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="personal")
    source_ref: Mapped[str | None] = mapped_column(String(200))
    environment_image: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    last_opened_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    # --- active state -----------------------------------------------------
    edit_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    content_sha256: Mapped[str | None] = mapped_column(String(64))
    # Denormalised pointer to the latest version. Deliberately a plain UUID
    # (no FK) so notebooks <-> notebook_versions is not a circular schema.
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), index=True)
    last_saved_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    last_activity_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class NotebookBlob(Base):
    """One row per distinct canonical notebook document."""

    __tablename__ = "notebook_blobs"

    sha256: Mapped[str] = mapped_column(String(64), primary_key=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    encoding: Mapped[str] = mapped_column(String(16), nullable=False, default="gzip+json")
    data: Mapped[bytes | None] = mapped_column(LargeBinary)
    storage_kind: Mapped[str] = mapped_column(String(16), nullable=False, default="db")
    storage_key: Mapped[str | None] = mapped_column(String(512))
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


class NotebookVersion(UUIDPrimaryKeyMixin, Base):
    """An immutable saved revision of a notebook."""

    __tablename__ = "notebook_versions"
    __table_args__ = (
        UniqueConstraint("notebook_id", "version_number", name="uq_notebook_version_number"),
        Index("ix_notebook_versions_notebook_version", "notebook_id", "version_number"),
        Index("ix_notebook_versions_kind", "kind"),
    )

    notebook_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("notebooks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    blob_sha256: Mapped[str] = mapped_column(
        String(64), ForeignKey("notebook_blobs.sha256"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="autosave")
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


class NotebookSession(UUIDPrimaryKeyMixin, Base):
    """Presence record used for time-on-task analytics."""

    __tablename__ = "notebook_sessions"
    __table_args__ = (
        Index("ix_notebook_sessions_user_started", "user_id", "started_at"),
        Index("ix_notebook_sessions_notebook_seen", "notebook_id", "last_seen_at"),
    )

    notebook_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("notebooks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    client: Mapped[str] = mapped_column(String(20), nullable=False, default="jupyterlab")
    started_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
