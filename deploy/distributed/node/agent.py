#!/usr/bin/env python3
"""OpenCS node agent: a tiny Prometheus exporter (standard library only).

Runs on every node under opencs.sh ("agent" service). It exists because the
standard exporters do not fit these targets: node_exporter reports the *host*
(120 CPUs / 125 GiB) instead of this container's 1 CPU / 512 MiB cgroup, and
there is no root, Docker or systemd for the usual sidecars.

Exposes, at GET /metrics (Bearer token required):
  every node   cgroup memory/CPU/pressure/OOM kills, disk, service up/restarts,
               error lines in service logs
  edge         request rate, status classes, latency histogram and upstream
               spread, parsed incrementally from the nginx access log
  pg nodes     up, recovery state, connections, replication lag, commits,
               cache hit ratio, size; on the primary also the job outbox
  hub nodes    hub health and running single-user servers vs the limit
  control      age of the latest database backup

Config comes from ~/opencs/env/agent.env (rendered by render.py).
"""

from __future__ import annotations

import glob
import hmac
import os
import re
import subprocess
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.environ.get("OPENCE_RUNTIME_DIR", os.path.expanduser("~/opencs"))
NODE = os.environ.get("AGENT_NODE", "unknown")
ROLE = os.environ.get("AGENT_ROLE", "unknown")
TOKEN = os.environ.get("AGENT_TOKEN", "")
PORT = int(os.environ.get("AGENT_PORT", "9100"))
CGROUP = "/sys/fs/cgroup"
BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)


def esc(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


class Out:
    """Prometheus text exposition builder."""

    def __init__(self) -> None:
        self.lines: list[str] = []
        self.seen: set[str] = set()

    def metric(self, name: str, value, labels: dict | None = None, kind: str = "gauge", help_: str = "") -> None:
        if name not in self.seen:
            self.seen.add(name)
            base = name[:-7] if name.endswith("_bucket") else name
            self.lines.append(f"# HELP {base} {help_ or base}")
            self.lines.append(f"# TYPE {base} {kind}")
        label_text = ""
        if labels:
            label_text = "{" + ",".join(f'{k}="{esc(v)}"' for k, v in labels.items()) + "}"
        number = float(value)
        # Full precision: rounding a large counter corrupts rate() downstream.
        text = str(int(number)) if number.is_integer() and abs(number) < 1e15 else repr(number)
        self.lines.append(f"{name}{label_text} {text}")

    def text(self) -> str:
        return "\n".join(self.lines) + "\n"


def read(path: str, default: str = "") -> str:
    try:
        with open(path, encoding="utf-8") as handle:
            return handle.read()
    except OSError:
        return default


def kv_file(path: str) -> dict[str, int]:
    values: dict[str, int] = {}
    for line in read(path).splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].lstrip("-").isdigit():
            values[parts[0]] = int(parts[1])
    return values


def pressure(path: str) -> dict[str, float]:
    result = {}
    for line in read(path).splitlines():
        kind, *fields = line.split()
        for field in fields:
            if field.startswith("avg10="):
                result[kind] = float(field.split("=", 1)[1])
    return result


# --------------------------------------------------------------------------- #
# Incremental log followers (handle truncation/rotation; never re-read a file)
# --------------------------------------------------------------------------- #
class Follower:
    def __init__(self, path: str) -> None:
        self.path = path
        self.offset = 0
        self.inode = None

    def new_lines(self, max_bytes: int = 8 * 1024 * 1024) -> list[str]:
        try:
            stat = os.stat(self.path)
        except OSError:
            return []
        if self.inode != stat.st_ino or stat.st_size < self.offset:
            # New file or copy-truncate rotation: start from the beginning.
            self.inode, self.offset = stat.st_ino, 0
        if stat.st_size == self.offset:
            return []
        with open(self.path, "rb") as handle:
            handle.seek(self.offset)
            data = handle.read(max_bytes)
        end = data.rfind(b"\n")
        if end < 0:
            return []
        self.offset += end + 1
        return data[: end + 1].decode("utf-8", "replace").splitlines()


