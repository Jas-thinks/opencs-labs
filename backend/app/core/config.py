"""Application configuration loaded from environment variables.

All configuration is environment driven. Defaults are development-safe and
never contain production secrets.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _find_env_file() -> Path | None:
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / ".env"
        if candidate.is_file():
            return candidate
    return None


REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="OPENCE_",
        env_file=_find_env_file(),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: Literal["development", "production", "test"] = "development"
    debug: bool = False

    # --- telemetry -------------------------------------------------------
    # Friendly identity reported by /telemetry and shown on the cluster dashboard.
    node_name: str = "opencs-node"
    node_role: Literal["central", "backend", "jupyter", "database", "worker"] = "backend"

    # --- session / security ---------------------------------------------
    jwt_secret: str = "dev-only-insecure-secret-change-me"
    jwt_issuer: str = "opencs"
    jwt_algorithm: str = "HS256"
    session_cookie: str = "opencs_session"
    session_ttl_seconds: int = 12 * 60 * 60
    cookie_secure: bool = False
    cookie_domain: str | None = None

    # --- database --------------------------------------------------------
    # Development default is a writable local SQLite file; production sets
    # OPENCE_DATABASE_URL to PostgreSQL.
    database_url: str = "sqlite:///./data/opencs.db"
    test_database_url: str = ""
    db_pool_size: int = 10
    db_max_overflow: int = 20

    # --- urls ------------------------------------------------------------
    public_origin: str = "http://localhost:5173"
    api_prefix: str = "/api/v1"
    # Absolute base the browser/JupyterLab extension should call. Empty means
    # derive it from public_origin + api_prefix (correct behind the Vite dev
    # proxy or a single-origin ingress).
    api_public_base: str = ""
    login_path: str = "/login"
    cors_origins: str = (
        "http://localhost:5173,http://localhost:8000,http://localhost:8888"
    )

    # --- jupyterhub ------------------------------------------------------
    # The Hub REST API lives under /hub/api (hub_api_url).
    jupyterhub_url: str = "http://localhost:8000"
    jupyterhub_api_url: str = "http://localhost:8000/hub/api"
    jupyterhub_api_token: str = ""
    # Base URL of the Hub's *proxy*, used for /user/<name>/ requests. This is a
    # different listener from the API: the proxy (port 8000) serves
    # /user/<name>/, while the Hub API (hub_port, 8081) only serves /hub/api and
    # answers 500 for /user/... paths. Pointing contents calls at the API host is
    # what made every notebook write fail authorisation.
    jupyterhub_proxy_url: str = ""
    jupyterhub_public_url: str = "http://localhost:5173"
    # Multi-Hub sharding. A JSON list; each entry is one independent Hub:
    #   [{"name": "nb0",
    #     "api_url":    "http://10.1.75.79:5221/nb/0/hub/api",   # backend -> Hub API
    #     "proxy_url":  "http://10.1.75.79:5221/nb/0",           # backend -> /user/<name>/
    #     "public_url": "http://10.1.75.53:5305/nb/0",           # browser (via the edge)
    #     "api_token":  "<per-shard service token>"}, ...]
    # A user is pinned to shard sha256(hub_username) % len(shards), so every API
    # node agrees without shared state. Their notebook home lives on that shard:
    # changing the number or order of shards moves users to an empty home.
    # Empty = single Hub configured by the jupyterhub_* settings above.
    jupyterhub_shards: str = ""
    notebook_backend: Literal["hub", "local", "disabled"] = "hub"
    notebook_start_timeout_seconds: int = 120
    # Uploaded .ipynb files (post attachments, turn-in by upload).
    notebook_upload_max_bytes: int = 5 * 1024 * 1024
    dataset_mount_path: str = "/opt/opencs/datasets"
    environment_image: str = "opencs/analytics:1.0.0"
    # Local (host-process) notebook backend: one JupyterLab server rooted at
    # local_notebooks_dir, spawned on first use by the backend.
    local_notebooks_dir: str = str(REPO_ROOT / "backend" / "data" / "local-notebooks")
    local_notebook_python: str = ""
    # ``localhost`` (not 127.0.0.1) so the host-only session cookie set on
    # localhost applies inside JupyterLab too.
    local_notebook_host: str = "localhost"
    local_notebook_port: int = 8888

    # --- object storage --------------------------------------------------
    s3_endpoint: str = ""
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_bucket: str = "opencs-datasets"
    s3_region: str = "us-east-1"
    dataset_serving_dir: str = str(REPO_ROOT / "datasets" / "serving")

    # --- auth ------------------------------------------------------------
    auth_mode: Literal["dev", "oidc"] = "dev"
    oidc_issuer: str = ""
    oidc_client_id: str = ""
    oidc_client_secret: str = ""
    oidc_scopes: str = "openid email profile"

    # --- grading ---------------------------------------------------------
    # docker     = local dev / single-host Compose (needs the Docker socket)
    # kubernetes = production (short-lived batch/v1 Job in the grader namespace)
    grader: Literal["docker", "kubernetes", "local", "disabled"] = "docker"
    grader_image: str = "opencs/analytics:1.0.0"
    grader_timeout_seconds: int = 90
    grader_memory: str = "1g"
    grader_cpus: str = "1"
    # Kubernetes sandbox settings (used only when grader = kubernetes).
    grader_k8s_namespace: str = "opencs-grading"
    grader_dataset_pvc: str = "opencs-datasets"
    # Docker sandbox staging directory. When the backend itself runs in a
    # container and starts sibling containers through the host daemon, a
    # `TemporaryDirectory` path is meaningless to the daemon: the bind mount is
    # resolved on the HOST. Set this to a path that is identical on the host and
    # inside the backend container (Compose bind-mounts it both ways) and the
    # staged notebook/checks are visible to the grading container. Empty =
    # create a plain temp directory (correct when the backend runs on the host).
    grader_staging_dir: str = ""
    # Local (host-process) grader: run grade_runner.py as a subprocess with the
    # notebook environment's Python. No isolation beyond the runner's timeout.
    grade_runner_path: str = str(REPO_ROOT / "notebook-image" / "grade_runner.py")

    # --- rate limiting ---------------------------------------------------
    rate_limit_enabled: bool = True
    rate_limit_launch_per_minute: int = 10
    rate_limit_evaluate_per_minute: int = 6
    rate_limit_autosave_per_minute: int = 12

    # --- capacity --------------------------------------------------------
    max_active_sessions: int = 450

    # --- notebook state / background work --------------------------------
    autosave_retention: int = 20
    session_idle_seconds: int = 300
    watcher_interval_seconds: int = 10
    watcher_active_window_seconds: int = 900
    job_worker_interval_seconds: int = 15
    job_max_attempts: int = 5
    job_stuck_seconds: int = 600
    # Disabled by the test suite so the in-process loops never touch the
    # developer's real database.
    background_workers_enabled: bool = True

    @field_validator("api_prefix")
    @classmethod
    def _normalise_prefix(cls, value: str) -> str:
        if not value.startswith("/"):
            value = "/" + value
        return value.rstrip("/")

    @property
    def is_production(self) -> bool:
        return self.env == "production"

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def public_api_base(self) -> str:
        """Absolute API base written into notebook metadata for the extension."""
        if self.api_public_base:
            return self.api_public_base.rstrip("/")
        return f"{self.public_origin.rstrip('/')}{self.api_prefix}"

    @property
    def hub_proxy_url(self) -> str:
        """Base URL serving ``/user/<name>/``.

        Falls back to ``jupyterhub_url`` because, in the common single-origin
        deployment, the proxy and the Hub API share a host and only differ in
        path. When they are separate listeners, set ``OPENCE_JUPYTERHUB_PROXY_URL``.
        """
        return (self.jupyterhub_proxy_url or self.jupyterhub_url).rstrip("/")

    @property
    def hub_shards(self) -> list[dict[str, str]]:
        """Parsed ``OPENCE_JUPYTERHUB_SHARDS``; empty list when unset.

        Raises ``ValueError`` on malformed configuration so a typo fails at
        startup, not at a student's first notebook launch.
        """
        raw = self.jupyterhub_shards.strip()
        if not raw:
            return []
        data = json.loads(raw)
        if not isinstance(data, list) or not data:
            raise ValueError("OPENCE_JUPYTERHUB_SHARDS must be a non-empty JSON list")
        shards: list[dict[str, str]] = []
        for index, entry in enumerate(data):
            if not isinstance(entry, dict):
                raise ValueError(f"OPENCE_JUPYTERHUB_SHARDS[{index}] must be an object")
            missing = [k for k in ("api_url", "public_url", "api_token") if not entry.get(k)]
            if missing:
                raise ValueError(f"OPENCE_JUPYTERHUB_SHARDS[{index}] is missing {missing}")
            shards.append(
                {
                    "name": str(entry.get("name") or f"shard{index}"),
                    "api_url": str(entry["api_url"]).rstrip("/"),
                    "proxy_url": str(entry.get("proxy_url") or entry["public_url"]).rstrip("/"),
                    "public_url": str(entry["public_url"]).rstrip("/"),
                    "api_token": str(entry["api_token"]),
                }
            )
        return shards

    @property
    def serving_dir(self) -> Path:
        path = Path(self.dataset_serving_dir)
        if not path.is_absolute():
            path = REPO_ROOT / path
        return path

    def validate_runtime(self) -> list[str]:
        """Return a list of configuration problems that should block startup
        in production. Empty list means the configuration is acceptable.
        """
        problems: list[str] = []
        if self.is_production:
            if len(self.jwt_secret) < 32 or "change-me" in self.jwt_secret:
                problems.append("OPENCE_JWT_SECRET must be a strong, unique secret in production")
            if self.env == "production" and not self.cookie_secure:
                problems.append("OPENCE_COOKIE_SECURE must be true in production")
            if self.notebook_backend != "hub":
                problems.append("notebook backend must be 'hub' in production")
            if not (self.jupyterhub_api_token or self.jupyterhub_shards.strip()):
                problems.append("OPENCE_JUPYTERHUB_API_TOKEN is required in production")
            if self.auth_mode == "dev":
                problems.append("dev password authentication cannot be used in production")
        try:
            shards = self.hub_shards
        except ValueError as exc:
            problems.append(str(exc))
            shards = []
        if self.notebook_backend == "hub" and not (self.jupyterhub_api_token or shards):
            problems.append("OPENCE_JUPYTERHUB_API_TOKEN is empty; notebook launches will fail")
        if self.is_production and self.grader == "docker":
            problems.append(
                "OPENCE_GRADER=docker cannot work in a hardened production pod (no Docker "
                "daemon); use OPENCE_GRADER=kubernetes or disabled"
            )
        if self.is_production and self.grader == "local":
            problems.append(
                "OPENCE_GRADER=local runs untrusted code without isolation; use "
                "kubernetes or disabled in production"
            )
        if self.is_production and self.notebook_backend == "local":
            problems.append(
                "OPENCE_NOTEBOOK_BACKEND=local is development-only; use hub in production"
            )
        return problems


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
