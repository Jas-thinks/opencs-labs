"""Monitoring configuration rendered from inventory.json (used by render.py).

Stack (ADR-011): VictoriaMetrics (scrapes + stores, Prometheus-compatible),
vmalert (rules; UI-only alerts written back as ALERTS series) and Grafana, all
on the monitoring node. Everything stays on the campus network.
"""

from __future__ import annotations

import json
from typing import Any

HOST_A = "10.1.75.53"
SCRAPE_INTERVAL = "30s"


def agent_port(node: dict) -> int:
    # Host A nodes share a bridge with the monitoring node: an unpublished port.
    # Host B nodes are reached through the host's published 6XYZ port.
    return 9100 if node["host"] == HOST_A else 6000


def _agent_target(node: dict, mon: dict) -> str:
    if node["host"] == mon["host"]:
        return f"{node['ip']}:9100"
    return f"{node['host']}:6{str(node['ssh_port'])[1:]}"  # 2221 -> 6221


def scrape_config(inv: dict, token: str) -> str:
    mon = monitoring_node(inv)
    api_port = inv["tuning"]["api_port"]
    agents = [
        {"targets": [_agent_target(n, mon)], "labels": {"node": n["name"], "alias": n["alias"], "role": n["role"]}}
        for n in inv["nodes"]
    ]
    apis = [
        {"targets": [f"{n['ip']}:{api_port}"], "labels": {"node": n["name"], "alias": n["alias"]}}
        for n in inv["nodes"]
        if n["role"] == "api"
    ]
    config = {
        "global": {"scrape_interval": SCRAPE_INTERVAL, "scrape_timeout": "10s"},
        "scrape_configs": [
            {"job_name": "agent", "bearer_token": token, "static_configs": agents},
            {"job_name": "api", "metrics_path": "/metrics", "static_configs": apis},
            {"job_name": "victoriametrics", "static_configs": [{"targets": [f"{mon['ip']}:8428"]}]},
            {"job_name": "vmalert", "static_configs": [{"targets": ["127.0.0.1:8880"]}]},
            {"job_name": "grafana", "static_configs": [{"targets": [f"{mon['ip']}:3000"]}]},
        ],
    }
    return "# Rendered by render.py\n" + json.dumps(config, indent=2)  # JSON is valid YAML


def monitoring_node(inv: dict) -> dict:
    alias = inv["tuning"].get("monitoring_alias", "pg2")
    return next(n for n in inv["nodes"] if n["alias"] == alias)


# --------------------------------------------------------------------------- #
# Alert rules (vmalert). Alerts are shown in Grafana only (no notifier).
# --------------------------------------------------------------------------- #
def _rule(name: str, expr: str, duration: str, severity: str, summary: str) -> dict:
    return {
        "alert": name,
        "expr": expr,
        "for": duration,
        "labels": {"severity": severity},
        "annotations": {"summary": summary},
    }