class ServiceLogs:
    """Restarts (from supervisor logs) and error lines (from service logs)."""

    ERROR = re.compile(r'"level": "(ERROR|CRITICAL)"|Traceback \(most recent call last\)|\[E \d|\[emerg\]|\[crit\]|FATAL:')

    def __init__(self) -> None:
        self.followers: dict[str, Follower] = {}
        self.restarts: dict[str, int] = {}
        self.errors: dict[str, int] = {}

    def scan(self) -> None:
        for path in glob.glob(os.path.join(ROOT, "logs", "*.log")):
            name = os.path.basename(path)[:-4]
            follower = self.followers.setdefault(path, Follower(path))
            lines = follower.new_lines()
            if name.endswith(".supervisor"):
                service = name[: -len(".supervisor")]
                started = sum(1 for line in lines if " started pid=" in line)
                if started:
                    # The first start after the agent boots is not a restart.
                    first = service not in self.restarts
                    self.restarts[service] = self.restarts.get(service, 0) + started - (1 if first else 0)
                else:
                    self.restarts.setdefault(service, 0)
            elif not name.startswith("edge."):
                self.errors[name] = self.errors.get(name, 0) + sum(1 for line in lines if self.ERROR.search(line))


class EdgeAccessLog:
    """Parses the edge's access log format (render.py: log_format opencs)."""

    LINE = re.compile(
        r'"(?P<method>[A-Z]+) (?P<path>\S+)[^"]*" (?P<status>\d{3}) \d+ up=(?P<up>\S*) rt=(?P<rt>[\d.]+)'
    )

    def __init__(self, path: str) -> None:
        self.follower = Follower(path)
        self.requests: dict[tuple[str, str], int] = {}
        self.upstreams: dict[str, int] = {}
        self.buckets: dict[str, list[int]] = {}
        self.sums: dict[str, float] = {}
        self.counts: dict[str, int] = {}

    @staticmethod
    def area(path: str) -> str:
        if path.startswith("/api/"):
            return "api"
        if path.startswith("/nb/"):
            return "notebook"
        if path.startswith("/grafana/"):
            return "grafana"
        if path.startswith("/assets/") or path == "/" or "." in path.rsplit("/", 1)[-1]:
            return "static"
        return "spa"

    def scan(self) -> None:
        for line in self.follower.new_lines():
            match = self.LINE.search(line)
            if not match:
                continue
            area = self.area(match["path"])
            status_class = match["status"][0] + "xx"
            key = (area, status_class)
            self.requests[key] = self.requests.get(key, 0) + 1
            seconds = float(match["rt"])
            buckets = self.buckets.setdefault(area, [0] * len(BUCKETS))
            for index, bound in enumerate(BUCKETS):
                if seconds <= bound:
                    buckets[index] += 1
            self.sums[area] = self.sums.get(area, 0.0) + seconds
            self.counts[area] = self.counts.get(area, 0) + 1
            if area == "api" and match["up"] not in ("", "-"):
                upstream = match["up"].split(",")[-1].strip()
                self.upstreams[upstream] = self.upstreams.get(upstream, 0) + 1

    def emit(self, out: Out) -> None:
        for (area, status_class), count in sorted(self.requests.items()):
            out.metric("opencs_edge_requests_total", count, {"area": area, "status_class": status_class}, "counter",
                       "Requests served by the edge, by area and status class")
        for area, buckets in sorted(self.buckets.items()):
            for bound, count in zip(BUCKETS, buckets):
                out.metric("opencs_edge_request_duration_seconds_bucket", count, {"area": area, "le": f"{bound:g}"},
                           "histogram", "Edge request duration (includes upstream time)")
            out.metric("opencs_edge_request_duration_seconds_bucket", self.counts[area], {"area": area, "le": "+Inf"}, "histogram")
            out.metric("opencs_edge_request_duration_seconds_sum", self.sums[area], {"area": area}, "histogram")
            out.metric("opencs_edge_request_duration_seconds_count", self.counts[area], {"area": area}, "histogram")
        for upstream, count in sorted(self.upstreams.items()):
            out.metric("opencs_edge_upstream_requests_total", count, {"upstream": upstream}, "counter",
                       "API requests per backend (load-balancer spread)")


# --------------------------------------------------------------------------- #
# Collectors
# --------------------------------------------------------------------------- #
def collect_cgroup(out: Out) -> None:
    stat = kv_file(f"{CGROUP}/memory.stat")
    current = int(read(f"{CGROUP}/memory.current", "0").strip() or 0)
    limit_raw = read(f"{CGROUP}/memory.max", "max").strip()
    limit = int(limit_raw) if limit_raw.isdigit() else 0
    for kind, value in (("current", current), ("anon", stat.get("anon", 0)), ("file", stat.get("file", 0)),
                        ("shmem", stat.get("shmem", 0)), ("limit", limit)):
        out.metric("opencs_cgroup_memory_bytes", value, {"type": kind}, help_="Container cgroup memory (anon = not reclaimable)")
    events = kv_file(f"{CGROUP}/memory.events")
    out.metric("opencs_cgroup_oom_kills_total", events.get("oom_kill", 0), kind="counter", help_="OOM kills in this container")
    cpu = kv_file(f"{CGROUP}/cpu.stat")
    out.metric("opencs_cgroup_cpu_seconds_total", cpu.get("usage_usec", 0) / 1e6, kind="counter", help_="CPU time used by the container")
    out.metric("opencs_cgroup_cpu_throttled_seconds_total", cpu.get("throttled_usec", 0) / 1e6, kind="counter",
               help_="Time the container was throttled by its CPU quota")
    quota = read(f"{CGROUP}/cpu.max", "max 100000").split()
    cores = (int(quota[0]) / int(quota[1])) if quota and quota[0].isdigit() else 0
    out.metric("opencs_cgroup_cpu_cores", cores, help_="CPU quota in cores")
    for resource in ("memory", "cpu", "io"):
        for kind, value in pressure(f"{CGROUP}/{resource}.pressure").items():
            out.metric("opencs_cgroup_pressure_avg10", value, {"resource": resource, "kind": kind},
                       help_="PSI stall percentage over 10 s")


