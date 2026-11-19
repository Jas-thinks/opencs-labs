from __future__ import annotations

import datetime as dt
import uuid
from typing import Literal

from pydantic import BaseModel, Field

PostKind = Literal["announcement", "material"]
PostStatus = Literal["draft", "published"]
AttachmentKind = Literal["link", "dataset", "lesson", "exercise", "assignment", "notebook", "file"]


class AttachmentIn(BaseModel):
    kind: AttachmentKind
    # link: the external URL. dataset/lesson/exercise: slug. assignment: id.
    # notebook: the sha256 returned by POST /courses/{id}/notebook-uploads.
    target: str = Field(min_length=1, max_length=2000)
    label: str | None = Field(default=None, max_length=240)


class PostCreate(BaseModel):
    kind: PostKind = "announcement"
    title: str = Field(default="", max_length=240)
    body: str = Field(default="", max_length=20000)
    topic: str | None = Field(default=None, max_length=120)
    is_pinned: bool = False
    status: PostStatus = "published"
    publish_at: dt.datetime | None = None
    attachments: list[AttachmentIn] = Field(default_factory=list, max_length=10)


class PostUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=240)
    body: str | None = Field(default=None, max_length=20000)
    topic: str | None = Field(default=None, max_length=120)
    is_pinned: bool | None = None
    status: PostStatus | None = None
    publish_at: dt.datetime | None = None
    attachments: list[AttachmentIn] | None = Field(default=None, max_length=10)


class AttachmentOut(BaseModel):
    id: uuid.UUID
    kind: str
    label: str
    url: str | None = None
    # True when url is an in-app route (render as a router link).
    internal: bool
    blob_sha256: str | None = None
    size_bytes: int | None = None


class AuthorRef(BaseModel):
    id: uuid.UUID
    display_name: str


class PostOut(BaseModel):
    id: uuid.UUID
    course_id: uuid.UUID
    kind: str
    title: str
    body: str
    topic: str | None = None
    is_pinned: bool
    status: str
    publish_at: dt.datetime | None = None
    published_at: dt.datetime | None = None
    edited_at: dt.datetime | None = None
    created_at: dt.datetime
    author: AuthorRef | None = None
    attachments: list[AttachmentOut] = Field(default_factory=list)
    # Viewer-specific
    is_read: bool = False
    can_edit: bool = False
    # Staff-only read receipts
    read_count: int | None = None
    audience: int | None = None


class PostListResponse(BaseModel):
    posts: list[PostOut]
    next_cursor: str | None = None


class ReaderOut(BaseModel):
    user_id: uuid.UUID
    display_name: str
    read_at: dt.datetime | None = None


class ReadersResponse(BaseModel):
    read: list[ReaderOut]
    unread: list[ReaderOut]


class NotebookUploadOut(BaseModel):
    sha256: str
    file_name: str
    size_bytes: int
    cells: int


class CopyOut(BaseModel):
    notebook_id: uuid.UUID
    title: str
    url: str
    created: bool
