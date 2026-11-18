"""Lightweight in-process telemetry: hop timings, rolling percentiles, cgroups.

Deliberately dependency-free. The nodes run in 512 MiB cgroups, so this module
never accumulates unbounded data: every route keeps a fixed-size reservoir of
recent samples and percentiles are computed on read.

Two things are exposed:

* ``Server-Timing`` — end-to-end hop breakdown for a single request
  (``lb``, ``backend``, ``db``, ``jupyter``), so a slow request shows which hop
  caused it without a tracing backend.
* ``/telemetry`` — per-route p50/p95/p99, error counts, upstream hop medians and
  the live cgroup memory/CPU picture.
"""

from __future__ import annotations

import math
import os
import pathlib
import platform
import threading
import time
from collections import deque
from contextvars import ContextVar
from typing import Any

#: Fixed sample window per route. 512 samples is a few KB and gives stable
#: p99 estimates without growing with traffic.
SAMPLE_WINDOW = 512

#: Routes that exist for operations and must not pollute latency statistics.
IGNORED_PATHS = ("/metrics", "/health", "/healthz", "/ready", "/telemetry")

_CG = pathlib.Path("/sys/fs/cgroup")

#: Per-request hop timings in milliseconds. Set by the middleware, appended to by
#: the DB and Jupyter instrumentation, then rendered into ``Server-Timing``.
_request_started: ContextVar[float | None] = ContextVar("telemetry_started", default=None)
_hop_ms: ContextVar[dict[str, float] | None] = ContextVar("telemetry_hops", default=None)


# --------------------------------------------------------------------------- #
# Per-request hop timings
# --------------------------------------------------------------------------- #
def begin_request() -> None:
    _request_started.set(time.perf_counter())
    _hop_ms.set({})


def end_request() -> tuple[float, dict[str, float]]:
    """Return (total_ms, hops). ``backend`` is the whole in-process duration."""
    started = _request_started.get()
    total_ms = round((time.perf_counter() - started) * 1000, 2) if started else 0.0
    hops = dict(_hop_ms.get() or {})
    hops["backend"] = total_ms
    return total_ms, hops


def add_hop(name: str, milliseconds: float) -> None:
    """Accumulate time spent in a downstream hop (db, jupyter, ...)."""
    hops = _hop_ms.get()
    if hops is None:
        return
    hops[name] = round(hops.get(name, 0.0) + milliseconds, 2)


def current_request_id() -> str:
    from app.core.logging import request_id_ctx

    return request_id_ctx.get()


def format_server_timing(hops: dict[str, float]) -> str:
    """Render ``Server-Timing``: backend first (total), then hops, then lb."""
    ordered: list[tuple[str, float]] = [("backend", hops.get("backend", 0.0))]
    for key in ("db", "jupyter"):
        if key in hops:
            ordered.append((key, hops[key]))
    return ", ".join(f"{name};dur={value}" for name, value in ordered)


# --------------------------------------------------------------------------- #
# Rolling per-route statistics
# --------------------------------------------------------------------------- #
class RouteStats:
    """Fixed-window latency reservoir plus error counters for one route."""

    __slots__ = ("samples", "count", "errors_4xx", "errors_5xx", "max_ms", "lock")

    def __init__(self) -> None:
        self.samples: deque[float] = deque(maxlen=SAMPLE_WINDOW)
        self.count = 0
        self.errors_4xx = 0
        self.errors_5xx = 0
        self.max_ms = 0.0
        self.lock = threading.Lock()

    def observe(self, ms: float, status: int) -> None:
        with self.lock:
            self.count += 1
            self.samples.append(ms)
            if ms > self.max_ms:
                self.max_ms = round(ms, 2)
            if 400 <= status < 500:
                self.errors_4xx += 1
            elif status >= 500:
                self.errors_5xx += 1

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            ordered = sorted(self.samples)
            count = self.count
            e4, e5, mx = self.errors_4xx, self.errors_5xx, self.max_ms

        def pct(p: float) -> float | None:
            if not ordered:
                return None
            if len(ordered) == 1:
                return round(ordered[0], 2)
            index = (len(ordered) - 1) * (p / 100.0)
            lower = math.floor(index)
            upper = min(lower + 1, len(ordered) - 1)
            weight = index - lower
            return round(ordered[lower] * (1 - weight) + ordered[upper] * weight, 2)

        total = e4 + e5
        return {
            "count": count,
            "samples": len(ordered),
            "p50_ms": pct(50),
            "p95_ms": pct(95),
            "p99_ms": pct(99),
            "max_ms": mx,
            "errors_4xx": e4,
            "errors_5xx": e5,
            "error_rate": round(total / count, 4) if count else 0.0,
        }