def collect_disk(out: Out) -> None:
    try:
        stats = os.statvfs(os.path.expanduser("~"))
    except OSError:
        return
    out.metric("opencs_disk_free_bytes", stats.f_bavail * stats.f_frsize, help_="Free disk for the runtime directory")
    out.metric("opencs_disk_size_bytes", stats.f_blocks * stats.f_frsize, help_="Disk size for the runtime directory")


def pid_alive(path: str) -> bool:
    try:
        pid = int(read(path).strip())
        os.kill(pid, 0)
        return True
    except (ValueError, OSError):
        return False


def collect_services(out: Out, logs: ServiceLogs) -> None:
    for path in glob.glob(os.path.join(ROOT, "run", "*.pid")):
        name = os.path.basename(path)[:-4]
        if "." in name:
            continue  # *.app.pid, edge.nginx.pid
        child = os.path.join(ROOT, "run", f"{name}.app.pid")
        up = pid_alive(path) and pid_alive(child)
        out.metric("opencs_service_up", 1 if up else 0, {"service": name}, help_="Supervised service and its child are running")
    for service, count in sorted(logs.restarts.items()):
        out.metric("opencs_service_restarts_total", count, {"service": service}, "counter", "Supervisor restarts since agent start")
    for service, count in sorted(logs.errors.items()):
        out.metric("opencs_log_errors_total", count, {"service": service}, "counter", "Error lines written by the service")


PG_QUERY = r"""
SELECT 'up', 1
UNION ALL SELECT 'in_recovery', pg_is_in_recovery()::int
UNION ALL SELECT 'conn_' || coalesce(state, 'other'), count(*) FROM pg_stat_activity WHERE datname IS NOT NULL GROUP BY state
UNION ALL SELECT 'max_connections', current_setting('max_connections')::int
UNION ALL SELECT 'replicas_streaming', count(*) FROM pg_stat_replication WHERE state = 'streaming'
UNION ALL SELECT 'replication_lag_bytes', coalesce(max(pg_wal_lsn_diff(pg_current_wal_lsn(), replay_lsn)), 0)
       FROM pg_stat_replication WHERE NOT pg_is_in_recovery()
UNION ALL SELECT 'replay_delay_seconds',
       CASE WHEN pg_is_in_recovery() AND pg_last_wal_receive_lsn() <> pg_last_wal_replay_lsn()
            THEN extract(epoch FROM now() - pg_last_xact_replay_timestamp()) ELSE 0 END
UNION ALL SELECT 'xact_commit', sum(xact_commit) FROM pg_stat_database
UNION ALL SELECT 'xact_rollback', sum(xact_rollback) FROM pg_stat_database
UNION ALL SELECT 'deadlocks', sum(deadlocks) FROM pg_stat_database
UNION ALL SELECT 'blks_hit', sum(blks_hit) FROM pg_stat_database
UNION ALL SELECT 'blks_read', sum(blks_read) FROM pg_stat_database
UNION ALL SELECT 'db_size_bytes', pg_database_size(current_database());
"""

JOBS_QUERY = r"""
SELECT 'jobs_' || status, count(*) FROM jobs GROUP BY status
UNION ALL SELECT 'oldest_pending_job_seconds',
       coalesce(extract(epoch FROM now() - min(run_at)), 0) FROM jobs WHERE status = 'pending'
UNION ALL SELECT 'unread_notifications', count(*) FROM notifications WHERE read_at IS NULL;
"""


