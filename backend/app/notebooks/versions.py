"""Immutable notebook revision history."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import NotFound
from app.db.base import utcnow
from app.notebooks.ipynb import validate_document
from app.notebooks.models import Notebook, NotebookBlob, NotebookVersion
from app.notebooks.snapshots import SnapshotStore, get_snapshot_store

logger = logging.getLogger("opencs.notebooks.versions")

VERSION_KINDS = ("autosave", "checkpoint", "submission", "manual")


class NotebookVersionService:
    def __init__(self, db: Session, store: SnapshotStore | None = None) -> None:
        self.db = db
        self.store = store or get_snapshot_store(db)

    # -- writes ----------------------------------------------------------
    def create_version(
        self,
        notebook: Notebook,
        document: dict[str, Any],
        *,
        kind: str = "autosave",
        actor_id: uuid.UUID | None = None,
        commit: bool = True,
    ) -> tuple[NotebookVersion | None, bool]:
        """Create a revision. Returns ``(version, created)``.

        Autosave revisions with identical content are a no-op. Submission and
        manual revisions are always recorded, even when the content matches an
        earlier revision, because they mark a distinct event.
        """
        if kind not in VERSION_KINDS:
            raise ValueError(f"unknown version kind: {kind}")
        document = validate_document(document)
        ref = self.store.put(document)

        if kind == "autosave" and notebook.content_sha256 == ref.sha256:
            current = (
                self.db.get(NotebookVersion, notebook.current_version_id)
                if notebook.current_version_id
                else None
            )
            if commit:
                self.db.commit()
            return current, False

        next_number = int(
            self.db.scalar(
                select(func.max(NotebookVersion.version_number)).where(
                    NotebookVersion.notebook_id == notebook.id
                )
            )
            or 0
        ) + 1
        now = utcnow()
        version = NotebookVersion(
            notebook_id=notebook.id,
            version_number=next_number,
            blob_sha256=ref.sha256,
            kind=kind,
            created_by=actor_id,
            created_at=now,
        )
        self.db.add(version)
        self.db.flush()

        notebook.content_sha256 = ref.sha256
        notebook.current_version_id = version.id
        notebook.edit_version = int(notebook.edit_version or 0) + 1
        notebook.last_saved_at = now
        notebook.last_activity_at = now
        notebook.size_bytes = ref.size_bytes

        if commit:
            self.db.commit()
            self.db.refresh(version)
            self.db.refresh(notebook)
        return version, True

    # -- reads -----------------------------------------------------------
    def list_versions(
        self, notebook_id: uuid.UUID, *, kind: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        stmt = (
            select(NotebookVersion, NotebookBlob.size_bytes)
            .join(NotebookBlob, NotebookBlob.sha256 == NotebookVersion.blob_sha256)
            .where(NotebookVersion.notebook_id == notebook_id)
            .order_by(NotebookVersion.version_number.desc())
            .limit(limit)
        )
        if kind:
            stmt = stmt.where(NotebookVersion.kind == kind)
        return [
            {
                "id": version.id,
                "version_number": version.version_number,
                "kind": version.kind,
                "sha256": version.blob_sha256,
                "size_bytes": size,
                "created_by": version.created_by,
                "created_at": version.created_at,
            }
            for version, size in self.db.execute(stmt).all()
        ]

    def get_version(
        self, notebook_id: uuid.UUID, version_number: int
    ) -> NotebookVersion:
        version = self.db.scalar(
            select(NotebookVersion).where(
                NotebookVersion.notebook_id == notebook_id,
                NotebookVersion.version_number == version_number,
            )
        )
        if version is None:
            raise NotFound("notebook version", str(version_number))
        return version

    def load_version(
        self, notebook_id: uuid.UUID, version_number: int
    ) -> tuple[NotebookVersion, dict[str, Any]]:
        version = self.get_version(notebook_id, version_number)
        return version, self.store.get(version.blob_sha256)

    def load_version_by_id(
        self, version_id: uuid.UUID
    ) -> tuple[NotebookVersion, dict[str, Any]]:
        version = self.db.get(NotebookVersion, version_id)
        if version is None:
            raise NotFound("notebook version")
        return version, self.store.get(version.blob_sha256)

    # -- retention -------------------------------------------------------
    def prune_autosaves(
        self, notebook_id: uuid.UUID | str | None = None, *, keep: int | None = None
    ) -> int:
        """Keep the newest ``keep`` autosave versions per notebook.

        Submission versions are never considered. Blobs are collected only
        after no version references them.
        """
        keep = settings.autosave_retention if keep is None else keep
        if keep < 1:
            keep = 1
        stmt = select(NotebookVersion.notebook_id).where(NotebookVersion.kind == "autosave")
        if notebook_id is not None:
            stmt = stmt.where(NotebookVersion.notebook_id == uuid.UUID(str(notebook_id)))
        notebook_ids = {row for row in self.db.scalars(stmt).all()}

        deleted = 0
        for nb_id in notebook_ids:
            stale = list(
                self.db.scalars(
                    select(NotebookVersion.id)
                    .where(
                        NotebookVersion.notebook_id == nb_id,
                        NotebookVersion.kind == "autosave",
                    )
                    .order_by(NotebookVersion.version_number.desc())
                    .offset(keep)
                ).all()
            )
            if not stale:
                continue
            self.db.execute(delete(NotebookVersion).where(NotebookVersion.id.in_(stale)))
            self.db.execute(
                update(Notebook)
                .where(Notebook.current_version_id.in_(stale))
                .values(current_version_id=None)
            )
            deleted += len(stale)
        if deleted:
            self.db.flush()
            self.collect_garbage()
            self.db.commit()
            logger.info("pruned %s autosave versions", deleted)
        return deleted

    def collect_garbage(self) -> int:
        referenced = select(NotebookVersion.blob_sha256)
        result = self.db.execute(
            delete(NotebookBlob).where(NotebookBlob.sha256.not_in(referenced))
        )
        return result.rowcount or 0


def snapshot_metadata(
    notebook: Notebook, version: NotebookVersion, size_bytes: int | None = None
) -> dict[str, Any]:
    return {
        "version_number": version.version_number,
        "kind": version.kind,
        "sha256": version.blob_sha256,
        "created_at": version.created_at,
        "size_bytes": size_bytes,
    }