class RouteRegistry:
    def __init__(self) -> None:
        self._routes: dict[str, RouteStats] = {}
        self._lock = threading.Lock()

    def get(self, route: str) -> RouteStats:
        with self._lock:
            stats = self._routes.get(route)
            if stats is None:
                stats = self._routes[route] = RouteStats()
            return stats

    def observe(self, route: str, ms: float, status: int) -> None:
        self.get(route).observe(ms, status)

    def snapshot(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            items = list(self._routes.items())
        return {route: stats.snapshot() for route, stats in sorted(items)}

    def reset(self) -> None:
        with self._lock:
            self._routes.clear()


routes = RouteRegistry()

#: Upstream hop medians (db, jupyter), filled by the middleware.
_hop_registry: dict[str, RouteStats] = {}
_hop_lock = threading.Lock()


def observe_hop(name: str, ms: float) -> None:
    with _hop_lock:
        stats = _hop_registry.get(name)
        if stats is None:
            stats = _hop_registry[name] = RouteStats()
    stats.observe(ms, 200)


def hop_snapshot() -> dict[str, dict[str, Any]]:
    with _hop_lock:
        items = list(_hop_registry.items())
    return {name: stats.snapshot() for name, stats in sorted(items)}


def reset_all() -> None:
    routes.reset()
    with _hop_lock:
        _hop_registry.clear()


# --------------------------------------------------------------------------- #
# cgroup + host resources
# --------------------------------------------------------------------------- #
def _read_int(path: pathlib.Path) -> int | None:
    try:
        return int(path.read_text().strip())
    except Exception:
        return None


def _read_events() -> dict[str, int]:
    events: dict[str, int] = {}
    try:
        for line in (_CG / "memory.events").read_text().splitlines():
            key, _, value = line.partition(" ")
            events[key] = int(value)
    except Exception:
        pass
    return events


def cgroup_memory() -> dict[str, Any]:
    """Report *anonymous* memory as the pressure signal.

    ``memory.current`` includes page cache, which the kernel reclaims instead of
    invoking the OOM killer. Reporting ``current/limit`` on a busy node shows
    ~95% while anonymous memory is 26%, which produces false SLO failures. Both
    numbers are returned; ``utilization_pct`` is the anonymous figure because
    that is the one that can actually cause an OOM kill.
    """
    current = _read_int(_CG / "memory.current") or 0
    limit = _read_int(_CG / "memory.max")
    anon = 0
    inactive_file = 0
    try:
        for line in (_CG / "memory.stat").read_text().splitlines():
            key, _, value = line.partition(" ")
            if key == "anon":
                anon = int(value)
            elif key == "inactive_file":
                inactive_file = int(value)
    except Exception:
        pass

    events = _read_events()
    limit_mb = round(limit / 1048576, 1) if limit else None
    # On a non-cgroup host ``memory.current`` is absent while ``memory.stat`` may
    # still exist, so clamp rather than emit negative derived values.
    current = max(current, anon)
    return {
        "used_mb": round(current / 1048576, 1),
        "anon_mb": round(anon / 1048576, 1),
        "file_cache_mb": round(max(current - anon, 0) / 1048576, 1),
        "reclaimable_mb": round(inactive_file / 1048576, 1),
        "limit_mb": limit_mb,
        "utilization_pct": round(anon / limit * 100, 1) if limit else 0.0,
        "physical_pct": round(current / limit * 100, 1) if limit else 0.0,
        "oom_kill_count": events.get("oom_kill", 0),
        "oom_group_kill": events.get("oom_group_kill", 0),
        "max_events_seen": events.get("max", 0),
    }


def cgroup_cpu() -> dict[str, Any]:
    """CPU usage from cpu.stat (usage_usec) plus the configured quota."""
    usage_usec = 0
    throttled = 0
    try:
        for line in (_CG / "cpu.stat").read_text().splitlines():
            key, _, value = line.partition(" ")
            if key == "usage_usec":
                usage_usec = int(value)
            elif key == "nr_throttled":
                throttled = int(value)
    except Exception:
        pass
    quota = None
    try:
        raw = (_CG / "cpu.max").read_text().split()
        if raw[0] != "max":
            quota = round(int(raw[0]) / int(raw[1]), 2)
    except Exception:
        pass
    return {
        "cpu_seconds_total": round(usage_usec / 1_000_000, 2),
        "nr_throttled": throttled,
        "cpu_quota_cores": quota,
        "load_1m": round(os.getloadavg()[0], 2) if hasattr(os, "getloadavg") else None,
    }


_PROCESS_START = time.time()


def telemetry_payload(node: str, role: str) -> dict[str, Any]:
    return {
        "node": node,
        "role": role,
        "host": platform.node(),
        "uptime_seconds": round(time.time() - _PROCESS_START, 1),
        "pid": os.getpid(),
        "routes": routes.snapshot(),
        "hops": hop_snapshot(),
        "memory": cgroup_memory(),
        "cpu": cgroup_cpu(),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def route_is_instrumented(path: str) -> bool:
    return not path.startswith(IGNORED_PATHS)
