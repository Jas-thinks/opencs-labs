"""Notebook server backend abstraction.

JupyterHub is authoritative for server lifecycle. This module is the single
seam through which the application reaches it, which keeps tests fast (a fake
backend is injected) without duplicating notebook lifecycle logic.
"""

from __future__ import annotations

from typing import Any, Protocol

from app.core.config import settings
from app.core.errors import UpstreamUnavailable
from app.integrations.jupyterhub import HubClient, ServerState, get_hub_client
from app.users.models import User


class NotebookBackend(Protocol):
    def get_server_state(self, user: User) -> ServerState: ...

    def start_server(self, user: User, options: dict[str, Any] | None = None) -> ServerState: ...

    def stop_server(self, user: User) -> None: ...

    def open_url(self, user: User, file_name: str | None = None) -> str: ...

    def contents_get(self, user: User, path: str) -> dict[str, Any]: ...

    def contents_put(self, user: User, path: str, model: dict[str, Any]) -> dict[str, Any]: ...

    def contents_list(self, user: User, path: str = "") -> list[dict[str, Any]]: ...

    def contents_delete(self, user: User, path: str) -> None: ...

    def contents_rename(self, user: User, old_path: str, new_path: str) -> None: ...

    def active_session_count(self) -> int: ...


class HubNotebookBackend:
    def __init__(self, hub: HubClient | None = None) -> None:
        self.hub = hub or get_hub_client()

    def get_server_state(self, user: User) -> ServerState:
        return self.hub.get_server_state(user.hub_username)

    def start_server(self, user: User, options: dict[str, Any] | None = None) -> ServerState:
        return self.hub.start_server(user.hub_username, options)

    def stop_server(self, user: User) -> None:
        self.hub.stop_server(user.hub_username)

    def open_url(self, user: User, file_name: str | None = None) -> str:
        return self.hub.open_url(user.hub_username, file_name)

    def contents_get(self, user: User, path: str) -> dict[str, Any]:
        return self.hub.contents_get(user.hub_username, path)

    def contents_put(self, user: User, path: str, model: dict[str, Any]) -> dict[str, Any]:
        return self.hub.contents_put(user.hub_username, path, model)

    def contents_list(self, user: User, path: str = "") -> list[dict[str, Any]]:
        return self.hub.contents_list(user.hub_username, path)

    def contents_delete(self, user: User, path: str) -> None:
        self.hub.contents_delete(user.hub_username, path)

    def contents_rename(self, user: User, old_path: str, new_path: str) -> None:
        self.hub.contents_rename(user.hub_username, old_path, new_path)

    def active_session_count(self) -> int:
        return len(self.hub.list_active_users())


class DisabledNotebookBackend:
    """Used when the notebook service is not configured.

    Every operation fails loudly; the platform never pretends a notebook was
    created or saved when no execution backend exists.
    """

    def _unavailable(self) -> None:
        raise UpstreamUnavailable(
            "Notebook execution is not configured on this deployment",
            details={"hint": "set OPENCE_NOTEBOOK_BACKEND=hub and configure JupyterHub"},
        )

    def get_server_state(self, user: User) -> ServerState:
        self._unavailable()
        raise AssertionError  # pragma: no cover

    def start_server(self, user: User, options: dict[str, Any] | None = None) -> ServerState:
        self._unavailable()
        raise AssertionError  # pragma: no cover

    def stop_server(self, user: User) -> None:
        self._unavailable()

    def open_url(self, user: User, file_name: str | None = None) -> str:
        self._unavailable()
        raise AssertionError  # pragma: no cover

    def contents_get(self, user: User, path: str) -> dict[str, Any]:
        self._unavailable()
        raise AssertionError  # pragma: no cover

    def contents_put(self, user: User, path: str, model: dict[str, Any]) -> dict[str, Any]:
        self._unavailable()
        raise AssertionError  # pragma: no cover

    def contents_list(self, user: User, path: str = "") -> list[dict[str, Any]]:
        self._unavailable()
        raise AssertionError  # pragma: no cover

    def contents_delete(self, user: User, path: str) -> None:
        self._unavailable()

    def contents_rename(self, user: User, old_path: str, new_path: str) -> None:
        self._unavailable()

    def active_session_count(self) -> int:
        self._unavailable()
        raise AssertionError  # pragma: no cover


_backend: NotebookBackend | None = None


def get_notebook_backend() -> NotebookBackend:
    global _backend
    if _backend is None:
        if settings.notebook_backend == "hub":
            _backend = HubNotebookBackend()
        else:
            _backend = DisabledNotebookBackend()
    return _backend
