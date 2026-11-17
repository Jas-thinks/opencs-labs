"""Timezone helpers.

SQLite (used in development and tests) drops ``tzinfo`` when storing
``DateTime(timezone=True)`` values. PostgreSQL keeps it. Every comparison in
the application goes through :func:`ensure_utc` so the two backends behave the
same way.
"""

from __future__ import annotations

import datetime as dt


def ensure_utc(value: dt.datetime | None) -> dt.datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=dt.UTC)
    return value.astimezone(dt.UTC)


def now_utc() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def seconds_between(start: dt.datetime | None, end: dt.datetime | None) -> float:
    start_utc = ensure_utc(start)
    end_utc = ensure_utc(end)
    if start_utc is None or end_utc is None:
        return 0.0
    return max(0.0, (end_utc - start_utc).total_seconds())
