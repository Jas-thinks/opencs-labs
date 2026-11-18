#!/usr/bin/env bash
# OpenCS Labs - cluster watchdog (runs on the control node under opencs.sh).
#
# Every INTERVAL seconds:
#   * health-checks each target in env/watchdog.targets
#   * after FAILS consecutive failures, SSHes to the node and (re)starts the
#     service. That also covers a container restart, after which nothing on
#     the node starts by itself (PID 1 is sshd).
#   * PostgreSQL is only ever *started*, never promoted. Failover is a manual
#     runbook step (README) so the watchdog can never cause split-brain.
#   * rotates logs hourly and takes a database backup daily.
#
# SSH uses ~/.ssh/opencs_cluster_ed25519, authorised on every node.
set -uo pipefail

ROOT="${OPENCE_RUNTIME_DIR:-$HOME/opencs}"
TARGETS="$ROOT/env/watchdog.targets"
INTERVAL=15
FAILS=3
KEY="$HOME/.ssh/opencs_cluster_ed25519"
SSH=(ssh -i "$KEY" -o IdentitiesOnly=yes -o BatchMode=yes -o ConnectTimeout=5
     -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile="$HOME/.ssh/known_hosts_opencs")
STATUS="$ROOT/run/cluster-status"
declare -A fails=()
last_rotate=0
last_backup=$(stat -c %Y "$ROOT/backups/latest.dump" 2>/dev/null || echo 0)

log() { printf '%s [watchdog] %s\n' "$(date -u +%FT%TZ)" "$*"; }

check() {  # kind target -> 0 healthy
  case "$1" in
    http) curl -fsS -o /dev/null --max-time 4 "$2" ;;
    pg)   pg_isready -q -h "$2" -p 5432 -t 3 ;;
  esac
}

remediate() {  # alias ssh_host ssh_port service
  local alias="$1" host="$2" port="$3" svc="$4"
  if [[ "$svc" == postgres ]]; then
    log "$alias: starting PostgreSQL (never promoting)"
    "${SSH[@]}" -p "$port" "student@$host" 'sudo -n -u postgres /usr/bin/pg_ctlcluster 16 main start' 2>&1 | tail -2
  else
    log "$alias: restarting $svc"
    "${SSH[@]}" -p "$port" "student@$host" "bash ~/opencs/bin/opencs.sh restart $svc" 2>&1 | tail -2
  fi
}

backup() {
  set -a; . "$ROOT/env/backup.env"; set +a
  local dir="$ROOT/backups" stamp; stamp=$(date -u +%Y%m%dT%H%M%SZ)
  mkdir -p "$dir"
  if pg_dump -Fc -Z 6 -f "$dir/opencs-$stamp.dump"; then
    ln -sfn "opencs-$stamp.dump" "$dir/latest.dump"
    ls -1t "$dir"/opencs-*.dump | tail -n +8 | xargs -r rm -f          # keep 7
    # Host A is one physical machine: a backup that stays on it is not a backup.
    local h=${OFFHOST%:*} p=${OFFHOST#*:}
    "${SSH[@]}" -p "$p" "student@$h" 'mkdir -p ~/opencs/backups-offhost' \
      && "${SSH[@]}" -p "$p" "student@$h" "cat > ~/opencs/backups-offhost/opencs-$stamp.dump" < "$dir/opencs-$stamp.dump" \
      && "${SSH[@]}" -p "$p" "student@$h" 'ls -1t ~/opencs/backups-offhost/*.dump | tail -n +8 | xargs -r rm -f' \
      && log "backup opencs-$stamp.dump stored locally and off-host"
  else
    log "backup FAILED"
  fi
}

log "watchdog up: $(grep -vc '^#' "$TARGETS") targets, every ${INTERVAL}s"
while true; do
  summary=""
  while IFS='|' read -r alias kind target host port svc; do
    [[ -z "$alias" || "$alias" == \#* ]] && continue
    if check "$kind" "$target"; then
      (( ${fails[$alias]:-0} > 0 )) && log "$alias: healthy again"
      fails[$alias]=0; summary+="$alias=up "
    else
      fails[$alias]=$(( ${fails[$alias]:-0} + 1 )); summary+="$alias=DOWN(${fails[$alias]}) "
      log "$alias: check failed (${fails[$alias]}/$FAILS) $target"
      if (( fails[$alias] == FAILS || (fails[$alias] > FAILS && fails[$alias] % 20 == 0) )); then
        remediate "$alias" "$host" "$port" "$svc"
      fi
    fi
  done < "$TARGETS"
  printf '%s %s\n' "$(date -u +%FT%TZ)" "$summary" > "$STATUS"

  now=$(date +%s)
  if (( now - last_rotate >= 3600 )); then
    last_rotate=$now
    bash "$ROOT/bin/opencs.sh" rotate >/dev/null
    while IFS='|' read -r alias kind target host port svc; do
      [[ -z "$alias" || "$alias" == \#* || "$svc" == postgres ]] && continue
      "${SSH[@]}" -p "$port" "student@$host" 'bash ~/opencs/bin/opencs.sh rotate' >/dev/null 2>&1 &
    done < "$TARGETS"
    wait
  fi
  if (( now - last_backup >= 86400 )); then
    last_backup=$now
    backup
  fi
  sleep "$INTERVAL"
done
