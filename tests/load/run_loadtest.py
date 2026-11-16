"""Load-test harness for OpenCS Labs.

This script drives a staged, mixed workload against a *running* stack and
reports measured results. It does not fabricate numbers: if the stack is not
reachable, it fails.

Workload per virtual user:
  1. sign in (POST /auth/token to obtain a bearer token)
  2. GET /learning/paths
  3. GET /datasets
  4. GET /datasets/iris/snippet
  5. GET /notebooks

Notebook spawning is load-tested separately because it depends on cluster
capacity; pass --spawn to include POST /notebooks/server/start (this will
actually spawn notebook pods and is expensive).

Usage:
    python tests/load/run_loadtest.py --users 10 --duration 60
    python tests/load/run_loadtest.py --users 100 --duration 120 --spawn

Requires: httpx (already pinned for the backend).
"""

from __future__ import annotations

import argparse
import asyncio
import random
import statistics
import sys
import time
from dataclasses import dataclass, field

import httpx

BASE = "http://localhost:8000"
API = f"{BASE}/api/v1"

ACCOUNTS = [
    ("student@opencs.local", "opencs-demo"),
    ("student2@opencs.local", "opencs-demo"),
]
PASSWORD_FALLBACK = "opencs-demo"


@dataclass
class Stats:
    latencies: list[float] = field(default_factory=list)
    errors: int = 0
    requests: int = 0
    error_codes: dict[str, int] = field(default_factory=dict)

    def record(self, elapsed: float, ok: bool, code: str = "") -> None:
        self.requests += 1
        self.latencies.append(elapsed)
        if not ok:
            self.errors += 1
            self.error_codes[code] = self.error_codes.get(code, 0) + 1

    def summary(self) -> dict:
        if not self.latencies:
            return {"requests": 0}
        ordered = sorted(self.latencies)
        return {
            "requests": self.requests,
            "errors": self.errors,
            "error_rate": round(self.errors / max(self.requests, 1), 4),
            "p50_ms": round(_percentile(ordered, 50) * 1000, 1),
            "p95_ms": round(_percentile(ordered, 95) * 1000, 1),
            "p99_ms": round(_percentile(ordered, 99) * 1000, 1),
            "max_ms": round(ordered[-1] * 1000, 1),
            "mean_ms": round(statistics.fmean(ordered) * 1000, 1),
            "error_codes": self.error_codes,
        }


def _percentile(ordered: list[float], pct: float) -> float:
    if len(ordered) == 1:
        return ordered[0]
    index = (len(ordered) - 1) * (pct / 100)
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    weight = index - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


async def timed(client: httpx.AsyncClient, stats: Stats, method: str, url: str, **kwargs) -> httpx.Response | None:
    started = time.perf_counter()
    try:
        response = await client.request(method, url, **kwargs)
    except httpx.HTTPError as exc:
        stats.record(time.perf_counter() - started, False, type(exc).__name__)
        return None
    elapsed = time.perf_counter() - started
    code = ""
    if response.status_code >= 400:
        try:
            code = response.json().get("error", {}).get("code", str(response.status_code))
        except Exception:  # noqa: BLE001
            code = str(response.status_code)
    stats.record(elapsed, response.status_code < 400, code)
    return response


async def virtual_user(user_id: int, duration: float, stats: Stats, spawn: bool) -> None:
    async with httpx.AsyncClient(timeout=30.0, base_url=BASE) as client:
        email, password = ACCOUNTS[user_id % len(ACCOUNTS)]
        response = await timed(client, stats, "POST", f"{API}/auth/token", json={"email": email, "password": password})
        if response is None or response.status_code != 200:
            return
        token = response.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        if spawn:
            await timed(client, stats, "POST", f"{API}/notebooks/server/start", headers=headers)

        deadline = time.monotonic() + duration
        while time.monotonic() < deadline:
            await timed(client, stats, "GET", f"{API}/learning/paths", headers=headers)
            await timed(client, stats, "GET", f"{API}/datasets", headers=headers)
            await timed(client, stats, "GET", f"{API}/datasets/iris/snippet", headers=headers)
            await timed(client, stats, "GET", f"{API}/practice/exercises", headers=headers)
            await timed(client, stats, "GET", f"{API}/notebooks", headers=headers)
            await asyncio.sleep(random.uniform(0.2, 1.0))


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--users", type=int, default=10)
    parser.add_argument("--duration", type=float, default=60.0)
    parser.add_argument("--base", default=BASE)
    parser.add_argument("--spawn", action="store_true", help="also start notebook servers")
    args = parser.parse_args()

    global BASE, API
    BASE = args.base.rstrip("/")
    API = f"{BASE}/api/v1"

    async with httpx.AsyncClient(timeout=10.0) as probe:
        try:
            health = await probe.get(f"{BASE}/health")
        except httpx.HTTPError as exc:
            print(f"stack is not reachable at {BASE}: {exc}", file=sys.stderr)
            return 2
    if health.status_code != 200:
        print(f"health check failed: {health.status_code}", file=sys.stderr)
        return 2

    print(f"load test: {args.users} users for {args.duration}s against {BASE}")
    stats = Stats()
    started = time.perf_counter()
    await asyncio.gather(*(virtual_user(index, args.duration, stats, args.spawn) for index in range(args.users)))
    wall = time.perf_counter() - started

    summary = stats.summary()
    summary["wall_seconds"] = round(wall, 1)
    summary["throughput_rps"] = round(summary.get("requests", 0) / max(wall, 0.001), 1)
    summary["users"] = args.users

    print("\n=== measured result ===")
    for key, value in summary.items():
        print(f"  {key}: {value}")

    if summary.get("error_rate", 1) > 0.01:
        print("\nFAILED: error rate above 1%", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
