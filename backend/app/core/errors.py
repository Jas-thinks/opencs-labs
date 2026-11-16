"""Structured API errors.

Every error returned by the API has a stable machine-readable ``code`` so the
frontend can react without parsing prose.
"""

from __future__ import annotations

from typing import Any

from fastapi import Request, status
from fastapi.responses import JSONResponse


class ApiError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = status.HTTP_400_BAD_REQUEST,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}


class NotFound(ApiError):
    def __init__(self, resource: str, identifier: str | None = None) -> None:
        message = f"{resource} not found"
        super().__init__(
            "NOT_FOUND",
            message,
            status_code=status.HTTP_404_NOT_FOUND,
            details={"resource": resource, "identifier": identifier},
        )


class Forbidden(ApiError):
    def __init__(self, message: str = "You do not have access to this resource") -> None:
        super().__init__("FORBIDDEN", message, status_code=status.HTTP_403_FORBIDDEN)


class Unauthenticated(ApiError):
    def __init__(self, message: str = "Authentication required") -> None:
        super().__init__("UNAUTHENTICATED", message, status_code=status.HTTP_401_UNAUTHORIZED)


class Conflict(ApiError):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(code, message, status_code=status.HTTP_409_CONFLICT, details=details)


class CapacityExhausted(ApiError):
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(
            "CAPACITY_EXHAUSTED",
            message,
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            details=details,
        )


class UpstreamUnavailable(ApiError):
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(
            "UPSTREAM_UNAVAILABLE",
            message,
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            details=details,
        )


async def api_error_handler(_: Request, exc: ApiError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": exc.code,
                "message": exc.message,
                "details": exc.details,
            }
        },
    )


async def unhandled_error_handler(_: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "An unexpected error occurred",
                "details": {},
            }
        },
    )
