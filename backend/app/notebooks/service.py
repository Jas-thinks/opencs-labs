"""Notebook metadata + Jupyter storage orchestration.

Every operation resolves storage through the authenticated owner. A browser
never supplies a filesystem path that is used directly.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import logging
import time
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import ApiError, CapacityExhausted, Conflict, NotFound, UpstreamUnavailable
from app.core.time import ensure_utc
from app.db.base import utcnow
from app.integrations.jupyterhub import ServerState
from app.integrations.notebooks import NotebookBackend, get_notebook_backend
from app.notebooks.ipynb import build_notebook, unique_file_name, validate_document, validate_file_name
from app.notebooks.models import Notebook, NotebookSession
from app.notebooks.snapshots import canonical_bytes
from app.notebooks.versions import NotebookVersionService
from app.users.models import User

logger = logging.getLogger("opencs.notebooks")


class NotebookService:
    def __init__(self, db: Session, backend: NotebookBackend | None = None) -> None:
        self.db = db
        self.backend = backend or get_notebook_backend()

    # -- server lifecycle --------------------------------------------------
    def server_state(self, user: User) -> ServerState:
        return self.backend.get_server_state(user)

    def ensure_server_ready(self, user: User, timeout: int | None = None) -> ServerState:
        state = self.backend.get_server_state(user)
        if state.running and state.ready:
            return state

        if not state.running:
            self._check_capacity()
            state = self.backend.start_server(user)
            logger.info("spawn requested", extra={"user": user.hub_username})

        deadline = time.monotonic() + (timeout or settings.notebook_start_timeout_seconds)
        while time.monotonic() < deadline:
            state = self.backend.get_server_state(user)
            if state.ready:
                return state
            time.sleep(1.0)

        raise ApiError(
            "NOTEBOOK_START_TIMEOUT",
            "The notebook server did not become ready in time. It may still be starting; retry shortly.",
            status_code=503,
            details={"timeout_seconds": timeout or settings.notebook_start_timeout_seconds},
        )

    def _check_capacity(self) -> None:
        try:
            active = self.backend.active_session_count()
        except UpstreamUnavailable:
            raise
        if active >= settings.max_active_sessions:
            raise CapacityExhausted(
                "All notebook slots are currently in use. Please retry shortly.",
                details={"active_sessions": active, "capacity": settings.max_active_sessions},
            )

    def start_server(self, user: User) -> ServerState:
        state = self.backend.get_server_state(user)
        if state.running:
            return state
        self._check_capacity()
        return self.backend.start_server(user)

    def stop_server(self, user: User) -> None:
        self.backend.stop_server(user)

    # -- metadata ----------------------------------------------------------
    def get_owned(self, user: User, notebook_id: str) -> Notebook:
        try:
            notebook_uuid = uuid.UUID(str(notebook_id))
        except ValueError as exc:
            raise NotFound("notebook", str(notebook_id)) from exc
        notebook = self.db.get(Notebook, notebook_uuid)
        if notebook is None:
            raise NotFound("notebook")
        if notebook.user_id != user.id:
            # Do not reveal that another user's notebook exists.
            raise NotFound("notebook")
        if notebook.kind == "upload":
            # Storage-only turn-in (no workspace file): never opened or edited.
            raise NotFound("notebook")
        return notebook

    def _existing_file_names(self, user: User) -> set[str]:
        rows = self.db.scalars(select(Notebook.file_name).where(Notebook.user_id == user.id))
        return set(rows)

    def _remote_file_names(self, user: User) -> set[str]:
        try:
            entries = self.backend.contents_list(user, "")
        except (UpstreamUnavailable, FileNotFoundError):
            return set()
        names = set()
        for entry in entries:
            if entry.get("type") == "notebook":
                names.add(entry["name"])
        return names

    def create(
        self,
        user: User,
        *,
        title: str,
        kind: str = "personal",
        source_ref: str | None = None,
        cells: list[dict] | None = None,
        notebook: dict | None = None,
        metadata: dict | None = None,
        wait_for_server: bool = True,
    ) -> Notebook:
        title = (title or "Untitled Notebook").strip()[:180] or "Untitled Notebook"
        state = self.backend.get_server_state(user)
        if not (state.running and state.ready):
            if wait_for_server:
                self.ensure_server_ready(user)
            else:
                self.ensure_server_ready(user, timeout=settings.notebook_start_timeout_seconds)

        existing = self._existing_file_names(user) | self._remote_file_names(user)
        file_name = unique_file_name(title, existing)

        notebook_id = uuid.uuid4()
        document = notebook or build_notebook(title=title, cells=cells or [], metadata=metadata)
        document = dict(document)
        doc_metadata = dict(document.get("metadata") or {})
        opencs = dict(doc_metadata.get("opencs") or {})
        opencs.setdefault("notebook_id", str(notebook_id))
        opencs.setdefault("state_version", 0)
        opencs.setdefault("api_base", settings.public_api_base)
        doc_metadata["opencs"] = opencs
        document["metadata"] = doc_metadata

        model = {"type": "notebook", "format": "json", "content": document}
        try:
            self.backend.contents_put(user, file_name, model)
        except (UpstreamUnavailable, FileNotFoundError) as exc:
            raise UpstreamUnavailable(
                "Could not save the notebook into your workspace",
                details={"reason": str(exc)},
            ) from exc

        notebook_row = Notebook(
            id=notebook_id,
            user_id=user.id,
            title=title,
            file_name=file_name,
            kind=kind,
            source_ref=source_ref,
            environment_image=settings.environment_image,
            last_opened_at=utcnow(),
        )
        self.db.add(notebook_row)
        self.db.commit()
        self.db.refresh(notebook_row)
        return notebook_row

    def list_owned(self, user: User, *, sync: bool = True) -> list[Notebook]:
        if sync:
            self._sync_remote_notebooks(user)
        return list(
            self.db.scalars(
                select(Notebook)
                # Uploaded turn-ins are storage-only (no workspace file).
                .where(Notebook.user_id == user.id, Notebook.kind != "upload")
                .order_by(Notebook.updated_at.desc())
            )
        )

    def _sync_remote_notebooks(self, user: User) -> None:
        """Register .ipynb files created directly in JupyterLab."""
        state = self.backend.get_server_state(user)
        if not (state.running and state.ready):
            return
        try:
            entries = self.backend.contents_list(user, "")
        except (UpstreamUnavailable, FileNotFoundError):
            return
        known = self._existing_file_names(user)
        changed = False
        for entry in entries:
            if entry.get("type") != "notebook":
                continue
            name = entry.get("name", "")
            if name in known:
                continue
            try:
                validate_file_name(name)
            except ValueError:
                continue
            self.db.add(
                Notebook(
                    user_id=user.id,
                    title=entry.get("name", "Notebook").removesuffix(".ipynb"),
                    file_name=name,
                    kind="personal",
                    environment_image=settings.environment_image,
                )
            )
            changed = True
        if changed:
            self.db.commit()

    def open(self, user: User, notebook_id: str) -> tuple[Notebook, str]:
        notebook = self.get_owned(user, notebook_id)
        self.ensure_server_ready(user)
        notebook.last_opened_at = utcnow()
        self.db.commit()
        return notebook, self.backend.open_url(user, notebook.file_name)

    def rename(self, user: User, notebook_id: str, new_title: str) -> Notebook:
        notebook = self.get_owned(user, notebook_id)
        new_title = (new_title or "").strip()[:180]
        if not new_title:
            raise ApiError("INVALID_TITLE", "Notebook title cannot be empty")

        state = self.backend.get_server_state(user)
        existing = self._existing_file_names(user) - {notebook.file_name}
        new_file = unique_file_name(new_title, existing)
        if new_file != notebook.file_name:
            if state.running and state.ready:
                try:
                    self.backend.contents_rename(user, notebook.file_name, new_file)
                except FileNotFoundError:
                    logger.warning("notebook file missing during rename: %s", notebook.file_name)
                except UpstreamUnavailable as exc:
                    raise UpstreamUnavailable(
                        "The notebook server is unavailable; rename was not applied",
                        details={"reason": str(exc)},
                    ) from exc
            notebook.file_name = new_file
        notebook.title = new_title
        notebook.updated_at = utcnow()
        self.db.commit()
        self.db.refresh(notebook)
        return notebook

    def delete(self, user: User, notebook_id: str) -> None:
        notebook = self.get_owned(user, notebook_id)
        state = self.backend.get_server_state(user)
        if state.running and state.ready:
            try:
                self.backend.contents_delete(user, notebook.file_name)
            except FileNotFoundError:
                pass
            except UpstreamUnavailable as exc:
                raise UpstreamUnavailable(
                    "The notebook server is unavailable; the file was not deleted",
                    details={"reason": str(exc)},
                ) from exc
        self.db.delete(notebook)
        self.db.commit()

    def download(self, user: User, notebook_id: str) -> tuple[Notebook, dict[str, Any]]:
        notebook = self.get_owned(user, notebook_id)
        try:
            model = self.backend.contents_get(user, notebook.file_name)
        except FileNotFoundError as exc:
            raise NotFound("notebook file") from exc
        content = model.get("content")
        if not isinstance(content, dict):
            raise Conflict("NOTEBOOK_UNAVAILABLE", "Notebook content is not available")
        return notebook, content

    def read_for_grading(self, user: User, notebook: Notebook) -> dict[str, Any]:
        try:
            model = self.backend.contents_get(user, notebook.file_name)
        except FileNotFoundError as exc:
            raise NotFound("notebook file") from exc
        content = model.get("content")
        if not isinstance(content, dict):
            raise Conflict("NOTEBOOK_UNAVAILABLE", "Notebook has no readable content")
        return content

    def _load_notebook(self, notebook_id: str) -> Notebook:
        try:
            notebook_uuid = uuid.UUID(str(notebook_id))
        except ValueError as exc:
            raise NotFound("notebook", str(notebook_id)) from exc
        notebook = self.db.get(Notebook, notebook_uuid)
        if notebook is None:
            raise NotFound("notebook")
        return notebook

    def _is_course_staff_for_notebook(self, user: User, notebook: Notebook) -> bool:
        if user.role == "admin":
            return True
        from app.courses.models import Enrollment
        from app.grading.models import Assignment, Submission

        role = self.db.scalar(
            select(Enrollment.role_in_course)
            .join(Assignment, Assignment.course_id == Enrollment.course_id)
            .join(Submission, Submission.assignment_id == Assignment.id)
            .where(
                Submission.notebook_id == notebook.id,
                Enrollment.user_id == user.id,
            )
            .limit(1)
        )
        return role in ("ta", "instructor", "staff")

    def get_viewable(self, user: User, notebook_id: str) -> Notebook:
        notebook = self._load_notebook(notebook_id)
        if notebook.user_id == user.id or self._is_course_staff_for_notebook(user, notebook):
            return notebook
        raise NotFound("notebook")

    # -- snapshots and active state ---------------------------------------
    def snapshot_working_copy(
        self,
        user: User,
        notebook: Notebook,
        *,
        kind: str = "autosave",
        actor_id: uuid.UUID | None = None,
        commit: bool = True,
    ):
        document = self.read_for_grading(user, notebook)
        service = NotebookVersionService(self.db)
        return service.create_version(
            notebook,
            document,
            kind=kind,
            actor_id=actor_id or user.id,
            commit=commit,
        )

    def autosave(
        self, user: User, notebook_id: str, *, base_version: int, document: dict[str, Any]
    ) -> dict[str, Any]:
        notebook = self.get_owned(user, notebook_id)
        try:
            document = validate_document(document)
        except ValueError as exc:
            raise ApiError(
                "INVALID_NOTEBOOK",
                str(exc),
                status_code=422,
                details={"reason": str(exc)},
            ) from exc

        sha256 = hashlib.sha256(canonical_bytes(document)).hexdigest()
        if notebook.content_sha256 == sha256:
            # The watcher or a previous request already stored this exact
            # document. That is a successful no-op even if the client's
            # base_version is stale.
            return {
                "version": int(notebook.edit_version or 0),
                "saved": False,
                "sha256": sha256,
                "saved_at": notebook.last_saved_at,
            }

        if int(base_version) != int(notebook.edit_version or 0):
            raise Conflict(
                "VERSION_CONFLICT",
                "The notebook was saved by another client; reload the latest version",
                details={
                    "current_version": int(notebook.edit_version or 0),
                    "latest_sha256": notebook.content_sha256,
                },
            )

        version, created = NotebookVersionService(self.db).create_version(
            notebook, document, kind="autosave", actor_id=user.id
        )
        return {
            "version": int(notebook.edit_version or 0),
            "saved": created,
            "sha256": sha256,
            "saved_at": notebook.last_saved_at,
            "version_number": version.version_number if version else None,
        }

    def heartbeat(self, user: User, notebook_id: str, *, client: str = "jupyterlab") -> dict[str, Any]:
        notebook = self.get_owned(user, notebook_id)
        now = utcnow()
        session = self.db.scalar(
            select(NotebookSession)
            .where(
                NotebookSession.notebook_id == notebook.id,
                NotebookSession.user_id == user.id,
                NotebookSession.ended_at.is_(None),
            )
            .order_by(NotebookSession.last_seen_at.desc())
            .limit(1)
        )
        if session is not None:
            last_seen = ensure_utc(session.last_seen_at)
            idle_cutoff = now - dt.timedelta(seconds=settings.session_idle_seconds)
            if last_seen is not None and last_seen >= idle_cutoff:
                session.last_seen_at = now
            else:
                session.ended_at = now
                session = None
        if session is None:
            session = NotebookSession(
                notebook_id=notebook.id,
                user_id=user.id,
                client=client,
                started_at=now,
                last_seen_at=now,
            )
            self.db.add(session)
        notebook.last_activity_at = now
        self.db.commit()
        self.db.refresh(session)
        return {
            "version": int(notebook.edit_version or 0),
            "last_saved_at": notebook.last_saved_at,
            "session_id": session.id,
        }

    def watch_snapshot(self, user: User, notebook: Notebook) -> bool:
        """Backstop used by the watcher: snapshot the file if it changed."""
        try:
            document = self.read_for_grading(user, notebook)
        except (NotFound, Conflict, UpstreamUnavailable, FileNotFoundError):
            return False
        sha256 = hashlib.sha256(canonical_bytes(document)).hexdigest()
        if notebook.content_sha256 == sha256:
            notebook.last_activity_at = utcnow()
            self.db.commit()
            return False
        NotebookVersionService(self.db).create_version(
            notebook, document, kind="autosave", actor_id=user.id
        )
        return True

    # -- version history ---------------------------------------------------
    def list_versions(
        self, user: User, notebook_id: str, *, kind: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        notebook = self.get_viewable(user, notebook_id)
        return NotebookVersionService(self.db).list_versions(
            notebook.id, kind=kind, limit=limit
        )

    def download_version(
        self, user: User, notebook_id: str, version_number: int
    ) -> tuple[Notebook, dict[str, Any], dict[str, Any]]:
        notebook = self.get_viewable(user, notebook_id)
        version, document = NotebookVersionService(self.db).load_version(
            notebook.id, version_number
        )
        return (
            notebook,
            {
                "version_number": version.version_number,
                "kind": version.kind,
                "sha256": version.blob_sha256,
                "created_at": version.created_at,
            },
            document,
        )


def notebook_last_modified(notebook: Notebook) -> dt.datetime:
    return notebook.updated_at or notebook.created_at
