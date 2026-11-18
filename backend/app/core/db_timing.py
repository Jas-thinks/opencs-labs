"""SQLAlchemy hooks that attribute query time to the current request.

The ``db;dur`` figure in ``Server-Timing`` is the sum of cursor execution time
for every statement issued while handling one request. It excludes connection
checkout and Python overhead, which is what "database query hop" means.
"""

from __future__ import annotations

import time

from sqlalchemy import event
from sqlalchemy.engine import Engine

from app.core import telemetry


def install_db_timing(engine: Engine) -> None:
    """Attach before/after cursor listeners to one engine (idempotent)."""
    if getattr(engine, "_opencs_timing_installed", False):
        return
    engine._opencs_timing_installed = True  # type: ignore[attr-defined]

    @event.listens_for(engine, "before_cursor_execute")
    def _before(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001, ARG001
        conn.info.setdefault("_opencs_query_started", []).append(time.perf_counter())

    @event.listens_for(engine, "after_cursor_execute")
    def _after(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001, ARG001
        stack = conn.info.get("_opencs_query_started")
        if not stack:
            return
        started = stack.pop()
        telemetry.add_hop("db", (time.perf_counter() - started) * 1000)
