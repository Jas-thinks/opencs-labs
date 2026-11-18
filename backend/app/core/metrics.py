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


def _telemetry_exposition() -> str:
    """Additional Prometheus series derived from the telemetry registry.

    Kept separate from the counters above so the process-global client stays
    untouched and route labels do not explode cardinality at scrape time.
    """
    from app.core import telemetry as t

    lines: list[str] = []
    memory = t.cgroup_memory()
    lines += [
        "# HELP opencs_cgroup_memory_anon_mb Anonymous (non-reclaimable) memory in MiB",
        "# TYPE opencs_cgroup_memory_anon_mb gauge",
        f"opencs_cgroup_memory_anon_mb {memory['anon_mb']}",
        "# HELP opencs_cgroup_memory_limit_mb cgroup memory limit in MiB",
        "# TYPE opencs_cgroup_memory_limit_mb gauge",
        f"opencs_cgroup_memory_limit_mb {memory['limit_mb'] or 0}",
        "# HELP opencs_cgroup_memory_utilization_pct Anonymous memory as a percent of the limit",
        "# TYPE opencs_cgroup_memory_utilization_pct gauge",
        f"opencs_cgroup_memory_utilization_pct {memory['utilization_pct']}",
        "# HELP opencs_cgroup_oom_kill_total OOM kills recorded by the cgroup",
        "# TYPE opencs_cgroup_oom_kill_total counter",
        f"opencs_cgroup_oom_kill_total {memory['oom_kill_count']}",
    ]
    lines += [
        "# HELP opencs_route_latency_ms Per-route latency percentiles from the rolling window",
        "# TYPE opencs_route_latency_ms gauge",
    ]
    for route, stats in t.routes.snapshot().items():
        if stats["p50_ms"] is None:
            continue
        safe = route.replace('"', "")
        lines.append(f'opencs_route_latency_ms{{route="{safe}",quantile="0.5"}} {stats["p50_ms"]}')
        lines.append(f'opencs_route_latency_ms{{route="{safe}",quantile="0.95"}} {stats["p95_ms"]}')
        lines.append(f'opencs_route_latency_ms{{route="{safe}",quantile="0.99"}} {stats["p99_ms"]}')
    lines += [
        "# HELP opencs_hop_latency_ms Upstream hop latency percentiles (db, jupyter)",
        "# TYPE opencs_hop_latency_ms gauge",
    ]
    for hop, stats in t.hop_snapshot().items():
        if stats["p50_ms"] is None:
            continue
        lines.append(f'opencs_hop_latency_ms{{hop="{hop}",quantile="0.5"}} {stats["p50_ms"]}')
        lines.append(f'opencs_hop_latency_ms{{hop="{hop}",quantile="0.95"}} {stats["p95_ms"]}')
    return "\n".join(lines) + "\n"


def metrics_response() -> Response:
    body = generate_latest().decode("utf-8") + _telemetry_exposition()
    return Response(content=body, media_type="text/plain; version=0.0.4; charset=utf-8")
