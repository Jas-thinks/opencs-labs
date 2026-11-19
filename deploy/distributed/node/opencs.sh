#!/usr/bin/env bash
# OpenCS Labs - per-node process supervisor for the 12-node deployment.
#
# Installed at ~/opencs/bin/opencs.sh on every node. The nodes are containers
# with PID 1 = sshd: no systemd, no cron, and nothing restarts on a container
# restart. This gives each service a keep-alive loop with backoff; the
# control node's watchdog covers whole-node restarts.
#
#   opencs.sh start|stop|restart|status <service>
#   opencs.sh list                  # status of every service started here
#   opencs.sh rotate                # copy-truncate logs larger than 20 MiB
#
# Services: api | worker | hub | edge | watchdog | agent | vm | vmalert | grafana
#
# Layout (~/opencs):
#   current -> releases/<sha>   code
#   venv/  nb-venv/  npm/       runtimes
#   env/                        rendered config (0600), never edited by hand
#   run/  logs/  tmp/  data/  datasets/  frontend/  backups/
set -uo pipefail

ROOT="${OPENCE_RUNTIME_DIR:-$HOME/opencs}"
RUN="$ROOT/run"; LOGS="$ROOT/logs"
mkdir -p "$RUN" "$LOGS" "$ROOT/tmp"
BACKOFF_INITIAL=2
BACKOFF_MAX=60
ROTATE_BYTES=$((20 * 1024 * 1024))

log() { printf '%s [opencs] %s\n' "$(date -u +%FT%TZ)" "$*"; }

service_cmd() {
  case "$1" in
    api|worker)
      # One worker per node: the cgroup is 1 CPU / 512 MiB, so scale-out is
      # more nodes, not more workers. uvloop + httptools: lowest per-request
      # overhead. No access log here - the edge logs every request once.
      cat <<EOF
cd "$ROOT/current/backend" && set -a && . "$ROOT/env/$1.env" && set +a && \
exec "$ROOT/venv/bin/uvicorn" app.main:app \
  --host "\$OPENCE_BACKEND_HOST" --port "\$OPENCE_BACKEND_PORT" --workers 1 \
  --loop uvloop --http httptools --no-access-log \
  --timeout-keep-alive 5 --limit-concurrency 128 \
  --proxy-headers --forwarded-allow-ips='*'
EOF
      ;;
    hub)
      cat <<EOF
cd "$ROOT/current/jupyterhub" && set -a && . "$ROOT/env/hub.env" && set +a && \
export PYTHONPATH="$ROOT/current/jupyterhub" && \
exec "$ROOT/nb-venv/bin/jupyterhub" -f jupyterhub_config.py
EOF
      ;;
    edge)
      mkdir -p "$ROOT/tmp/client" "$ROOT/tmp/proxy" "$ROOT/tmp/fastcgi" "$ROOT/tmp/uwsgi" "$ROOT/tmp/scgi"
      echo "exec nginx -p '$ROOT' -c '$ROOT/env/edge.conf' -g 'daemon off;'"
      ;;
    watchdog)
      echo "exec bash '$ROOT/bin/watchdog.sh'"
      ;;
    agent)
      # Node metrics exporter (stdlib only), every node. ADR-011.
      echo "set -a && . '$ROOT/env/agent.env' && set +a && exec python3 '$ROOT/bin/agent.py'"
      ;;
    vm)
      # VictoriaMetrics: scrapes every agent/API and stores 30 days of metrics.
      # memory.allowedBytes caps its caches inside the 512 MiB cgroup.
      cat <<EOF
set -a && . "$ROOT/env/monitoring.env" && set +a && \
exec "$ROOT/monitoring/victoria-metrics-prod" \
  -storageDataPath="$ROOT/data/vm" -retentionPeriod="\$VM_RETENTION" \
  -httpListenAddr="\$MON_IP:8428" -promscrape.config="$ROOT/env/scrape.yml" \
  -memory.allowedBytes=64MiB -search.maxConcurrentRequests=4 -loggerLevel=WARN
EOF
      ;;
    vmalert)
      # Alert rules; firing state is written back as ALERTS series (UI only,
      # no notifier) and shown in Grafana.
      cat <<EOF
set -a && . "$ROOT/env/monitoring.env" && set +a && \
exec "$ROOT/monitoring/vmalert-prod" -rule="$ROOT/env/alerts.yml" \
  -datasource.url="http://\$MON_IP:8428" -remoteWrite.url="http://\$MON_IP:8428" \
  -remoteRead.url="http://\$MON_IP:8428" -notifier.blackhole \
  -httpListenAddr=127.0.0.1:8880 -evaluationInterval=30s -loggerLevel=WARN
