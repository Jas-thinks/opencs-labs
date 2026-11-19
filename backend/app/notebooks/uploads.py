"""Validation for user-uploaded notebooks (.ipynb only).

Uploads arrive as JSON ({file_name, notebook}) rather than multipart: the
browser parses the file, the server re-validates everything. Only nbformat 4
documents pass; nothing else is ever stored or served.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.errors import ApiError
from app.notebooks.ipynb import validate_document
from app.notebooks.snapshots import canonical_bytes

_UNSAFE = re.compile(r"[^A-Za-z0-9 ._()\-]+")


class NotebookUpload(BaseModel):
    file_name: str = Field(min_length=1, max_length=200)
    notebook: dict[str, Any]


def clean_label(file_name: str) -> str:
    """A display/download name that is always '<safe>.ipynb'."""
    base = file_name.replace("\\", "/").rsplit("/", 1)[-1]
    stem = base[:-6] if base.lower().endswith(".ipynb") else base
    stem = _UNSAFE.sub("_", stem).strip(" ._") or "notebook"
    return f"{stem[:120]}.ipynb"


def validate_upload(upload: NotebookUpload) -> tuple[dict[str, Any], str, int]:
    """Return (document, safe_file_name, size_bytes) or raise a 4xx ApiError."""
    if not upload.file_name.lower().endswith(".ipynb"):
        raise ApiError("NOT_A_NOTEBOOK", "Only .ipynb notebook files can be uploaded", status_code=422)
    try:
        document = validate_document(upload.notebook)
    except ValueError as exc:
        raise ApiError(
            "INVALID_NOTEBOOK",
            f"This file is not a valid Jupyter notebook: {exc}",
            status_code=422,
        ) from exc
    size = len(canonical_bytes(document))
    limit = settings.notebook_upload_max_bytes
    if size > limit:
        raise ApiError(
            "NOTEBOOK_TOO_LARGE",
            f"Notebook is {size // 1024} KB; the limit is {limit // 1024} KB. Clear large outputs and try again.",
            status_code=413,
            details={"size_bytes": size, "limit_bytes": limit},
        )
    return document, clean_label(upload.file_name), size
