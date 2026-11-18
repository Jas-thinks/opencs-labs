"""Request-scoped telemetry middleware.

Emits ``Server-Timing`` with the real hop breakdown and records per-route
percentiles. ``X-Request-ID`` is generated or propagated so one request can be
followed from the load balancer through the backend to Jupyter.
"""

from __future__ import annotations

import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.core import telemetry
from app.core.logging import request_id_ctx


def _route_label(request: Request) -> str:
    """Prefer the route template (``/api/v1/notebooks/{id}``) over the raw path."""
    scope_route = request.scope.get("route")
    template = getattr(scope_route, "path", None)
    if template:
        return template
    return request.url.path


class TelemetryMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Reuse an upstream id (the load balancer mints one) or make our own.
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        token = request_id_ctx.set(request_id)
        telemetry.begin_request()
        started = time.perf_counter()

        response = None
        try:
            response = await call_next(request)
            return response
        finally:
            status = getattr(response, "status_code", 500)
            total_ms, hops = telemetry.end_request()

            if response is not None:
                response.headers["x-request-id"] = request_id
                # Two Server-Timing headers are legal and combine; the LB adds lb;dur.
                response.headers["server-timing"] = telemetry.format_server_timing(hops)

            if telemetry.route_is_instrumented(request.url.path):
                label = _route_label(request)
                telemetry.routes.observe(label, total_ms, status)
                for hop in ("db", "jupyter"):
                    if hop in hops:
                        telemetry.observe_hop(hop, hops[hop])

            request_id_ctx.reset(token)


def timing_scope() -> float:
    """Convenience for callers that want to time a block themselves."""
    return time.perf_counter()
