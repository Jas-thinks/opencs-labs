from __future__ import annotations

import datetime as dt
import uuid
from typing import Literal

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
