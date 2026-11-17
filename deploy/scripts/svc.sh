#!/usr/bin/env bash
# OpenCS Labs — minimal process supervisor for hosts without systemd.
#
# The deployment targets run PID 1 = sshd, so `systemctl` cannot manage
# services. This script provides the subset we actually need: start, stop,
# restart, status, and a keep-alive loop that restarts a crashed service with
# backoff. It is intentionally small and dependency-free (no supervisor,
# runit, s6 or tmux is installed on the targets).
#
# Usage:
#   svc.sh start   <service> [--foreground-log]
#   svc.sh stop    <service>
#   svc.sh restart <service>
#   svc.sh status  <service>
#   svc.sh supervise <service>     # keep-alive loop (spawned detached)
#   svc.sh list
#
# State lives in $RUNTIME_DIR (default ~/opencs-runtime):
#   run/<service>.pid      supervisor PID
#   run/<service>.app.pid  child process PID
#   logs/<service>.log     stdout/stderr
set -uo pipefail

RUNTIME_DIR="${OPENCE_RUNTIME_DIR:-$HOME/opencs-runtime}"
RUN_DIR="$RUNTIME_DIR/run"
LOG_DIR="$RUNTIME_DIR/logs"
mkdir -p "$RUN_DIR" "$LOG_DIR"

BACKOFF_INITIAL=2
BACKOFF_MAX=60

log() { printf '%s [svc] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }

# --- service definitions ---------------------------------------------------
# Each service: <start command>. The command must run in the foreground;
# the supervisor owns backgrounding. Paths are absolute so the service does
# not depend on the caller's cwd.
service_cmd() {
  case "$1" in
    backend)
      # Bind 0.0.0.0 (not 127.0.0.1): the load balancer runs on a *different*
      # container and reaches this backend over the docker bridge network.
      # Firewalling is handled at the host: see docs/deployment/NETWORK_AND_SECURITY.md.
      #
      # ONE worker by default. Each container is capped at 512 MiB
      # (cgroup memory.max, measured in Phase 0). Importing pandas + scikit-learn
      # + pyarrow costs ~350-400 MiB RSS, so a second worker drives the node into
      # the OOM killer. Horizontal scale is the three backend containers, not
      # workers within a container.
      echo 'cd "$HOME/opencs-labs/backend" && set -a && . "$HOME/opencs-runtime/.env" && set +a && exec "$HOME/opencs-runtime/venv/bin/uvicorn" app.main:app --host "${OPENCE_BACKEND_HOST:-0.0.0.0}" --port "${OPENCE_BACKEND_PORT:-8000}" --workers "${OPENCE_BACKEND_WORKERS:-1}" --limit-concurrency 64 --proxy-headers --forwarded-allow-ips="*"'
      ;;
    *)
      return 1
      ;;
  esac
}

pid_of() {  # supervisor pid
  local f="$RUN_DIR/$1.pid"
  [[ -f "$f" ]] && cat "$f" 2>/dev/null
}

child_pid_of() {
  local f="$RUN_DIR/$1.app.pid"
  [[ -f "$f" ]] && cat "$f" 2>/dev/null
}

is_running() {
  local pid; pid=$(pid_of "$1")
  [[ -n "${pid:-}" ]] && kill -0 "$pid" 2>/dev/null
}

# --- keep-alive loop -------------------------------------------------------
# Restarts the service when it exits. Backoff resets after the process has
# stayed up for BACKOFF_MAX seconds, so a crash loop cannot spin at full speed.
supervise() {
  local name="$1" cmd log_file child uptime_seconds backoff=$BACKOFF_INITIAL
  cmd=$(service_cmd "$name") || { log "unknown service: $name"; exit 64; }
  log_file="$LOG_DIR/$name.log"

  log "supervisor starting for $name"
  while true; do
    local started_at; started_at=$(date +%s)
    bash -c "$cmd" >>"$log_file" 2>&1 &
    child=$!
    echo "$child" > "$RUN_DIR/$name.app.pid"
    log "$name started (pid $child)"

    wait "$child"
    local rc=$?
    uptime_seconds=$(( $(date +%s) - started_at ))
    log "$name exited rc=$rc after ${uptime_seconds}s"

    # A stop request removes the pid file; honour it before restarting.
    if [[ ! -f "$RUN_DIR/$name.pid" ]]; then
      log "$name stopped by request"
      exit 0
    fi

    if (( uptime_seconds >= BACKOFF_MAX )); then
      backoff=$BACKOFF_INITIAL
    fi
    log "$name restarting in ${backoff}s"
    sleep "$backoff"
    (( backoff = backoff * 2 > BACKOFF_MAX ? BACKOFF_MAX : backoff * 2 ))
  done
}

# --- commands --------------------------------------------------------------
cmd_start() {
  local name="$1"
  local cmd; cmd=$(service_cmd "$name") || { log "unknown service: $name"; exit 64; }
  if is_running "$name"; then
    log "$name already running (pid $(pid_of "$name"))"
    return 0
  fi
  rm -f "$RUN_DIR/$name.app.pid"
  setsid bash -c "$(printf '%q ' "$0" supervise "$name")" >>"$LOG_DIR/$name.supervisor.log" 2>&1 &
  local sup=$!
  echo "$sup" > "$RUN_DIR/$name.pid"
  sleep 2
  if is_running "$name"; then
    log "$name supervisor up (pid $sup), child $(child_pid_of "$name")"
  else
    log "$name failed to start; see $LOG_DIR/$name.supervisor.log"
    return 1
  fi
}

cmd_stop() {
  local name="$1" pid child
  pid=$(pid_of "$name")
  child=$(child_pid_of "$name")
  if [[ -z "${pid:-}" ]]; then
    log "$name not running"
    rm -f "$RUN_DIR/$name.pid" "$RUN_DIR/$name.app.pid"
    return 0
  fi
  # Remove the pid file first so the supervisor loop does not restart the child.
  rm -f "$RUN_DIR/$name.pid"
  [[ -n "${child:-}" ]] && kill "$child" 2>/dev/null
  kill "$pid" 2>/dev/null
  for _ in $(seq 1 20); do
    kill -0 "$pid" 2>/dev/null || break
    sleep 0.5
  done
  kill -9 "$pid" 2>/dev/null
  rm -f "$RUN_DIR/$name.app.pid"
  log "$name stopped"
}

cmd_status() {
  local name="$1"
  if is_running "$name"; then
    log "$name: running (supervisor $(pid_of "$name"), child $(child_pid_of "$name"))"
  else
    log "$name: stopped"
    return 1
  fi
}

cmd_list() {
  for f in "$RUN_DIR"/*.pid; do
    [[ -e "$f" ]] || continue
    cmd_status "$(basename "$f" .pid)"
  done
}

case "${1:-}" in
  start)     shift; cmd_start "${1:?service name required}" ;;
  stop)      shift; cmd_stop "${1:?service name required}" ;;
  restart)   shift; cmd_stop "${1:?service name required}"; cmd_start "$1" ;;
  status)    shift; cmd_status "${1:?service name required}" ;;
  supervise) shift; supervise "${1:?service name required}" ;;
  list)      cmd_list ;;
  *) echo "usage: $0 {start|stop|restart|status|supervise|list} [service]" >&2; exit 64 ;;
esac
