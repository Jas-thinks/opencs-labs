"""Client for the JupyterHub REST API.

Only the backend holds the Hub admin token. Browser clients never receive Hub
tokens; notebook access is granted through the JupyterHub session cookie that
is established by the Hub's OpenCS authenticator.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import settings
from app.core.errors import CapacityExhausted, UpstreamUnavailable

logger = logging.getLogger("opencs.jupyterhub")


@dataclass(slots=True)
class ServerState:
    running: bool
    ready: bool
    pending: str | None = None
    url: str | None = None
    started_at: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "running": self.running,
            "ready": self.ready,
            "status": "running" if self.ready else ("starting" if self.running or self.pending else "stopped"),
            "pending": self.pending,
            "url": self.url,
        }


class HubClient:
    def __init__(
        self,
        api_url: str | None = None,
        token: str | None = None,
        public_url: str | None = None,
        timeout: float = 20.0,
    ) -> None:
        self.api_url = (api_url or settings.jupyterhub_api_url).rstrip("/")
        self.token = token if token is not None else settings.jupyterhub_api_token
        self.public_url = (public_url or settings.jupyterhub_public_url).rstrip("/")
        self.timeout = timeout
        self._token_cache: dict[tuple[str, str], tuple[str, float]] = {}
        self._lock = threading.Lock()

    # -- low level -----------------------------------------------------
    def _client(self) -> httpx.Client:
        headers = {"Authorization": f"token {self.token}"} if self.token else {}
        return httpx.Client(base_url=self.api_url, headers=headers, timeout=self.timeout)

    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        if not self.token:
            raise UpstreamUnavailable(
                "JupyterHub API token is not configured on the backend",
                details={"hint": "set OPENCE_JUPYTERHUB_API_TOKEN"},
            )
        try:
            with self._client() as client:
                return client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise UpstreamUnavailable(
                "JupyterHub is unreachable", details={"reason": str(exc)}
            ) from exc

    # -- users / servers ------------------------------------------------
    def ensure_user(self, username: str) -> None:
        response = self._request("POST", "/users", json={"usernames": [username]})
        if response.status_code not in (200, 201, 409):
            self._raise(response, "create hub user")

    def get_user(self, username: str) -> dict[str, Any] | None:
        response = self._request("GET", f"/users/{username}")
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            self._raise(response, "read hub user")
        return response.json()

    def get_server_state(self, username: str) -> ServerState:
        user = self.get_user(username)
        if not user:
            return ServerState(running=False, ready=False)

        # JupyterHub 4 exposes the default server two ways:
        #   "server":  "/user/<name>/"   (a URL string, for convenience)
        #   "servers": {"": {..., "ready": true, "pending": null, "url": ...}}
        # The ready/pending/started fields only exist in `servers[""]`, so
        # reading "server" as an object loses them (and used to raise
        # AttributeError during a launch).
        servers = user.get("servers")
        default_server: dict[str, Any] | None = None
        if isinstance(servers, dict):
            candidate = servers.get("")
            if isinstance(candidate, dict):
                default_server = candidate

        if default_server is None:
            legacy = user.get("server")
            if isinstance(legacy, dict):
                default_server = legacy
            elif isinstance(legacy, str) and legacy:
                # A URL with no detail object: running, readiness unknown.
                return ServerState(running=True, ready=False, url=legacy)
            else:
                return ServerState(running=False, ready=False)

        if not isinstance(default_server, dict):
            return ServerState(running=False, ready=False)
        return ServerState(
            running=True,
            ready=bool(default_server.get("ready")),
            pending=default_server.get("pending"),
            url=default_server.get("url"),
            started_at=default_server.get("started"),
        )

    def start_server(self, username: str, options: dict[str, Any] | None = None) -> ServerState:
        self.ensure_user(username)
        payload: dict[str, Any] = {}
        if options:
            payload.update(options)
        response = self._request("POST", f"/users/{username}/server", json=payload)
        if response.status_code in (201, 202):
            return self.get_server_state(username)
        if response.status_code == 400 and "already running" in response.text.lower():
            return self.get_server_state(username)
        if response.status_code == 429:
            raise CapacityExhausted(
                "Notebook capacity is temporarily exhausted. Please retry shortly.",
                details={"retry_after_seconds": 30},
            )
        if response.status_code == 409:
            return self.get_server_state(username)
        self._raise(response, "start notebook server")

    def stop_server(self, username: str) -> None:
        response = self._request("DELETE", f"/users/{username}/server")
        if response.status_code not in (202, 204, 404):
            self._raise(response, "stop notebook server")

    def list_active_users(self) -> list[dict[str, Any]]:
        response = self._request("GET", "/users", params={"state": "active"})
        if response.status_code != 200:
            self._raise(response, "list hub users")
        data = response.json()
        return data if isinstance(data, list) else []

    # -- user server API -------------------------------------------------
    def user_token(self, username: str) -> str:
        """Mint a scoped token for talking to one user's notebook server.

        The token is cached in the backend process only and never returned to
        a browser.
        """
        cache_key = (username, "access:servers")
        now = time.time()
        with self._lock:
            cached = self._token_cache.get(cache_key)
            if cached and cached[1] > now + 60:
                return cached[0]
        payload = {
            "expires_in": 3600,
            "note": "opencs-backend server API",
            "scopes": [f"access:servers!user={username}"],
        }
        response = self._request("POST", f"/users/{username}/tokens", json=payload)
        if response.status_code not in (200, 201):
            self._raise(response, "mint scoped hub token")
        token = response.json()["token"]
        with self._lock:
            self._token_cache[cache_key] = (token, now + 3600)
        return token

    def _user_client(self, username: str) -> httpx.Client:
        token = self.user_token(username)
        return httpx.Client(
            base_url=f"{settings.hub_proxy_url}/user/{username}",
            headers={"Authorization": f"token {token}"},
            timeout=self.timeout,
        )

    def _mutating_client(self, username: str) -> httpx.Client:
        """Kept as an alias because writes have a distinct reason to exist.

        A request authenticated with a Hub-minted token is exempt from the
        single-user server's XSRF check, so no ``_xsrf`` cookie or header is
        needed. Sending a *mismatched* header is what breaks it ("XSRF cookie
        does not match PUT argument"), so this deliberately adds none.
        """
        return self._user_client(username)

    def contents_get(self, username: str, path: str) -> dict[str, Any]:
        with self._user_client(username) as client:
            response = client.get(f"/api/contents/{path}", params={"content": "1"})
        if response.status_code == 404:
            raise FileNotFoundError(path)
        if response.status_code != 200:
            self._raise(response, "read notebook contents")
        return response.json()

    def contents_put(self, username: str, path: str, model: dict[str, Any]) -> dict[str, Any]:
        with self._user_client(username) as client:
            response = client.put(f"/api/contents/{path}", json=model)
        if response.status_code not in (200, 201):
            self._raise(response, "write notebook contents")
        return response.json()

    def contents_list(self, username: str, path: str = "") -> list[dict[str, Any]]:
        with self._user_client(username) as client:
            response = client.get(f"/api/contents/{path}", params={"content": "1"})
        if response.status_code == 404:
            return []
        if response.status_code != 200:
            self._raise(response, "list notebook contents")
        payload = response.json()
        if payload.get("type") != "directory":
            return []
        return payload.get("content", [])

    def contents_delete(self, username: str, path: str) -> None:
        with self._user_client(username) as client:
            response = client.delete(f"/api/contents/{path}")
        if response.status_code not in (204, 404):
            self._raise(response, "delete notebook contents")

    def contents_rename(self, username: str, old_path: str, new_path: str) -> None:
        with self._user_client(username) as client:
            response = client.patch(f"/api/contents/{old_path}", json={"path": new_path})
        if response.status_code not in (200, 201):
            self._raise(response, "rename notebook contents")

    # -- helpers ---------------------------------------------------------
    def open_url(self, username: str, file_name: str | None = None) -> str:
        base = f"{self.public_url}/user/{username}/lab"
        if file_name:
            from urllib.parse import quote

            return f"{base}/tree/{quote(file_name)}"
        return f"{base}/tree"

    @staticmethod
    def _raise(response: httpx.Response, action: str) -> None:
        detail = response.text[:500]
        logger.warning("hub %s failed: %s %s", action, response.status_code, detail)
        if response.status_code in (401, 403):
            raise UpstreamUnavailable(
                "The backend is not authorised to manage notebook servers",
                details={"status": response.status_code},
            )
        if response.status_code == 429:
            raise CapacityExhausted("Notebook capacity is temporarily exhausted.")
        raise UpstreamUnavailable(
            f"JupyterHub could not {action}", details={"status": response.status_code}
        )


_hub_client: HubClient | None = None
_hub_lock = threading.Lock()


def get_hub_client() -> HubClient:
    global _hub_client
    with _hub_lock:
        if _hub_client is None:
            _hub_client = HubClient()
        return _hub_client
