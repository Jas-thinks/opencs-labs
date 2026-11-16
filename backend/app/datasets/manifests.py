"""Dataset manifest validation.

Manifests are produced by ``scripts/fetch_datasets.py`` from the real files.
The backend validates them again before publishing so a malformed or unsafe
manifest can never reach the catalogue or generate a loading snippet.
"""

from __future__ import annotations

import json
import posixpath
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
RELATIVE_PATH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*(/[A-Za-z0-9][A-Za-z0-9._-]*)+$")
SUPPORTED_FORMATS = {"csv", "parquet", "xlsx"}


def safe_relative_path(value: str) -> str:
    """Reject absolute paths, traversal and separators we do not control."""
    if not value or value.startswith("/") or "\\" in value or ".." in value:
        raise ValueError("dataset path must be a safe relative path")
    normalised = posixpath.normpath(value)
    if normalised.startswith("..") or not RELATIVE_PATH_RE.match(normalised):
        raise ValueError("dataset path must be a safe relative path")
    if posixpath.isabs(normalised):
        raise ValueError("dataset path must be relative")
    return normalised


class ColumnSchema(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    dtype: str = Field(min_length=1, max_length=40)


class ManifestVersion(BaseModel):
    version: int = Field(ge=1)
    format: str
    file: str
    object_key: str
    relative_mount_path: str
    sha256: str
    size_bytes: int = Field(ge=0)
    row_count: int = Field(ge=0)
    columns: list[ColumnSchema]
    preview: list[dict[str, Any]]
    published_at: str | None = None
    transform: dict[str, Any] = Field(default_factory=dict)

    @field_validator("sha256")
    @classmethod
    def _sha(cls, value: str) -> str:
        value = value.lower()
        if not SHA256_RE.match(value):
            raise ValueError("sha256 must be 64 lowercase hex characters")
        return value

    @field_validator("format")
    @classmethod
    def _format(cls, value: str) -> str:
        value = value.lower()
        if value not in SUPPORTED_FORMATS:
            raise ValueError(f"unsupported dataset format: {value}")
        return value

    @field_validator("relative_mount_path", "object_key")
    @classmethod
    def _path(cls, value: str) -> str:
        return safe_relative_path(value)

    @field_validator("file")
    @classmethod
    def _file(cls, value: str) -> str:
        if "/" in value or "\\" in value or value.startswith("."):
            raise ValueError("file must be a bare file name")
        return value

    @model_validator(mode="after")
    def _consistent(self) -> "ManifestVersion":
        if not self.relative_mount_path.endswith("/" + self.file):
            raise ValueError("relative_mount_path must end with file")
        if len(self.columns) == 0:
            raise ValueError("columns must not be empty")
        for row in self.preview:
            unexpected = set(row) - {column.name for column in self.columns}
            if unexpected:
                raise ValueError(f"preview contains unknown columns: {sorted(unexpected)}")
        return self


class DatasetManifest(BaseModel):
    schema_version: int = 1
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,60}$")
    title: str = Field(min_length=1, max_length=200)
    category: str = Field(min_length=1, max_length=80)
    summary: str = Field(min_length=1, max_length=1000)
    description: str = Field(default="", max_length=4000)
    teaching_tags: list[str] = Field(default_factory=list)
    position: int = 0
    license: str = Field(min_length=1, max_length=200)
    license_url: str = ""
    license_status: str = "review-required"
    source_url: str = ""
    attribution: str = ""
    notes: str = ""
    versions: list[ManifestVersion]

    @model_validator(mode="after")
    def _versions_unique(self) -> "DatasetManifest":
        seen = set()
        for version in self.versions:
            if version.version in seen:
                raise ValueError("duplicate dataset version")
            seen.add(version.version)
        if not self.versions:
            raise ValueError("dataset must have at least one version")
        return self


def load_manifest(path: Path) -> DatasetManifest:
    return DatasetManifest.model_validate(json.loads(Path(path).read_text()))


def load_manifests(directory: Path) -> list[DatasetManifest]:
    manifests = []
    for path in sorted(Path(directory).glob("*.json")):
        if path.name == "index.json":
            continue
        manifests.append(load_manifest(path))
    return manifests


def verify_file(manifest: DatasetManifest, serving_dir: Path) -> list[str]:
    """Verify that every version's file exists and matches size and checksum."""
    import hashlib

    problems: list[str] = []
    root = Path(serving_dir).resolve()
    for version in manifest.versions:
        path = (root / version.relative_mount_path).resolve()
        if not str(path).startswith(str(root) + "/"):
            problems.append(f"v{version.version}: path escapes serving root")
            continue
        if not path.is_file():
            problems.append(f"v{version.version}: missing file {version.relative_mount_path}")
            continue
        if path.stat().st_size != version.size_bytes:
            problems.append(f"v{version.version}: size mismatch")
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest() != version.sha256:
            problems.append(f"v{version.version}: sha256 mismatch")
    return problems
