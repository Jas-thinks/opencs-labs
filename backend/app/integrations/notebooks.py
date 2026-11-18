"""Notebook server backend abstraction.

JupyterHub is authoritative for server lifecycle. This module is the single
seam through which the application reaches it, which keeps tests fast (a fake
backend is injected) without duplicating notebook lifecycle logic.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import quote

from app.core.config import settings
from app.core.errors import UpstreamUnavailable
from app.integrations.jupyterhub import (
    HubClient,
    ServerState,
    get_hub_shards,
    hub_client_for,
)
from app.notebooks.ipynb import NOTEBOOK_SUFFIX, validate_file_name
from app.users.models import User

logger = logging.getLogger("opencs.notebooks.local")


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
    """Routes each user to their Hub.

    With ``OPENCE_JUPYTERHUB_SHARDS`` set, a user is pinned to one of several
    independent Hubs (see ``jupyterhub.shard_index``). Passing ``hub`` pins every
    user to that one client, which is what the tests and single-Hub deployments do.
    """

    def __init__(self, hub: HubClient | None = None) -> None:
        self._fixed = hub
        self.hub = hub or get_hub_shards()[0]

    def _hub(self, user: User) -> HubClient:
        return self._fixed or hub_client_for(user.hub_username)

    def get_server_state(self, user: User) -> ServerState:
        return self._hub(user).get_server_state(user.hub_username)

    def start_server(self, user: User, options: dict[str, Any] | None = None) -> ServerState:
        return self._hub(user).start_server(user.hub_username, options)

    def stop_server(self, user: User) -> None:
        self._hub(user).stop_server(user.hub_username)

    def open_url(self, user: User, file_name: str | None = None) -> str:
        return self._hub(user).open_url(user.hub_username, file_name)

    def contents_get(self, user: User, path: str) -> dict[str, Any]:
        return self._hub(user).contents_get(user.hub_username, path)

    def contents_put(self, user: User, path: str, model: dict[str, Any]) -> dict[str, Any]:
        return self._hub(user).contents_put(user.hub_username, path, model)

    def contents_list(self, user: User, path: str = "") -> list[dict[str, Any]]:
        return self._hub(user).contents_list(user.hub_username, path)

    def contents_delete(self, user: User, path: str) -> None:
        self._hub(user).contents_delete(user.hub_username, path)

    def contents_rename(self, user: User, old_path: str, new_path: str) -> None:
        self._hub(user).contents_rename(user.hub_username, old_path, new_path)

    def active_session_count(self) -> int:
        hubs = [self._fixed] if self._fixed else get_hub_shards()
        total = 0
        for hub in hubs:
            try:
                total += len(hub.list_active_users())
            except UpstreamUnavailable:
                # One unreachable shard must not block launches on the others;
                # its users fail on their own requests instead.
                logger.warning("hub shard %s unreachable while counting sessions", hub.name)
        return total


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


class LocalNotebookBackend:
    """Host-process notebook backend for local development.

    One JupyterLab server is spawned on demand and rooted at
    ``local_notebooks_dir``; each user's notebooks live in a subdirectory.
    Contents are read and written directly on the filesystem, so the backend
    does not need Jupyter's REST API (or a token) to create notebooks.

    There is no per-user isolation: every notebook server, kernel and the
    backend run as the same macOS user.
    """

    def __init__(self) -> None:
        self.root = Path(settings.local_notebooks_dir).expanduser().resolve()
        self.host = settings.local_notebook_host
        self.port = settings.local_notebook_port
        self.python = settings.local_notebook_python or sys.executable
        self._process: subprocess.Popen | None = None
        self._lock = threading.Lock()

    # -- helpers ---------------------------------------------------------
    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def _user_dir(self, user: User) -> Path:
        raw = user.hub_username or str(user.id)
        name = re.sub(r"[^A-Za-z0-9._-]", "_", raw).strip("._") or "user"
        return self.root / name

    def _probe(self) -> bool:
        try:
            with urllib.request.urlopen(f"{self.base_url}/lab", timeout=1.5) as response:
                return 200 <= response.status < 400
        except urllib.error.HTTPError as exc:
            # 401/403 still proves a Jupyter server is listening.
            return exc.code in (200, 302, 401, 403)
        except Exception:  # noqa: BLE001 - connection refused, timeout, DNS
            return False

    def _log_path(self) -> Path:
        return self.root / "jupyterlab.log"

    def _path(self, user: User, file_name: str) -> Path:
        return self._user_dir(user) / validate_file_name(file_name)

    @staticmethod
    def _model(path: Path, content: dict[str, Any]) -> dict[str, Any]:
        return {
            "type": "notebook",
            "format": "json",
            "name": path.name,
            "path": path.name,
            "content": content,
        }

    # -- lifecycle -------------------------------------------------------
    def get_server_state(self, user: User) -> ServerState:
        if self._probe():
            return ServerState(running=True, ready=True, url=f"{self.base_url}/lab")
        return ServerState(running=False, ready=False)

    def start_server(self, user: User, options: dict[str, Any] | None = None) -> ServerState:
        with self._lock:
            if self._probe():
                return ServerState(running=True, ready=True, url=f"{self.base_url}/lab")

            if self._process is None or self._process.poll() is not None:
                self.root.mkdir(parents=True, exist_ok=True)
                self._user_dir(user).mkdir(parents=True, exist_ok=True)
                command = [
                    self.python,
                    "-m",
                    "jupyterlab",
                    "--no-browser",
                    f"--ip={self.host}",
                    f"--port={self.port}",
                    f"--ServerApp.root_dir={self.root}",
                    "--ServerApp.token=",
                    "--ServerApp.password=",
                ]
                log = open(self._log_path(), "a", encoding="utf-8")  # noqa: SIM115
                try:
                    self._process = subprocess.Popen(  # noqa: S603 - admin-configured binary
                        command,
                        stdout=log,
                        stderr=subprocess.STDOUT,
                        cwd=str(self.root),
                        start_new_session=True,
                    )
                except OSError as exc:
                    log.close()
                    raise UpstreamUnavailable(
                        "Could not start the local JupyterLab server",
                        details={
                            "python": self.python,
                            "reason": str(exc),
                            "hint": "set OPENCE_LOCAL_NOTEBOOK_PYTHON to the notebook venv python",
                        },
                    ) from exc
                finally:
                    log.close()

            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                if self._process is not None and self._process.poll() is not None:
                    break
                if self._probe():
                    return ServerState(running=True, ready=True, url=f"{self.base_url}/lab")
                time.sleep(0.5)

            raise UpstreamUnavailable(
                "The local JupyterLab server did not become ready",
                details={
                    "python": self.python,
                    "port": self.port,
                    "log": str(self._log_path()),
                },
            )

    def stop_server(self, user: User) -> None:
        with self._lock:
            process = self._process
            if process is None or process.poll() is not None:
                logger.warning("no locally spawned JupyterLab process to stop")
                return
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            self._process = None

    def open_url(self, user: User, file_name: str | None = None) -> str:
        base = f"{self.base_url}/lab/tree/{quote(self._user_dir(user).name)}"
        if file_name:
            return f"{base}/{quote(file_name)}"
        return base

    # -- contents --------------------------------------------------------
    def contents_get(self, user: User, path: str) -> dict[str, Any]:
        file_path = self._path(user, path)
        if not file_path.is_file():
            raise FileNotFoundError(path)
        content = json.loads(file_path.read_text(encoding="utf-8"))
        return self._model(file_path, content)

    def contents_put(self, user: User, path: str, model: dict[str, Any]) -> dict[str, Any]:
        file_path = self._path(user, path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        content = model.get("content") or {}
        file_path.write_text(json.dumps(content, indent=1, ensure_ascii=False), encoding="utf-8")
        return self._model(file_path, content)

    def contents_list(self, user: User, path: str = "") -> list[dict[str, Any]]:
        directory = self._user_dir(user)
        if not directory.is_dir():
            return []
        entries: list[dict[str, Any]] = []
        for item in sorted(directory.iterdir(), key=lambda p: p.name.lower()):
            if item.is_file() and item.name.endswith(NOTEBOOK_SUFFIX):
                entries.append(
                    {
                        "type": "notebook",
                        "name": item.name,
                        "path": item.name,
                        "format": "json",
                    }
                )
        return entries

    def contents_delete(self, user: User, path: str) -> None:
        file_path = self._path(user, path)
        if not file_path.is_file():
            raise FileNotFoundError(path)
        file_path.unlink()

    def contents_rename(self, user: User, old_path: str, new_path: str) -> None:
        source = self._path(user, old_path)
        destination = self._path(user, new_path)
        if not source.is_file():
            raise FileNotFoundError(old_path)
        os.replace(source, destination)

    def active_session_count(self) -> int:
        return 1 if self._probe() else 0


_backend: NotebookBackend | None = None


def get_notebook_backend() -> NotebookBackend:
    global _backend
    if _backend is None:
        if settings.notebook_backend == "hub":
            _backend = HubNotebookBackend()
        elif settings.notebook_backend == "local":
            _backend = LocalNotebookBackend()
        else:
            _backend = DisabledNotebookBackend()
    return _backend
