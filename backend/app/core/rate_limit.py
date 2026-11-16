"""Small in-process rate limiter.

This is deliberately simple: a sliding window keyed by principal and scope.
For a multi-replica deployment the same interface should be backed by Redis
(see docs/TECHNICAL_DECISIONS.md). Rate limiting is a safety valve, not the
authorization boundary.
"""

from __future__ import annotations

import threading
import time
from collections import deque

from fastapi import Request

from app.core.config import settings
from app.core.errors import ApiError


class SlidingWindowLimiter:
    def __init__(self) -> None:
        self._events: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def check(self, key: str, limit: int, window_seconds: int = 60) -> tuple[bool, int]:
        now = time.monotonic()
        cutoff = now - window_seconds
        with self._lock:
            bucket = self._events.setdefault(key, deque())
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            if len(bucket) >= limit:
                retry_after = max(1, int(window_seconds - (now - bucket[0])))
                return False, retry_after
            bucket.append(now)
            return True, 0

    def reset(self) -> None:
        with self._lock:
            self._events.clear()


limiter = SlidingWindowLimiter()


def enforce_rate_limit(request: Request, scope: str, limit: int) -> None:
    if not settings.rate_limit_enabled:
        return
    user = getattr(request.state, "user", None)
    principal = f"user:{user.id}" if user is not None else f"ip:{request.client.host if request.client else 'unknown'}"
    allowed, retry_after = limiter.check(f"{scope}:{principal}", limit)
    if not allowed:
        raise ApiError(
            "RATE_LIMITED",
            "Too many requests; slow down and try again",
            status_code=429,
            details={"retry_after_seconds": retry_after},
        )