def psql(query: str) -> dict[str, float] | None:
    env = {**os.environ, "PGPASSWORD": os.environ.get("PG_MONITOR_PASSWORD", ""), "PGCONNECT_TIMEOUT": "3"}
    try:
        result = subprocess.run(
            ["psql", "-h", "127.0.0.1", "-U", "opencs_monitor", "-d", "opencs", "-AtF", "\t", "-c", query],
            env=env, capture_output=True, text=True, timeout=8,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    values = {}
    for line in result.stdout.splitlines():
        key, _, value = line.partition("\t")
        try:
            values[key] = float(value or 0)
        except ValueError:
            continue
    return values


def collect_postgres(out: Out) -> None:
    values = psql(PG_QUERY)
    out.metric("opencs_pg_up", 1 if values else 0, help_="PostgreSQL answers queries")
    if not values:
        return
    counters = {"xact_commit", "xact_rollback", "deadlocks", "blks_hit", "blks_read"}
    for key, value in sorted(values.items()):
        if key == "up":
            continue
        if key.startswith("conn_"):
            out.metric("opencs_pg_connections", value, {"state": key[5:]}, help_="Connections by state")
        elif key in counters:
            out.metric(f"opencs_pg_{key}_total", value, kind="counter")
        else:
            out.metric(f"opencs_pg_{key}", value)
    if values.get("in_recovery") == 0:
        jobs = psql(JOBS_QUERY) or {}
        for key, value in sorted(jobs.items()):
            if key.startswith("jobs_"):
                out.metric("opencs_jobs", value, {"status": key[5:]}, help_="Job outbox rows by status")
            else:
                out.metric(f"opencs_{key}", value)


def collect_hub(out: Out) -> None:
    url = os.environ.get("HUB_HEALTH_URL", "")
    up = 0
    if url:
        try:
            with urllib.request.urlopen(url, timeout=3) as response:  # noqa: S310 - local, configured
                up = 1 if response.status == 200 else 0
        except OSError:
            up = 0
    out.metric("opencs_hub_up", up, help_="JupyterHub answers its health check")
    running = 0
    for cmdline in glob.glob("/proc/[0-9]*/cmdline"):
        try:
            with open(cmdline, "rb") as handle:
                if b"jupyterhub-singleuser" in handle.read():
                    running += 1
        except OSError:
            continue  # process exited while scanning
    out.metric("opencs_hub_running_servers", running, help_="Running single-user notebook servers")
    out.metric("opencs_hub_server_limit", int(os.environ.get("HUB_SERVER_LIMIT", "0") or 0), help_="Configured limit")


def collect_control(out: Out) -> None:
    latest = os.path.join(ROOT, "backups", "latest.dump")
    try:
        age = time.time() - os.stat(latest).st_mtime
    except OSError:
        age = -1
    out.metric("opencs_backup_age_seconds", age, help_="Age of the latest database dump (-1 = none)")


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #
LOGS = ServiceLogs()
EDGE = EdgeAccessLog(os.path.join(ROOT, "logs", "edge.access.log")) if os.path.exists(
    os.path.join(ROOT, "env", "edge.conf")) else None
LOCK = threading.Lock()


def render() -> str:
    out = Out()
    started = time.perf_counter()
    with LOCK:
        LOGS.scan()
        if EDGE is not None:
            EDGE.scan()
    out.metric("opencs_node_info", 1, {"role": ROLE}, help_="Node identity")
    collect_cgroup(out)
    collect_disk(out)
    collect_services(out, LOGS)
    if EDGE is not None:
        EDGE.emit(out)
    if ROLE in ("pg-primary", "pg-standby"):
        collect_postgres(out)
    if ROLE == "hub":
        collect_hub(out)
    if ROLE == "control":
        collect_control(out)
    out.metric("opencs_agent_scrape_seconds", time.perf_counter() - started, help_="Time to collect these metrics")
    return out.text()


class Handler(BaseHTTPRequestHandler):
    server_version = "opencs-agent"

    def do_GET(self) -> None:  # noqa: N802 - http.server API
        if self.path == "/healthz":
            self._send(200, "ok\n")
            return
        if self.path != "/metrics":
            self._send(404, "not found\n")
            return
        supplied = self.headers.get("Authorization", "")
        if not TOKEN or not hmac.compare_digest(supplied, f"Bearer {TOKEN}"):
            self._send(401, "unauthorized\n")
            return
        try:
            self._send(200, render(), "text/plain; version=0.0.4")
        except Exception as exc:  # noqa: BLE001 - a broken collector must not kill the agent
            self._send(500, f"collector error: {exc}\n")

    def _send(self, status: int, body: str, content_type: str = "text/plain") -> None:
        data = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args) -> None:  # quiet: scraped every 30 s
        return


if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("AGENT_TOKEN is required")
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    server.daemon_threads = True
    print(f"opencs-agent node={NODE} role={ROLE} port={PORT}", flush=True)
    server.serve_forever()
