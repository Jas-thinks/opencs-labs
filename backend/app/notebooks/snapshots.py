"""Content-addressed notebook document storage.

Documents are canonicalised (sorted keys, no insignificant whitespace), hashed
with SHA-256 and gzip-compressed into ``notebook_blobs``. Identical documents
therefore store and hash identically. The interface keeps the door open for an
object-storage adapter without changing version or API callers.
"""

from __future__ import annotations

import gzip
import hashlib
import json
from dataclasses import dataclass
from typing import Any, Protocol

from sqlalchemy.orm import Session

from app.core.errors import Conflict
from app.db.base import utcnow
from app.notebooks.models import NotebookBlob

ENCODING = "gzip+json"


@dataclass(frozen=True)
class SnapshotRef:
    sha256: str
    size_bytes: int
    created: bool


class SnapshotStore(Protocol):
    def put(self, document: dict[str, Any]) -> SnapshotRef: ...

    def get(self, sha256: str) -> dict[str, Any]: ...


def canonical_bytes(document: dict[str, Any]) -> bytes:
    """Deterministic JSON encoding used for hashing and storage."""
    return json.dumps(
        document,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


class DbSnapshotStore:
    def __init__(self, db: Session) -> None:
        self.db = db

    def put(self, document: dict[str, Any]) -> SnapshotRef:
        payload = canonical_bytes(document)
        sha256 = hashlib.sha256(payload).hexdigest()
        existing = self.db.get(NotebookBlob, sha256)
        if existing is not None:
            return SnapshotRef(sha256, existing.size_bytes, created=False)
        self.db.add(
            NotebookBlob(
                sha256=sha256,
                size_bytes=len(payload),
                encoding=ENCODING,
                data=gzip.compress(payload, mtime=0),
                storage_kind="db",
                created_at=utcnow(),
            )
        )
        self.db.flush()
        return SnapshotRef(sha256, len(payload), created=True)

    def get(self, sha256: str) -> dict[str, Any]:
        blob = self.db.get(NotebookBlob, sha256)
        if blob is None:
            raise Conflict("SNAPSHOT_MISSING", "The notebook snapshot is not available")
        if blob.storage_kind != "db" or blob.data is None:
            raise Conflict(
                "SNAPSHOT_UNAVAILABLE",
                "The notebook snapshot is stored externally and cannot be read here",
            )
        try:
            payload = gzip.decompress(blob.data)
        except OSError as exc:
            raise Conflict("SNAPSHOT_CORRUPT", "The notebook snapshot could not be decoded") from exc
        document = json.loads(payload.decode("utf-8"))
        if not isinstance(document, dict):
            raise Conflict("SNAPSHOT_CORRUPT", "The notebook snapshot is not a JSON object")
        return document


def get_snapshot_store(db: Session) -> SnapshotStore:
    return DbSnapshotStore(db)
