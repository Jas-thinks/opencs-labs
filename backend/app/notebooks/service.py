"""Notebook metadata + Jupyter storage orchestration.

Every operation resolves storage through the authenticated owner. A browser
never supplies a filesystem path that is used directly.
"""

from __future__ import annotations

import datetime as dt
import logging
import time
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import ApiError, CapacityExhausted, Conflict, NotFound, UpstreamUnavailable
from app.db.base import utcnow
from app.integrations.jupyterhub import ServerState
from app.integrations.notebooks import NotebookBackend, get_notebook_backend
from app.notebooks.ipynb import build_notebook, unique_file_name, validate_file_name
from app.notebooks.models import Notebook
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

        document = notebook or build_notebook(title=title, cells=cells or [], metadata=metadata)
        model = {"type": "notebook", "format": "json", "content": document}
        try:
            self.backend.contents_put(user, file_name, model)
        except (UpstreamUnavailable, FileNotFoundError) as exc:
            raise UpstreamUnavailable(
                "Could not save the notebook into your workspace",
                details={"reason": str(exc)},
            ) from exc

        notebook_row = Notebook(
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
                .where(Notebook.user_id == user.id)
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


def notebook_last_modified(notebook: Notebook) -> dt.datetime:
    return notebook.updated_at or notebook.created_at