def alert_rules(inv: dict) -> str:
    rules = [
        _rule("NodeAgentDown", 'up{job="agent"} == 0', "2m", "critical",
              "{{ $labels.node }} ({{ $labels.role }}) is not reachable"),
        _rule("APIDown", 'up{job="api"} == 0', "1m", "critical", "API {{ $labels.node }} is down"),
        _rule("ServiceDown", "opencs_service_up == 0", "2m", "critical",
              "{{ $labels.service }} on {{ $labels.node }} is not running"),
        _rule("ServiceFlapping", "increase(opencs_service_restarts_total[15m]) > 3", "0m", "warning",
              "{{ $labels.service }} on {{ $labels.node }} restarted {{ $value }} times in 15 min"),
        _rule("EdgeErrorRateHigh",
              'sum(rate(opencs_edge_requests_total{status_class="5xx"}[5m])) '
              "/ clamp_min(sum(rate(opencs_edge_requests_total[5m])), 0.001) > 0.05",
              "5m", "critical", "More than 5% of requests fail with 5xx"),
        _rule("APILatencyHigh",
              'histogram_quantile(0.95, sum(rate(opencs_edge_request_duration_seconds_bucket{area="api"}[5m])) by (le)) > 0.5',
              "10m", "warning", "API p95 latency at the edge is {{ $value | humanizeDuration }}"),
        _rule("PostgresDown", "opencs_pg_up == 0", "1m", "critical", "PostgreSQL on {{ $labels.node }} is down"),
        _rule("ReplicationBroken", 'opencs_pg_replicas_streaming{role="pg-primary"} == 0', "2m", "critical",
              "The standby is not streaming from the primary"),
        _rule("ReplicationLagHigh", "opencs_pg_replication_lag_bytes > 64e6", "5m", "warning",
              "Standby is {{ $value | humanize1024 }}B behind"),
        _rule("ConnectionsNearLimit",
              "sum by (node) (opencs_pg_connections) / on(node) opencs_pg_max_connections > 0.85",
              "5m", "warning", "PostgreSQL on {{ $labels.node }} is near max_connections"),
        _rule("MemoryPressure",
              'opencs_cgroup_memory_bytes{type="anon"} / on(node) opencs_cgroup_memory_bytes{type="limit"} > 0.9',
              "5m", "warning", "{{ $labels.node }} uses {{ $value | humanizePercentage }} of its memory limit"),
        _rule("OOMKill", "increase(opencs_cgroup_oom_kills_total[15m]) > 0", "0m", "critical",
              "A process on {{ $labels.node }} was OOM-killed"),
        _rule("DiskLow", "opencs_disk_free_bytes / opencs_disk_size_bytes < 0.1", "10m", "warning",
              "{{ $labels.node }} has less than 10% disk free"),
        _rule("JobBacklog", "opencs_oldest_pending_job_seconds > 600", "5m", "warning",
              "Background jobs are {{ $value | humanizeDuration }} behind (worker on the control node)"),
        _rule("NotebookCapacityHigh",
              "sum(opencs_hub_running_servers) / clamp_min(sum(opencs_hub_server_limit), 1) > 0.85",
              "10m", "warning", "Notebook capacity is almost exhausted"),
        _rule("HubDown", "opencs_hub_up == 0", "2m", "critical", "JupyterHub on {{ $labels.node }} is down"),
        _rule("BackupStale", "opencs_backup_age_seconds > 26 * 3600 or opencs_backup_age_seconds < 0", "30m",
              "warning", "The latest database backup is missing or older than 26 h"),
    ]
    return "# Rendered by render.py\n" + json.dumps({"groups": [{"name": "opencs", "interval": "30s", "rules": rules}]}, indent=2)


# --------------------------------------------------------------------------- #
# Grafana
# --------------------------------------------------------------------------- #
def grafana_ini(inv: dict, admin_password: str, secret_key: str, root: str) -> str:
    mon = monitoring_node(inv)
    return f"""; Rendered by render.py - Grafana behind the edge at /grafana/
[paths]
data = {root}/data/grafana
logs = {root}/logs/grafana
plugins = {root}/data/grafana/plugins
provisioning = {root}/env/grafana-provisioning

[server]
http_addr = {mon['ip']}
http_port = 3000
root_url = {inv['public_origin']}/grafana/
serve_from_sub_path = true
enable_gzip = true

[security]
admin_user = admin
admin_password = {admin_password}
secret_key = {secret_key}
cookie_samesite = lax
disable_gravatar = true

[users]
allow_sign_up = false
default_theme = dark

[auth.anonymous]
enabled = false

[analytics]
reporting_enabled = false
check_for_updates = false
check_for_plugin_updates = false
feedback_links_enabled = false

[news]
news_feed_enabled = false

[plugins]
plugin_admin_enabled = false

[database]
wal = true

[unified_alerting]
enabled = false

[alerting]
enabled = false

[log]
mode = console
level = warn
"""


def grafana_datasource(inv: dict) -> str:
    mon = monitoring_node(inv)
    return json.dumps({
        "apiVersion": 1,
        "datasources": [{
            "name": "VictoriaMetrics",
            "uid": "vm",
            "type": "prometheus",
            "access": "proxy",
            "url": f"http://{mon['ip']}:8428",
            "isDefault": True,
            "jsonData": {"timeInterval": SCRAPE_INTERVAL, "httpMethod": "POST"},
        }],
    }, indent=2)


def grafana_dashboard_provider(root: str) -> str:
    return json.dumps({
        "apiVersion": 1,
        "providers": [{
            "name": "opencs",
            "folder": "OpenCS",
            "type": "file",
            "disableDeletion": True,
            "allowUiUpdates": False,
            "options": {"path": f"{root}/env/dashboards"},
        }],
    }, indent=2)


