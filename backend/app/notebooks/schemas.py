from __future__ import annotations

import datetime as dt
import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field


class NotebookOut(BaseModel):
    id: uuid.UUID
    title: str
    file_name: str
    kind: str
    source_ref: str | None = None
    environment_image: str
    size_bytes: int
    created_at: dt.datetime
    updated_at: dt.datetime
    last_opened_at: dt.datetime | None = None
    edit_version: int = 0
    content_sha256: str | None = None
    current_version_id: uuid.UUID | None = None
    last_saved_at: dt.datetime | None = None
    last_activity_at: dt.datetime | None = None

    model_config = {"from_attributes": True}


class NotebookCreate(BaseModel):
    title: str = Field(default="Untitled Notebook", max_length=180)


class NotebookUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=180)


class ServerStateOut(BaseModel):
    running: bool
    ready: bool
    status: Literal["running", "starting", "stopped"]
    pending: str | None = None
    url: str | None = None


class OpenNotebookResponse(BaseModel):
    notebook: NotebookOut
    url: str


class NotebookListResponse(BaseModel):
    notebooks: list[NotebookOut]
    total: int


class AutosaveRequest(BaseModel):
    base_version: int = Field(ge=0)
    document: dict[str, Any]


class AutosaveResponse(BaseModel):
    version: int
    saved: bool
    sha256: str
    saved_at: dt.datetime | None = None
    version_number: int | None = None


class HeartbeatRequest(BaseModel):
    client: Literal["jupyterlab", "web"] = "jupyterlab"


class HeartbeatResponse(BaseModel):
    version: int
    last_saved_at: dt.datetime | None = None
    session_id: uuid.UUID


class NotebookVersionOut(BaseModel):
    id: uuid.UUID | None = None
    version_number: int
    kind: str
    sha256: str
    size_bytes: int | None = None
    created_by: uuid.UUID | None = None
    created_at: dt.datetime


class NotebookVersionList(BaseModel):
    versions: list[NotebookVersionOut]
