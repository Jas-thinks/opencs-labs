"""OpenCS Labs API application factory.

Modular monolith: each feature owns its models, schemas, service and router,
but there is one deployable application and one database.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app import __version__
from app.analytics.router import router as analytics_router
from app.notifications.router import router as notifications_router
from app.stream.router import router as stream_router
from app.teaching.router import router as teaching_router
from app.auth.router import router as auth_router
from app.core import telemetry
from app.core.config import settings
from app.core.db_timing import install_db_timing
from app.core.errors import ApiError, api_error_handler, unhandled_error_handler
from app.core.jobs import job_worker_loop
from app.core.logging import RequestContextMiddleware, configure_logging
from app.core.metrics import MetricsMiddleware, metrics_response
from app.core.telemetry_middleware import TelemetryMiddleware
from app.courses.router import router as courses_router
from app.datasets.router import router as datasets_router
from app.db.session import SessionLocal, engine
from app.grading.router import router as grading_router
from app.learning.router import router as learning_router
from app.notebooks.router import router as notebooks_router
from app.notebooks.watcher import watcher_loop
from app.practice.router import router as practice_router
from app.users.router import router as users_router

logger = logging.getLogger("opencs")


@asynccontextmanager
async def lifespan(_: FastAPI):
    tasks: list[asyncio.Task] = []
    if settings.background_workers_enabled:
        tasks = [
            asyncio.create_task(watcher_loop(), name="opencs-autosave-watcher"),
            asyncio.create_task(job_worker_loop(), name="opencs-job-worker"),
        ]
        logger.info("background workers started")
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
            logger.info("background workers stopped")


def create_app() -> FastAPI:
    configure_logging("DEBUG" if settings.debug else "INFO")

    # Attribute query time to the request so Server-Timing can report db;dur.
    install_db_timing(engine)

    problems = settings.validate_runtime()
    if problems:
        for problem in problems:
            logger.warning("configuration: %s", problem)
        if settings.is_production:
            raise RuntimeError("Invalid production configuration: " + "; ".join(problems))

    app = FastAPI(
        title="OpenCS Labs API",
        version=__version__,
        description="Learning, practice and notebook workspace for OpenCS Labs.",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        redoc_url=None,
        lifespan=lifespan,
    )

    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(TelemetryMiddleware)
    app.add_middleware(MetricsMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        expose_headers=["X-Request-ID", "Server-Timing"],
    )

    app.add_exception_handler(ApiError, api_error_handler)
    app.add_exception_handler(RequestValidationError, _validation_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)

    prefix = settings.api_prefix
    app.include_router(auth_router, prefix=prefix)
    app.include_router(users_router, prefix=prefix)
    app.include_router(learning_router, prefix=prefix)
    app.include_router(practice_router, prefix=prefix)
    app.include_router(datasets_router, prefix=prefix)
    app.include_router(notebooks_router, prefix=prefix)
    app.include_router(courses_router, prefix=prefix)
    app.include_router(grading_router, prefix=prefix)
    app.include_router(analytics_router, prefix=prefix)
    app.include_router(stream_router, prefix=prefix)
    app.include_router(notifications_router, prefix=prefix)
    app.include_router(teaching_router, prefix=prefix)

    @app.get("/health", tags=["ops"])
    def health():
        return {"status": "ok", "version": __version__}

    @app.get("/ready", tags=["ops"])
    def ready():
        with SessionLocal() as session:
            session.execute(text("SELECT 1"))
        return {"status": "ready", "database": "ok"}

    @app.get("/metrics", tags=["ops"], include_in_schema=False)
    def metrics():
        return metrics_response()

    @app.get("/telemetry", tags=["ops"], include_in_schema=False)
    def telemetry_view():
        return telemetry.telemetry_payload(settings.node_name, settings.node_role)

    @app.get(f"{prefix}/config", tags=["config"])
    def runtime_config():
        # Public, non-secret runtime facts the UI needs.
        return {
            "environment": settings.env,
            "auth_mode": settings.auth_mode,
            "environment_image": settings.environment_image,
            "dataset_mount_path": settings.dataset_mount_path,
            "max_active_sessions": settings.max_active_sessions,
            "notebook_backend": settings.notebook_backend,
            "api_prefix": settings.api_prefix,
        }

    return app


async def _validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "The request payload or query is invalid",
                "details": {"issues": exc.errors()},
            }
        },
    )


app = create_app()