# --------------------------------------------------------------------------- #
# Dashboards (generated: small builder instead of thousands of JSON lines)
# --------------------------------------------------------------------------- #
DS = {"type": "prometheus", "uid": "vm"}


class Board:
    def __init__(self, uid: str, title: str, description: str) -> None:
        self.uid, self.title, self.description = uid, title, description
        self.panels: list[dict] = []
        self.y = 0
        self.x = 0
        self.row_h = 0

    def _place(self, w: int, h: int) -> dict:
        if self.x + w > 24:
            self.x, self.y = 0, self.y + self.row_h
            self.row_h = 0
        pos = {"x": self.x, "y": self.y, "w": w, "h": h}
        self.x += w
        self.row_h = max(self.row_h, h)
        return pos

    def row(self, title: str) -> None:
        self.x, self.y = 0, self.y + self.row_h
        self.row_h = 1
        self.panels.append({"type": "row", "title": title, "collapsed": False, "gridPos": {"x": 0, "y": self.y, "w": 24, "h": 1}, "id": len(self.panels) + 1})
        self.x, self.y, self.row_h = 0, self.y + 1, 0

    def _panel(self, kind: str, title: str, targets: list[tuple[str, str]], w: int, h: int, unit: str = "short",
               extra: dict | None = None, description: str = "") -> None:
        panel = {
            "id": len(self.panels) + 1,
            "type": kind,
            "title": title,
            "description": description,
            "datasource": DS,
            "gridPos": self._place(w, h),
            "targets": [
                {"refId": chr(65 + i), "datasource": DS, "expr": expr, "legendFormat": legend, "range": kind != "table", "instant": kind == "table"}
                for i, (expr, legend) in enumerate(targets)
            ],
            "fieldConfig": {"defaults": {"unit": unit}, "overrides": []},
            "options": {},
        }
        if kind == "timeseries":
            panel["fieldConfig"]["defaults"]["custom"] = {"lineWidth": 1, "fillOpacity": 8, "showPoints": "never"}
            panel["options"] = {"legend": {"displayMode": "list", "placement": "bottom"}, "tooltip": {"mode": "multi"}}
        if extra:
            for key, value in extra.items():
                if isinstance(value, dict) and isinstance(panel.get(key), dict):
                    panel[key].update(value)
                else:
                    panel[key] = value
        self.panels.append(panel)

    def ts(self, title, targets, w=12, h=8, unit="short", description=""):
        self._panel("timeseries", title, targets, w, h, unit, description=description)

    def stat(self, title, expr, w=4, h=4, unit="short", thresholds=None, description=""):
        steps = thresholds or [{"color": "green", "value": None}]
        self._panel("stat", title, [(expr, "")], w, h, unit, {
            "fieldConfig": {"defaults": {"unit": unit, "thresholds": {"mode": "absolute", "steps": steps}}, "overrides": []},
            "options": {"colorMode": "background", "graphMode": "area", "reduceOptions": {"calcs": ["lastNotNull"]}},
        }, description)

    def table(self, title, expr, w=24, h=7, description=""):
        self._panel("table", title, [(expr, "")], w, h, "short", {
            "options": {"showHeader": True},
            "transformations": [{"id": "labelsToFields", "options": {}}],
        }, description)

    def json(self) -> str:
        return json.dumps({
            "uid": self.uid,
            "title": self.title,
            "description": self.description,
            "tags": ["opencs"],
            "timezone": "browser",
            "schemaVersion": 39,
            "version": 1,
            "refresh": "30s",
            "time": {"from": "now-6h", "to": "now"},
            "panels": self.panels,
            "templating": {"list": []},
        }, indent=1)


RED = [{"color": "green", "value": None}, {"color": "red", "value": 1}]
UP = [{"color": "red", "value": None}, {"color": "green", "value": 1}]


