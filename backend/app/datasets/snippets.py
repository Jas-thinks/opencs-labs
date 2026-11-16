"""Validated, ready-to-insert dataset loading snippets.

The backend owns the mount path. The browser can only select a published
dataset; it can never contribute path segments.
"""

from __future__ import annotations

import posixpath
from typing import Any

from app.core.config import settings
from app.datasets.manifests import safe_relative_path

READERS = {
    "csv": "pd.read_csv",
    "parquet": "pd.read_parquet",
    "xlsx": "pd.read_excel",
}


def dataset_absolute_path(relative_path: str, mount_path: str | None = None) -> str:
    relative = safe_relative_path(relative_path)
    mount = (mount_path or settings.dataset_mount_path).rstrip("/")
    if not mount.startswith("/") or ".." in mount:
        raise ValueError("dataset mount path must be an absolute path without traversal")
    return posixpath.join(mount, relative)


def build_loading_snippet(
    *,
    dataset_id: str,
    title: str,
    version: int,
    relative_path: str,
    fmt: str,
    mount_path: str | None = None,
) -> dict[str, Any]:
    fmt = (fmt or "").lower()
    if fmt not in READERS:
        raise ValueError(f"unsupported dataset format: {fmt}")
    absolute = dataset_absolute_path(relative_path, mount_path)
    reader = READERS[fmt]
    code = (
        "import pandas as pd\n"
        "\n"
        f"# {title} (v{version}) — read-only OpenCS dataset\n"
        f"df = {reader}({absolute!r})\n"
        "df.head()"
    )
    return {
        "dataset_id": dataset_id,
        "version": version,
        "language": "python",
        "cell_type": "code",
        "auto_execute": False,
        "code": code,
        "path": absolute,
        "read_only": True,
    }
