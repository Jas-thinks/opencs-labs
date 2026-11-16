"""Dataset catalogue models.

Binaries live in object storage and on the read-only serving volume. The
database stores only catalogue metadata, checksums and schema/preview data.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Dataset(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "datasets"

    slug: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    summary: Mapped[str] = mapped_column(String(1000), nullable=False, default="")
    description: Mapped[str] = mapped_column(String(4000), nullable=False, default="")
    category: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    teaching_tags: Mapped[list] = mapped_column(default=list, nullable=False)
    is_published: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    versions: Mapped[list["DatasetVersion"]] = relationship(
        back_populates="dataset", order_by="DatasetVersion.version", cascade="all, delete-orphan"
    )

    @property
    def current_version(self) -> "DatasetVersion | None":
        published = [v for v in self.versions if v.is_current]
        if published:
            return published[0]
        return max(self.versions, key=lambda v: v.version, default=None)


class DatasetVersion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "dataset_versions"
    __table_args__ = (UniqueConstraint("dataset_id", "version", name="uq_dataset_version"),)

    dataset_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    format: Mapped[str] = mapped_column(String(20), nullable=False)
    object_key: Mapped[str] = mapped_column(String(500), nullable=False)
    # Relative to the read-only mount root, e.g. "iris/v1/iris.csv".
    relative_mount_path: Mapped[str] = mapped_column(String(500), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    columns: Mapped[list] = mapped_column(default=list, nullable=False)
    preview: Mapped[list] = mapped_column(default=list, nullable=False)
    license: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    license_url: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    license_status: Mapped[str] = mapped_column(String(30), nullable=False, default="review-required")
    source_url: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    attribution: Mapped[str] = mapped_column(String(1000), nullable=False, default="")
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    published_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    dataset: Mapped[Dataset] = relationship(back_populates="versions")