def dashboards() -> dict[str, str]:
    boards: dict[str, str] = {}

    b = Board("opencs-overview", "OpenCS / Cluster overview", "Health of all 12 nodes: alerts, availability, memory, CPU.")
    b.stat("Firing alerts", 'count(ALERTS{alertstate="firing"}) or vector(0)', thresholds=RED)
    b.stat("Nodes up", 'sum(up{job="agent"})', thresholds=[{"color": "red", "value": None}, {"color": "green", "value": 12}])
    b.stat("APIs up", 'sum(up{job="api"})', thresholds=[{"color": "red", "value": None}, {"color": "orange", "value": 3}, {"color": "green", "value": 4}])
    b.stat("Requests / s", "sum(rate(opencs_edge_requests_total[5m]))", unit="reqps")
    b.stat("5xx rate", 'sum(rate(opencs_edge_requests_total{status_class="5xx"}[5m])) / clamp_min(sum(rate(opencs_edge_requests_total[5m])), 0.001)',
           unit="percentunit", thresholds=[{"color": "green", "value": None}, {"color": "orange", "value": 0.01}, {"color": "red", "value": 0.05}])
    b.stat("API p95", 'histogram_quantile(0.95, sum(rate(opencs_edge_request_duration_seconds_bucket{area="api"}[5m])) by (le))',
           unit="s", thresholds=[{"color": "green", "value": None}, {"color": "orange", "value": 0.2}, {"color": "red", "value": 0.5}])
    b.table("Firing alerts", 'ALERTS{alertstate="firing"}', h=6, description="Alerts are evaluated by vmalert and shown here only.")
    b.row("Resources per node")
    b.ts("Memory in use (anon) vs 512 MiB limit", [('opencs_cgroup_memory_bytes{type="anon"} / on(node) opencs_cgroup_memory_bytes{type="limit"}', "{{node}}")],
         unit="percentunit", description="Non-reclaimable memory as a share of the cgroup limit. Page cache is excluded.")
    b.ts("CPU (cores used, quota = 1)", [("rate(opencs_cgroup_cpu_seconds_total[5m])", "{{node}}")], unit="short")
    b.ts("Memory pressure (PSI some, avg10)", [('opencs_cgroup_pressure_avg10{resource="memory",kind="some"}', "{{node}}")], unit="percent")
    b.ts("CPU throttling", [("rate(opencs_cgroup_cpu_throttled_seconds_total[5m])", "{{node}}")], unit="s")
    b.row("Services")
    b.table("Service status (1 = running)", "opencs_service_up", h=8)
    b.ts("Restarts (15 min)", [("increase(opencs_service_restarts_total[15m])", "{{node}} {{service}}")])
    b.ts("Error log lines / min", [("rate(opencs_log_errors_total[5m]) * 60", "{{node}} {{service}}")])
    b.ts("Disk free", [("opencs_disk_free_bytes", "{{node}}")], unit="bytes", w=12)
    b.ts("OOM kills", [("increase(opencs_cgroup_oom_kills_total[1h])", "{{node}}")], w=12)
    boards["overview.json"] = b.json()

    b = Board("opencs-edge-api", "OpenCS / Edge & API", "Golden signals at the edge and inside the API.")
    b.ts("Requests / s by area", [("sum by (area) (rate(opencs_edge_requests_total[5m]))", "{{area}}")], unit="reqps", w=8)
    b.ts("Status classes", [("sum by (status_class) (rate(opencs_edge_requests_total[5m]))", "{{status_class}}")], unit="reqps", w=8)
    b.ts("Backend spread (round-robin)", [("sum by (upstream) (rate(opencs_edge_upstream_requests_total[5m]))", "{{upstream}}")], unit="reqps", w=8)
    b.ts("API latency at the edge", [
        (f'histogram_quantile({q}, sum(rate(opencs_edge_request_duration_seconds_bucket{{area="api"}}[5m])) by (le))', f"p{int(float(q) * 100)}")
        for q in ("0.5", "0.95", "0.99")
    ], unit="s")
    b.ts("Notebook traffic latency (edge → shard)", [
        (f'histogram_quantile({q}, sum(rate(opencs_edge_request_duration_seconds_bucket{{area="notebook"}}[5m])) by (le))', f"p{int(float(q) * 100)}")
        for q in ("0.5", "0.95")
    ], unit="s")
    b.row("Inside the API")
    b.ts("Slowest routes (p95)", [("topk(8, histogram_quantile(0.95, sum by (route, le) (rate(opencs_http_request_duration_seconds_bucket[10m]))))", "{{route}}")], unit="s", w=24, h=9)
    b.ts("Requests / s per API node", [("sum by (node) (rate(opencs_http_requests_total[5m]))", "{{node}}")], unit="reqps")
    b.ts("5xx per route", [('sum by (route) (rate(opencs_http_requests_total{status=~"5.."}[5m]))', "{{route}}")], unit="reqps")
    b.ts("Notebook launches", [("sum by (result) (rate(opencs_notebook_launches_total[15m]))", "{{result}}")], unit="reqps")
    b.ts("API process memory (RSS)", [('process_resident_memory_bytes{job="api"}', "{{node}}")], unit="bytes")
    boards["edge-api.json"] = b.json()

    b = Board("opencs-data", "OpenCS / Database, jobs & backups", "PostgreSQL primary/standby, the job outbox and backups.")
    b.stat("Primary up", 'max(opencs_pg_up{role="pg-primary"})', thresholds=UP)
    b.stat("Standby streaming", 'max(opencs_pg_replicas_streaming{role="pg-primary"})', thresholds=UP)
    b.stat("Replication lag", 'max(opencs_pg_replication_lag_bytes{role="pg-primary"})', unit="bytes",
           thresholds=[{"color": "green", "value": None}, {"color": "orange", "value": 16e6}, {"color": "red", "value": 64e6}])
    b.stat("Pending jobs", 'sum(opencs_jobs{status="pending"}) or vector(0)',
           thresholds=[{"color": "green", "value": None}, {"color": "orange", "value": 20}, {"color": "red", "value": 50}])
    b.stat("Oldest pending job", "max(opencs_oldest_pending_job_seconds)", unit="s",
           thresholds=[{"color": "green", "value": None}, {"color": "orange", "value": 120}, {"color": "red", "value": 600}])
    b.stat("Last backup age", "max(opencs_backup_age_seconds)", unit="s",
           thresholds=[{"color": "green", "value": None}, {"color": "orange", "value": 90000}, {"color": "red", "value": 93600}])
    b.ts("Connections by state", [("opencs_pg_connections", "{{node}} {{state}}")])
    b.ts("Transactions / s", [("rate(opencs_pg_xact_commit_total[5m])", "{{node}} commit"), ("rate(opencs_pg_xact_rollback_total[5m])", "{{node}} rollback")])
    b.ts("Cache hit ratio", [("rate(opencs_pg_blks_hit_total[5m]) / clamp_min(rate(opencs_pg_blks_hit_total[5m]) + rate(opencs_pg_blks_read_total[5m]), 1)", "{{node}}")], unit="percentunit")
    b.ts("Replication lag (bytes)", [('opencs_pg_replication_lag_bytes{role="pg-primary"}', "lag")], unit="bytes")
    b.ts("Job outbox", [("opencs_jobs", "{{status}}")])
    b.ts("Database size", [("opencs_pg_db_size_bytes", "{{node}}")], unit="bytes")
    boards["data.json"] = b.json()

    b = Board("opencs-notebooks", "OpenCS / Notebooks", "JupyterHub shards: health and capacity.")
    b.stat("Running notebook servers", "sum(opencs_hub_running_servers)", w=6)
    b.stat("Capacity", "sum(opencs_hub_server_limit)", w=6)
    b.stat("Utilisation", "sum(opencs_hub_running_servers) / clamp_min(sum(opencs_hub_server_limit), 1)", w=6, unit="percentunit",
           thresholds=[{"color": "green", "value": None}, {"color": "orange", "value": 0.7}, {"color": "red", "value": 0.85}])
    b.stat("Hubs up", "sum(opencs_hub_up)", w=6, thresholds=[{"color": "red", "value": None}, {"color": "green", "value": 4}])
    b.ts("Running servers per shard", [("opencs_hub_running_servers", "{{node}}")], w=12)
    b.ts("Shard memory (anon) vs limit", [('opencs_cgroup_memory_bytes{type="anon",role="hub"} / on(node) opencs_cgroup_memory_bytes{type="limit",role="hub"}', "{{node}}")], w=12, unit="percentunit")
    b.ts("Notebook launch time p95", [("histogram_quantile(0.95, sum(rate(opencs_notebook_launch_duration_seconds_bucket[30m])) by (le))", "p95")], unit="s", w=12)
    b.ts("Active notebook sessions (API view)", [("max(opencs_active_notebook_sessions)", "sessions")], w=12)
    boards["notebooks.json"] = b.json()
    return boards
