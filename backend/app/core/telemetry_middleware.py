"""Request-scoped telemetry middleware.

Emits ``Server-Timing`` with the real hop breakdown and records per-route
percentiles. ``X-Request-ID`` is generated or propagated so one request can be
followed from the load balancer through the backend to Jupyter.
"""

from __future__ import annotations

import time
import uuid

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core import telemetry
from app.core.logging import header_value, request_id_ctx


def _route_label(scope: Scope) -> str:
    """Prefer the route template (``/api/v1/notebooks/{id}``) over the raw path."""
    template = getattr(scope.get("route"), "path", None)
    return template or scope.get("path", "")


class TelemetryMiddleware:
    """Server-Timing + per-route percentiles, as plain ASGI middleware.

    The hop breakdown is finalised when the response *starts*, because that is
    when the Server-Timing header is written; for every non-streaming response
    the endpoint (and its db/jupyter hops) has completed by then.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        # Reuse an upstream id (the load balancer mints one) or make our own.
        request_id = header_value(scope, b"x-request-id") or uuid.uuid4().hex[:16]
        token = request_id_ctx.set(request_id)
        telemetry.begin_request()
        result: dict = {}

        async def send_with_timing(message: Message) -> None:
            if message["type"] == "http.response.start":
                total_ms, hops = telemetry.end_request()
                result.update(status=message["status"], total_ms=total_ms, hops=hops)
                headers = MutableHeaders(scope=message)
                headers["x-request-id"] = request_id
                # Two Server-Timing headers are legal and combine; the LB adds lb;dur.
                headers["server-timing"] = telemetry.format_server_timing(hops)
            await send(message)

        try:
            await self.app(scope, receive, send_with_timing)
        finally:
            if not result:  # failed before a response started
                total_ms, hops = telemetry.end_request()
                result.update(status=500, total_ms=total_ms, hops=hops)
            path = scope.get("path", "")
            if telemetry.route_is_instrumented(path):
                telemetry.routes.observe(_route_label(scope), result["total_ms"], result["status"])
                for hop in ("db", "jupyter"):
                    if hop in result["hops"]:
                        telemetry.observe_hop(hop, result["hops"][hop])
            request_id_ctx.reset(token)


def timing_scope() -> float:
    """Convenience for callers that want to time a block themselves."""
    return time.perf_counter()
