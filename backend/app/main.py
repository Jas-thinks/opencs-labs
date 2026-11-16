"""OpenCS Labs API application factory.

Modular monolith: each feature owns its models, schemas, service and router,
but there is one deployable application and one database.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app import __version__
from app.auth.router import router as auth_router
from app.core.config import settings
from app.core.errors import ApiError, api_error_handler, unhandled_error_handler
from app.core.logging import RequestContextMiddleware, configure_logging
from app.core.metrics import MetricsMiddleware, metrics_response
from app.datasets.router import router as datasets_router
from app.db.session import SessionLocal
from app.learning.router import router as learning_router
from app.notebooks.router import router as notebooks_router
from app.practice.router import router as practice_router
from app.users.router import router as users_router

logger = logging.getLogger("opencs")


def create_app() -> FastAPI:
    configure_logging("DEBUG" if settings.debug else "INFO")

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
    )

    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(MetricsMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        expose_headers=["X-Request-ID"],
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
