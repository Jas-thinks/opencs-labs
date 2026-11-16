"""Notebook metadata.

The notebook *file* lives in the student's Jupyter home on persistent
storage. This table is the ownership index used for authorization. The
``file_name`` is generated server-side; no browser-supplied path is ever
used to resolve storage.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


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
