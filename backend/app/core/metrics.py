"""Prometheus metrics for the platform API.

Notebook/cluster metrics are collected by Prometheus from JupyterHub and
Kubernetes; this module covers the application layer.
"""

from __future__ import annotations

import time

from prometheus_client import Counter, Gauge, Histogram, generate_latest
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

REQUEST_COUNT = Counter(
    "opencs_http_requests_total",
    "HTTP requests handled by the OpenCS API",
    ["method", "route", "status"],
)
REQUEST_LATENCY = Histogram(
    "opencs_http_request_duration_seconds",
    "Latency of OpenCS API requests",
    ["method", "route"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)
NOTEBOOK_LAUNCHES = Counter(
    "opencs_notebook_launches_total",
    "Notebook server launch requests",
    ["result"],
)
NOTEBOOK_LAUNCH_LATENCY = Histogram(
    "opencs_notebook_launch_duration_seconds",
    "Time from launch request to a ready notebook server",
    buckets=(0.5, 1, 2, 5, 10, 20, 30, 60, 120, 300),
)
ACTIVE_SESSIONS = Gauge(
    "opencs_active_notebook_sessions",
    "Active notebook servers observed for OpenCS users",
)
GRADER_RUNS = Counter(
    "opencs_grader_runs_total",
    "Practice evaluation runs",
    ["result"],
)
GRADER_LATENCY = Histogram(
    "opencs_grader_duration_seconds",
    "Practice evaluation duration",
    buckets=(0.5, 1, 2, 5, 10, 20, 30, 60, 120),
)


def _route_template(request: Request) -> str:
    route = request.scope.get("route")
    return getattr(route, "path", request.url.path)


class MetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path in ("/metrics", "/health", "/healthz"):
            return await call_next(request)
        started = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            elapsed = time.perf_counter() - started
            route = _route_template(request)
            REQUEST_COUNT.labels(request.method, route, str(status_code)).inc()
            REQUEST_LATENCY.labels(request.method, route).observe(elapsed)


def metrics_response() -> Response:
    return Response(content=generate_latest(), media_type="text/plain; version=0.0.4; charset=utf-8")