EOF
      ;;
    grafana)
      echo "exec '$ROOT/monitoring/grafana/bin/grafana' server --homepath '$ROOT/monitoring/grafana' --config '$ROOT/env/grafana.ini'"
      ;;
    runner)
      # GitHub Actions self-hosted runner (edge node only; ADR-011). Started
      # by ~/actions-runner/register-opencs.sh once it is registered.
      echo "cd \"\$HOME/actions-runner\" && exec ./run.sh"
      ;;
    *) return 1 ;;
  esac
}

sup_pid()   { [[ -f "$RUN/$1.pid" ]] && cat "$RUN/$1.pid" 2>/dev/null; }
child_pid() { [[ -f "$RUN/$1.app.pid" ]] && cat "$RUN/$1.app.pid" 2>/dev/null; }
running()   { local p; p=$(sup_pid "$1"); [[ -n "${p:-}" ]] && kill -0 "$p" 2>/dev/null; }

supervise() {
  local name="$1" cmd backoff=$BACKOFF_INITIAL
  cmd=$(service_cmd "$name") || { log "unknown service $name"; exit 64; }
  log "supervisor up for $name"
  while true; do
    local t0; t0=$(date +%s)
    # setsid: the child gets its own process group, so stop can kill the
    # whole tree (JupyterHub's proxy, culler and user servers included).
    setsid bash -c "$cmd" >>"$LOGS/$name.log" 2>&1 &
    local child=$!
    echo "$child" > "$RUN/$name.app.pid"
    log "$name started pid=$child"
    wait "$child"; local rc=$?
    local up=$(( $(date +%s) - t0 ))
    log "$name exited rc=$rc after ${up}s"
    [[ -f "$RUN/$name.pid" ]] || { log "$name stopped by request"; exit 0; }
    (( up >= BACKOFF_MAX )) && backoff=$BACKOFF_INITIAL
    log "$name restarting in ${backoff}s"
    sleep "$backoff"
    backoff=$(( backoff * 2 > BACKOFF_MAX ? BACKOFF_MAX : backoff * 2 ))
  done
}

cmd_start() {
  local name="$1"
  service_cmd "$name" >/dev/null || { log "unknown service $name"; return 64; }
  if running "$name"; then log "$name already running"; return 0; fi
  rm -f "$RUN/$name.app.pid"
  setsid bash "$0" supervise "$name" >>"$LOGS/$name.supervisor.log" 2>&1 < /dev/null &
  echo $! > "$RUN/$name.pid"
  sleep 1
  running "$name" && log "$name supervisor pid=$(sup_pid "$name")" || { log "$name failed"; return 1; }
}

cmd_stop() {
  local name="$1" sup child
  sup=$(sup_pid "$name"); child=$(child_pid "$name")
  rm -f "$RUN/$name.pid"                 # tells the loop not to restart
  if [[ -n "${child:-}" ]]; then
    kill -TERM -- "-$child" 2>/dev/null || kill -TERM "$child" 2>/dev/null
    for _ in $(seq 1 30); do kill -0 "$child" 2>/dev/null || break; sleep 0.5; done
    kill -KILL -- "-$child" 2>/dev/null || true
  fi
  [[ -n "${sup:-}" ]] && kill "$sup" 2>/dev/null
  rm -f "$RUN/$name.app.pid"
  log "$name stopped"
}

cmd_status() {
  if running "$1"; then
    log "$1 running sup=$(sup_pid "$1") child=$(child_pid "$1")"
  else
    log "$1 stopped"; return 1
  fi
}

cmd_rotate() {
  local f
  for f in "$LOGS"/*.log; do
    [[ -f "$f" ]] || continue
    if (( $(stat -c %s "$f") > ROTATE_BYTES )); then
      cp "$f" "$f.1" && : > "$f" && log "rotated $f"
    fi
  done
  # nginx keeps its own fds; ask it to reopen after truncation.
  [[ -f "$RUN/edge.nginx.pid" ]] && kill -USR1 "$(cat "$RUN/edge.nginx.pid")" 2>/dev/null
  return 0
}

case "${1:-}" in
  start)     cmd_start   "${2:?service}" ;;
  stop)      cmd_stop    "${2:?service}" ;;
  restart)   cmd_stop    "${2:?service}"; cmd_start "$2" ;;
  status)    cmd_status  "${2:?service}" ;;
  supervise) supervise   "${2:?service}" ;;
  rotate)    cmd_rotate ;;
  list)      rc=0; for f in "$RUN"/*.pid; do
               n=$(basename "$f" .pid); [[ -e "$f" && "$n" != *.* ]] || continue  # skip *.app.pid, edge.nginx.pid
               cmd_status "$n" || rc=1; done; exit $rc ;;
  *) echo "usage: $0 {start|stop|restart|status} <api|worker|hub|edge|watchdog|agent|vm|vmalert|grafana> | list | rotate" >&2; exit 64 ;;
esac
