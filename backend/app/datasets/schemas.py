from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from pydantic import BaseModel, Field


class DatasetVersionOut(BaseModel):
    version: int
    format: str
    size_bytes: int
    sha256: str
    row_count: int
    license: str
    license_url: str = ""
    license_status: str
    source_url: str = ""
    attribution: str = ""
    published_at: dt.datetime | None = None
    is_current: bool

    model_config = {"from_attributes": True}


class DatasetSummary(BaseModel):
    id: uuid.UUID
    slug: str
    title: str
    summary: str
    category: str
    teaching_tags: list[str] = Field(default_factory=list)
    version: int | None = None
    format: str | None = None
    row_count: int | None = None
    size_bytes: int | None = None
    license: str | None = None
    license_status: str | None = None


class DatasetListResponse(BaseModel):
    datasets: list[DatasetSummary]
    total: int
    limit: int
    offset: int


class DatasetDetail(DatasetSummary):
    description: str = ""
    attribution: str = ""
    source_url: str = ""
    license_url: str = ""
    columns: list[dict[str, str]] = Field(default_factory=list)
    preview: list[dict[str, Any]] = Field(default_factory=list)
    versions: list[DatasetVersionOut] = Field(default_factory=list)
    read_only: bool = True
    notes: str = ""


class PreviewResponse(BaseModel):
    dataset_id: str
    version: int
    format: str
    row_count: int
    columns: list[dict[str, str]]
    rows: list[dict[str, Any]]
    truncated: bool
    license: str
    license_status: str


class SnippetResponse(BaseModel):
    dataset_id: str
    version: int
    language: str
    cell_type: str
    auto_execute: bool
    code: str
    path: str
    read_only: bool


class CategorySummary(BaseModel):
    category: str
    count: int
