"""Test doubles for external systems.

These replace only the infrastructure seam (JupyterHub and the grading
sandbox). API authorization, ownership checks, serialisation and storage
metadata logic still run for real.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from app.integrations.grader import GradeResult, GradeTest
from app.integrations.jupyterhub import ServerState
from app.notebooks.ipynb import validate_file_name
from app.users.models import User


class FakeNotebookBackend:
    def __init__(self) -> None:
        self.servers: dict[str, ServerState] = {}
        self.files: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
        self.started: list[str] = []
        self.stopped: list[str] = []

    def get_server_state(self, user: User) -> ServerState:
        return self.servers.get(
            user.hub_username, ServerState(running=True, ready=True, url=f"/user/{user.hub_username}/")
        )

    def start_server(self, user: User, options: dict[str, Any] | None = None) -> ServerState:
        self.started.append(user.hub_username)
        state = ServerState(
            running=True, ready=True, url=f"/user/{user.hub_username}/", started_at="now"
        )
        self.servers[user.hub_username] = state
        return state

    def stop_server(self, user: User) -> None:
        self.stopped.append(user.hub_username)
        self.servers[user.hub_username] = ServerState(running=False, ready=False)

    def open_url(self, user: User, file_name: str | None = None) -> str:
        base = f"http://hub.test/user/{user.hub_username}/lab"
        return f"{base}/tree/{file_name}" if file_name else f"{base}/tree"

    def contents_get(self, user: User, path: str) -> dict[str, Any]:
        files = self.files[user.hub_username]
        if path not in files:
            raise FileNotFoundError(path)
        return {"type": "notebook", "format": "json", "content": files[path]}

    def contents_put(self, user: User, path: str, model: dict[str, Any]) -> dict[str, Any]:
        validate_file_name(path)
        self.files[user.hub_username][path] = model["content"]
        return {"type": "notebook", "path": path}

    def contents_list(self, user: User, path: str = "") -> list[dict[str, Any]]:
        return [
            {"name": name, "type": "notebook", "path": name}
            for name in sorted(self.files[user.hub_username])
        ]

    def contents_delete(self, user: User, path: str) -> None:
        files = self.files[user.hub_username]
        if path not in files:
            raise FileNotFoundError(path)
        del files[path]

    def contents_rename(self, user: User, old_path: str, new_path: str) -> None:
        files = self.files[user.hub_username]
        if old_path not in files:
            raise FileNotFoundError(old_path)
        validate_file_name(new_path)
        files[new_path] = files.pop(old_path)

    def active_session_count(self) -> int:
        running = sum(1 for state in self.servers.values() if state.running)
        return max(running, 1)

    # test helpers
    def file_count(self, user: User) -> int:
        return len(self.files[user.hub_username])


class FakeGrader:
    def __init__(self, passed: bool = True) -> None:
        self.passed = passed
        self.calls = 0

    def evaluate(self, notebook: dict[str, Any], evaluation: dict[str, Any]) -> GradeResult:
        self.calls += 1
        tests = [
            GradeTest(
                id=item.get("id", "check"),
                description=item.get("description", ""),
                passed=self.passed,
                message="" if self.passed else "assertion failed",
            )
            for item in evaluation.get("tests", [])
        ]
        return GradeResult(
            passed=self.passed,
            score=1.0 if self.passed else 0.0,
            tests=tests,
            duration_seconds=0.01,
        )

    def available(self) -> bool:
        return True
