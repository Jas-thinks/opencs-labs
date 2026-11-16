"""Dataset catalogue queries and previews."""

from __future__ import annotations

import datetime as dt
import logging
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.core.errors import NotFound
from app.datasets.models import Dataset, DatasetVersion
from app.datasets.snippets import build_loading_snippet

logger = logging.getLogger("opencs.datasets")


class DatasetService:
    def __init__(self, db: Session, serving_dir: Path | None = None) -> None:
        self.db = db
        self.serving_dir = serving_dir or settings.serving_dir

    def _query(self):
        return (
            select(Dataset)
            .where(Dataset.is_published.is_(True))
            .options(selectinload(Dataset.versions))
        )

    def list(
        self,
        *,
        q: str | None = None,
        category: str | None = None,
        tag: str | None = None,
        limit: int = 24,
        offset: int = 0,
    ) -> tuple[list[Dataset], int]:
        stmt = self._query()
        if category:
            stmt = stmt.where(Dataset.category == category)
        if q:
            needle = f"%{q.strip().lower()}%"
            stmt = stmt.where(
                or_(
                    func.lower(Dataset.title).like(needle),
                    func.lower(Dataset.summary).like(needle),
                    func.lower(Dataset.description).like(needle),
                )
            )
        rows = list(self.db.scalars(stmt.order_by(Dataset.position, Dataset.title)))
        if tag:
            rows = [row for row in rows if tag in (row.teaching_tags or [])]
        total = len(rows)
        return rows[offset : offset + limit], total

    def get(self, slug: str) -> Dataset:
        dataset = self.db.scalar(self._query().where(Dataset.slug == slug))
        if dataset is None:
            raise NotFound("dataset", slug)
        return dataset

    def categories(self) -> list[dict[str, Any]]:
        rows = self.db.execute(
            select(Dataset.category, func.count(Dataset.id))
            .where(Dataset.is_published.is_(True))
            .group_by(Dataset.category)
            .order_by(Dataset.category)
        ).all()
        return [{"category": category, "count": count} for category, count in rows]

    def _version(self, dataset: Dataset, version: int | None) -> DatasetVersion:
        if version is None:
            current = dataset.current_version
            if current is None:
                raise NotFound("dataset version", dataset.slug)
            return current
        for candidate in dataset.versions:
            if candidate.version == version:
                return candidate
        raise NotFound("dataset version", f"{dataset.slug}:v{version}")

    def snippet(self, slug: str, version: int | None = None) -> dict[str, Any]:
        dataset = self.get(slug)
        selected = self._version(dataset, version)
        return build_loading_snippet(
            dataset_id=dataset.slug,
            title=dataset.title,
            version=selected.version,
            relative_path=selected.relative_mount_path,
            fmt=selected.format,
        )

    def preview(self, slug: str, *, limit: int = 20) -> dict[str, Any]:
        dataset = self.get(slug)
        selected = self._version(dataset, None)
        limit = max(1, min(limit, 100))
        rows = selected.preview or []
        truncated = selected.row_count > len(rows)

        file_path = (self.serving_dir / selected.relative_mount_path).resolve()
        root = self.serving_dir.resolve()
        if str(file_path).startswith(str(root) + "/") and file_path.is_file():
            try:
                frame = self._read_bounded(file_path, selected.format, limit)
                rows = self._records(frame)
                truncated = selected.row_count > len(rows)
            except Exception as exc:  # noqa: BLE001 - fall back to stored preview
                logger.warning("live preview failed for %s: %s", slug, exc)

        return {
            "dataset_id": dataset.slug,
            "version": selected.version,
            "format": selected.format,
            "row_count": selected.row_count,
            "columns": selected.columns,
            "rows": rows[:limit],
            "truncated": truncated,
            "license": selected.license,
            "license_status": selected.license_status,
        }

    @staticmethod
    def _read_bounded(path: Path, fmt: str, limit: int) -> pd.DataFrame:
        if fmt == "csv":
            return pd.read_csv(path, nrows=limit)
        if fmt == "parquet":
            return pd.read_parquet(path).head(limit)
        if fmt == "xlsx":
            return pd.read_excel(path, nrows=limit)
        raise ValueError(f"unsupported preview format: {fmt}")

    @staticmethod
    def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for row in frame.astype(object).to_dict(orient="records"):
            clean: dict[str, Any] = {}
            for key, value in row.items():
                clean[str(key)] = _json_scalar(value)
            records.append(clean)
        return records


def _json_scalar(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (pd.Timestamp, dt.datetime, dt.date)):
        return value.isoformat()
    if isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return None if pd.isna(value) else value
    if hasattr(value, "item"):
        inner = value.item()
        return None if isinstance(inner, float) and pd.isna(inner) else inner
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return str(value)
