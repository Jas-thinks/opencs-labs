#!/usr/bin/env bash
# OpenCS Labs - 12-node deployment orchestrator (runs on the operator machine).
#
#   deploy/distributed/deploy.sh <command> [args]
#
# Phases (each idempotent; run in this order for a fresh cluster):
#   render                 secrets + per-node config into build/
#   preflight              key login + role ports + free memory on every node
#   cleanup                dump & stop the pre-existing deployments (asks first)
#   release                build artifacts, ship code/frontend/datasets/config
#   runtimes               build venvs once per host, copy to peers
#   postgres               primary + streaming hot standby
#   migrate                alembic upgrade head + seed (control node, once)
#   start [alias|role|all] start services (edge last)
#   status                 one line per node
#   verify                 end-to-end checks + latency sample through the edge
#   rollout                zero-downtime code update: release + rolling API restart
#   rollback               repoint `current` to the previous release everywhere
#   monitoring             VictoriaMetrics + vmalert + Grafana + node agents (ADR-011)
#   logs [who] [svc] [re]  tail or grep service logs across the cluster
#   config [service ...]   re-render + ship config only, restart services
#
# Needs: ~/.ssh/opencs_deploy_ed25519 (authorised on all nodes),
#        secrets/sudo.env with lines `<alias>=<sudo password>` (gitignored).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
BUILD="$HERE/build"
CFG="$BUILD/ssh_config"
INV="$HERE/inventory.json"
ART="$BUILD/artifacts"

say()  { printf '\033[1m==> %s\033[0m\n' "$*"; }
die()  { printf 'error: %s\n' "$*" >&2; exit 1; }
r()    { ssh -F "$CFG" "$@"; }                        # r <alias> <cmd>
q()    { python3 -c "import json,sys;inv=json.load(open('$INV'));$1"; }
aliases() { q "print(' '.join(n['alias'] for n in inv['nodes'] if '$1' in ('all',n['role'],n['alias'])))"; }
ip_of()   { q "print(next(n['ip'] for n in inv['nodes'] if n['alias']=='$1'))"; }
sudo_pw() { grep "^$1=" "$HERE/secrets/sudo.env" | cut -d= -f2-; }
rsudo()   { local a=$1; shift; r "$a" "sudo -S -p '' bash -c $(printf '%q' "$*")" <<<"$(sudo_pw "$a")"; }
each()    { local pids=() a; for a in $1; do ( "$2" "$a" 2>&1 | sed "s/^/[$a] /" ) & pids+=($!); done
            local rc=0; for p in "${pids[@]}"; do wait "$p" || rc=1; done; return $rc; }
ROOT=/home/student/opencs

# --------------------------------------------------------------------------- #
cmd_render() { python3 "$HERE/render.py"; }

cmd_preflight() {
  [[ -f "$CFG" ]] || cmd_render
  _pf() {
    r "$1" 'printf "%s mem=%sMiB/512 load=%s " "$(hostname)" $(( $(cat /sys/fs/cgroup/memory.current) / 1048576 )) "$(cut -d" " -f1 /proc/loadavg)";
            for p in 5000 8000 5432; do ss -ltn | grep -q ":$p " && printf "busy:%s " $p; done; echo'
  }
  each "$(aliases all)" _pf
}

# --------------------------------------------------------------------------- #
# Phase 0: the pre-existing deployments. Dumps every opencs database to the
# operator machine first, then stops only OpenCS processes (tmux sessions
# opencs-*, the old svc.sh supervisors, the stray PostgreSQL on the control
# node). Nothing else on these shared containers is touched.
cmd_cleanup() {
  local dumps="$HERE/secrets/pre-deploy-dumps"; mkdir -p "$dumps"
  say "dumping pre-existing opencs databases to $dumps"
  for a in pg1 pg2 ctl; do
    if rsudo "$a" "sudo -u postgres pg_dump -Fc opencs" > "$dumps/$a-opencs.dump" 2>/dev/null && [[ -s "$dumps/$a-opencs.dump" ]]; then
      echo "  $a: $(du -h "$dumps/$a-opencs.dump" | cut -f1)"
    else
      rm -f "$dumps/$a-opencs.dump"; echo "  $a: no opencs database"
    fi
  done
  if [[ "${YES:-}" != 1 ]]; then
    read -r -p "Stop the old OpenCS processes on all nodes? [y/N] " ok; [[ "$ok" == y ]] || die "aborted"
  fi
  _stop() {
    r "$1" 'for s in $(tmux ls -F "#{session_name}" 2>/dev/null | grep "^opencs-"); do tmux kill-session -t "$s" && echo "killed tmux $s"; done
            for d in ~/opencs-runtime; do [ -x $d/svc.sh ] && for p in $d/run/*.pid; do [ -e "$p" ] && OPENCE_RUNTIME_DIR=$d bash $d/svc.sh stop "$(basename "$p" .pid)"; done; done 2>/dev/null
            sleep 1; ss -ltn | grep -E ":(5000|6000|8000) " || echo "role ports free"'
  }
  each "$(aliases all)" _stop
  say "stopping the stray PostgreSQL on the control node"
  rsudo ctl "pg_ctlcluster 16 main stop 2>/dev/null; echo manual > /etc/postgresql/16/main/start.conf; echo stopped"
}

# --------------------------------------------------------------------------- #
# Artifacts are built on the operator machine: the targets have no Node.js
# (frontend) and PyPI is blocked on some of them.
build_artifacts() {
  local sha; sha=$(git -C "$REPO" rev-parse --short=12 HEAD)
  [[ -z "$(git -C "$REPO" status --porcelain --untracked-files=no)" ]] || die "commit first: a release is an exact commit"
  rm -rf "$ART"; mkdir -p "$ART"
  say "release $sha"
  git -C "$REPO" archive --format=tar --prefix="$sha/" HEAD | gzip -1 > "$ART/code.tgz"
  echo "$sha" > "$ART/SHA"

  say "frontend (same-origin API base)"
  (cd "$REPO/frontend" && npm ci --no-audit --no-fund --silent && VITE_API_BASE=/api/v1 npm run build --silent)
  find "$REPO/frontend/dist" -type f \( -name '*.js' -o -name '*.css' -o -name '*.html' -o -name '*.svg' \) -exec gzip -9 -k -f {} \;
  tar -C "$REPO/frontend/dist" -czf "$ART/frontend.tgz" .

  say "datasets"
  [[ -d "$REPO/datasets/serving" ]] || "$REPO/backend/.venv/bin/python" "$REPO/scripts/fetch_datasets.py"
  git -C "$REPO" checkout -- datasets/manifests 2>/dev/null || true   # drop timestamp-only churn
  tar -C "$REPO/datasets" -czf "$ART/datasets.tgz" serving

  say "jupyterlab extension (needs Node >= 20.19 on PATH, or NODE22=/path/to/bin)"
  local ext="$BUILD/ext"; rm -rf "$ext"; mkdir -p "$ext"
  cp -r "$REPO/jupyterlab-extension/"{package.json,package-lock.json,tsconfig.json,schema,style,src} "$ext/"
  ( cd "$ext" && export PATH="${NODE22:+$NODE22:}${JLAB_VENV:+$JLAB_VENV/bin:}$PATH" \
    && npm ci --include=dev --no-audit --no-fund --silent && npx tsc && jupyter labextension build . >/dev/null )
  tar -C "$ext/opencs_jupyterlab_datasets/labextension" -czf "$ART/labextension.tgz" .
  ls -la "$ART"
}

ship() {  # alias: code + scripts + env + role artifacts, then flip `current`
  local a=$1 sha role; sha=$(cat "$ART/SHA"); role=$(q "print(next(n['role'] for n in inv['nodes'] if n['alias']=='$a'))")
  r "$a" "mkdir -p $ROOT/{releases,env,bin,run,logs,tmp,data,backups} && chmod 700 $ROOT/env"
  r "$a" "cd $ROOT/releases && [ -d $sha ] || tar xzf -" < "$ART/code.tgz"
  r "$a" "cat > $ROOT/bin/opencs.sh && chmod +x $ROOT/bin/opencs.sh" < "$HERE/node/opencs.sh"
  r "$a" "cat > $ROOT/bin/watchdog.sh" < "$HERE/node/watchdog.sh"
  r "$a" "umask 077; tar -C $ROOT/env -xf -" < <(tar -C "$BUILD/$a" -cf - .)
  r "$a" "cat > $ROOT/bin/agent.py" < "$HERE/node/agent.py"
  case "$role" in
    edge|control) r "$a" "rm -rf $ROOT/frontend.new && mkdir $ROOT/frontend.new && tar xzf - -C $ROOT/frontend.new && rm -rf $ROOT/frontend.old && { [ -d $ROOT/frontend ] && mv $ROOT/frontend $ROOT/frontend.old || true; } && mv $ROOT/frontend.new $ROOT/frontend" < "$ART/frontend.tgz" ;;
  esac
  case "$role" in
    api|control|hub) r "$a" "mkdir -p $ROOT/datasets && tar xzf - -C $ROOT/datasets" < "$ART/datasets.tgz" ;;
  esac
  # Keep the previous release for rollback, prune older ones.
  r "$a" "cd $ROOT && { [ -L current ] && ln -sfn \$(readlink current) previous || true; } && ln -sfn releases/$sha current && ls -1t releases | tail -n +4 | sed 's|^|releases/|' | xargs -r rm -rf; echo current=\$(readlink current)"
}

cmd_release() {
  [[ "${SKIP_BUILD:-}" == 1 && -f "$ART/SHA" ]] || build_artifacts
  cmd_render
  each "$(aliases all)" ship
}

# --------------------------------------------------------------------------- #
# Runtimes. Each venv is built once per physical host on a node that can reach
# PyPI, then streamed to its peers over the docker bridge (same absolute path,
# so console-script shebangs stay valid). SSH agent forwarding carries the
# operator key for the node-to-node hop; nothing private is stored on nodes.
with_agent() {  # a private agent holding only the deploy key, for -A hops
  [[ -n "${OPENCS_AGENT:-}" ]] && return
  eval "$(ssh-agent -s)" >/dev/null; OPENCS_AGENT=$SSH_AGENT_PID
  trap 'kill $OPENCS_AGENT 2>/dev/null' EXIT
  ssh-add -q ~/.ssh/opencs_deploy_ed25519
}

copy_dir() {  # src_alias dst_alias path   (both nodes on the same physical host)
  local dst_ip; dst_ip=$(ip_of "$2")
  with_agent
  # ControlPath=none: a multiplexed master opened without -A would silently
  # drop agent forwarding for this hop.
  ssh -A -o ControlPath=none -F "$CFG" "$1" "tar -C $(dirname "$3") -cf - $(basename "$3") | ssh -o StrictHostKeyChecking=accept-new -o BatchMode=yes student@$dst_ip 'rm -rf $3.tmp && mkdir -p $3.tmp && tar -C $3.tmp -xf - && rm -rf $3 && mv $3.tmp/$(basename "$3") $3 && rmdir $3.tmp && echo copied $3'"
}

build_nb_venv() {  # alias: notebook/Hub runtime + the dataset extension
  local a=$1 sha; sha=$(cat "$ART/SHA")
  r "$a" "set -e; [ -x $ROOT/nb-venv/bin/jupyterhub-singleuser ] && echo 'nb-venv present' && exit 0
          python3 -m venv $ROOT/nb-venv && $ROOT/nb-venv/bin/pip install -q --upgrade pip wheel
          $ROOT/nb-venv/bin/pip install -q --no-cache-dir -r $ROOT/releases/$sha/notebook-image/requirements.lock jupyterhub-idle-culler==2.0.0 PyJWT==2.10.1
          $ROOT/nb-venv/bin/python -m ipykernel install --sys-prefix --name python3 --display-name 'Python 3 (OpenCS)'
          echo nb-venv built"
  r "$a" "d=$ROOT/nb-venv/share/jupyter/labextensions/@opencs/jupyterlab-datasets; rm -rf \$d && mkdir -p \$d && tar xzf - -C \$d && echo extension installed" < "$ART/labextension.tgz"
}

cmd_runtimes() {
  local sha; sha=$(cat "$ART/SHA")
  say "Host A: backend venv + notebook venv on api1 (PyPI reachable)"
  r api1 "set -e; [ -x $ROOT/venv/bin/uvicorn ] || { python3 -m venv $ROOT/venv && $ROOT/venv/bin/pip install -q --upgrade pip wheel && $ROOT/venv/bin/pip install -q --no-cache-dir -r $ROOT/releases/$sha/backend/requirements.txt; }; $ROOT/venv/bin/pip install -q -r $ROOT/releases/$sha/backend/requirements.txt && echo venv ok"
  build_nb_venv api1
  for a in api2 api3 api4 ctl; do copy_dir api1 "$a" $ROOT/venv & done; wait
  for a in api2 api3 api4 ctl; do copy_dir api1 "$a" $ROOT/nb-venv & done; wait

  say "Host B: notebook venv + configurable-http-proxy on nb0"
  build_nb_venv nb0
  r nb0 "set -e; [ -x $ROOT/npm/node_modules/.bin/configurable-http-proxy ] || npm install --silent --no-audit --no-fund --prefix $ROOT/npm configurable-http-proxy@4.6.3; echo chp ok"
  for a in nb1 nb2 nb3; do copy_dir nb0 "$a" $ROOT/nb-venv & done; wait
  for a in nb1 nb2 nb3; do copy_dir nb0 "$a" $ROOT/npm & done; wait

  say "edge + standby edge: nginx package"
  for a in edge ctl; do rsudo "$a" "command -v nginx >/dev/null || (apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq nginx-core >/dev/null); command -v nginx; pkill -f '[n]ginx: master process /usr/sbin/nginx' || true"; done

  say "control node: PostgreSQL client tools for backups / readiness checks"
  rsudo ctl "command -v pg_dump || (apt-get install -y -qq postgresql-client-16 >/dev/null); pg_dump --version"
}

# --------------------------------------------------------------------------- #
cmd_postgres() {
  local pip; pip=$(ip_of pg1)
  for a in pg1 pg2; do
    r "$a" "cat > /tmp/opencs.conf" < "$BUILD/$a/opencs.conf"
    r "$a" "cat > /tmp/pg_hba.opencs" < "$BUILD/$a/pg_hba.opencs"
    # Watchdog may start (never promote) PostgreSQL without a password.
    rsudo "$a" "install -m 0644 -o postgres -g postgres /tmp/opencs.conf /etc/postgresql/16/main/conf.d/opencs.conf
      h=/etc/postgresql/16/main/pg_hba.conf; sed -i '/# BEGIN opencs/,/# END opencs/d' \$h
      { echo '# BEGIN opencs'; cat /tmp/pg_hba.opencs; echo '# END opencs'; } >> \$h; rm -f /tmp/opencs.conf /tmp/pg_hba.opencs
      echo 'student ALL=(postgres) NOPASSWD: /usr/bin/pg_ctlcluster 16 main start' > /etc/sudoers.d/opencs-pg; chmod 440 /etc/sudoers.d/opencs-pg; visudo -cq
      echo auto > /etc/postgresql/16/main/start.conf; echo configured"
  done

  say "primary (pg1): restart with new config, roles, fresh opencs database"
  local dbpw replpw; dbpw=$(grep ^DB_PASSWORD= "$HERE/secrets/cluster.env" | cut -d= -f2); replpw=$(grep ^REPL_PASSWORD= "$HERE/secrets/cluster.env" | cut -d= -f2)
  rsudo pg1 "pg_ctlcluster 16 main restart && sleep 2 && sudo -u postgres psql -v ON_ERROR_STOP=1 -q <<SQL
DO \\\$\\\$BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='opencs') THEN CREATE ROLE opencs LOGIN; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='replicator') THEN CREATE ROLE replicator LOGIN REPLICATION; END IF;
END\\\$\\\$;
ALTER ROLE opencs PASSWORD '$dbpw';
ALTER ROLE replicator PASSWORD '$replpw';
-- A previous deployment left synchronous_standby_names='db2' in
-- postgresql.auto.conf: every commit then waits forever for a standby that does
-- not exist. Replication here is deliberately async.
ALTER SYSTEM RESET synchronous_standby_names;
SELECT pg_reload_conf();
SQL
    if [ '${FRESH_DB:-1}' = 1 ]; then sudo -u postgres dropdb --if-exists opencs; fi
    sudo -u postgres psql -Atqc \"select 1 from pg_database where datname='opencs'\" | grep -q 1 || sudo -u postgres createdb -O opencs opencs
    sudo -u postgres psql -q -d opencs -c 'CREATE EXTENSION IF NOT EXISTS pg_stat_statements'
    sudo -u postgres psql -Atqc \"select 1 from pg_replication_slots where slot_name='standby1'\" | grep -q 1 || sudo -u postgres psql -qc \"select pg_create_physical_replication_slot('standby1')\" >/dev/null
    echo primary ready"

  say "standby (pg2): re-clone from primary"
  rsudo pg2 "set -e; pg_ctlcluster 16 main stop || true
    d=/var/lib/postgresql/16/main; rm -rf \$d.old; mv \$d \$d.old; install -d -o postgres -g postgres -m 700 \$d
    sudo -u postgres env PGPASSWORD='$replpw' pg_basebackup -h $pip -U replicator -D \$d -R -S standby1 -X stream -c fast
    pg_ctlcluster 16 main start && rm -rf \$d.old && echo standby streaming"
  sleep 3
  rsudo pg1 "sudo -u postgres psql -Atc \"select client_addr, state, sync_state, replay_lag from pg_stat_replication\""
}

cmd_migrate() {
  r ctl "cd $ROOT/current/backend && set -a && . $ROOT/env/worker.env && set +a && $ROOT/venv/bin/alembic upgrade head && cd .. && OPENCE_DATASET_SERVING_DIR=$ROOT/datasets/serving $ROOT/venv/bin/python scripts/seed.py | tail -5"
}

# --------------------------------------------------------------------------- #
MON=$(python3 -c "import json;print(json.load(open('$INV'))['tuning'].get('monitoring_alias','pg2'))")
svc_for() {
  local base
  case "$(q "print(next(n['role'] for n in inv['nodes'] if n['alias']=='$1'))")" in
    api) base=api;; hub) base=hub;; edge) base=edge;; control) base="worker edge watchdog";; *) base="";;
  esac
  # Every node runs the metrics agent; the monitoring node also runs the stack.
  if [[ "$1" == "$MON" ]]; then base="$base vm vmalert grafana"; fi
  echo "$base agent"
}

_start() { local s; for s in $(svc_for "$1"); do r "$1" "bash $ROOT/bin/opencs.sh ${ACTION:-start} $s"; done; }

cmd_start() {
  local which=${1:-all}
  if [[ "$which" == all ]]; then
    say "hubs + APIs (parallel), then control, then edge"
    each "$(aliases hub) $(aliases api)" _start
    ensure_cluster_key
    _start ctl
    _start edge
  else
    each "$(aliases "$which")" _start
  fi
}

# The watchdog on ctl restarts services over SSH with its own key, authorised
# on every node. Restricting it further (command= in authorized_keys) is
# possible but would also block the off-host backup copy.
ensure_cluster_key() {
  local pub
  pub=$(r ctl 'k=~/.ssh/opencs_cluster_ed25519; [ -f $k ] || ssh-keygen -q -t ed25519 -N "" -C opencs-watchdog -f $k; cat $k.pub')
  _auth() { r "$1" "umask 077; mkdir -p ~/.ssh; grep -qxF '$pub' ~/.ssh/authorized_keys 2>/dev/null || echo '$pub' >> ~/.ssh/authorized_keys"; }
  each "$(aliases all)" _auth
}

cmd_stop() { ACTION=stop each "$(aliases "${1:?alias|role|all}")" _start; }

cmd_status() {
  _st() { r "$1" "printf '%-8s mem=%4sMiB ' \$(hostname) \$(( \$(cat /sys/fs/cgroup/memory.current)/1048576 )); bash $ROOT/bin/opencs.sh list 2>/dev/null | awk '{printf \"%s=%s \", \$3, \$4}'; pgrep -x postgres >/dev/null && printf 'postgres=running'; echo"; }
  each "$(aliases all)" _st | sort
  r ctl "cat $ROOT/run/cluster-status 2>/dev/null" || true
}

cmd_verify() {
  local o; o=$(q "print(inv['public_origin'])")
  say "edge $o"
  curl -fsS -o /dev/null -w "  SPA        %{http_code} %{time_total}s\n" "$o/"
  curl -fsS -o /dev/null -w "  /health    %{http_code} %{time_total}s\n" "$o/health"
  local js; js=$(curl -fsS "$o/" | grep -o '/assets/[^"]*\.js' | head -1)
  curl -fsS -o /dev/null -H 'Accept-Encoding: gzip' -w "  asset(gz)  %{http_code} %{size_download}B %{time_total}s\n" "$o$js"
  for i in 0 1 2 3; do curl -fsS -o /dev/null -w "  /nb/$i      %{http_code} %{time_total}s\n" "$o/nb/$i/hub/health"; done
  say "API spread over 40 requests (upstream per request from the edge log)"
  # /health is not access-logged at the edge; an unauthenticated /me (401) is.
  for _ in $(seq 40); do curl -sS -o /dev/null "$o/api/v1/me"; done
  r edge "sleep 6; tail -n 300 $ROOT/logs/edge.access.log | grep 'GET /api/v1/me ' | tail -40 | grep -o 'up=[0-9.:]*' | sort | uniq -c"
  say "login + authenticated call"
  local jar; jar=$(mktemp)
  curl -fsS -c "$jar" -H 'Content-Type: application/json' -d '{"email":"student@opencs.local","password":"opencs-demo"}' -o /dev/null -w "  login      %{http_code} %{time_total}s\n" "$o/api/v1/auth/login"
  curl -fsS -b "$jar" -o /dev/null -w "  /me        %{http_code} %{time_total}s\n" "$o/api/v1/me"
  rm -f "$jar"
}

cmd_rollout() {
  cmd_release
  say "rolling restart: one API at a time, edge keeps serving from the others"
  local a; for a in $(aliases api); do
    r "$a" "bash $ROOT/bin/opencs.sh restart api && for i in \$(seq 60); do curl -fsS -o /dev/null http://127.0.0.1:8000/health && { for w in 1 2 3; do curl -s -o /dev/null http://127.0.0.1:8000/api/v1/me; done; echo healthy+warm; exit 0; }; sleep 1; done; exit 1"
  done
  r ctl "bash $ROOT/bin/opencs.sh restart worker"
  each "$(aliases hub)" _start   # idempotent: a running Hub keeps its users
  for a in edge ctl; do r "$a" "nginx -p $ROOT -c $ROOT/env/edge.conf -t -q && kill -HUP \$(cat $ROOT/run/edge.nginx.pid) && echo reloaded"; done
}

cmd_rollback() {
  _rb() { r "$1" "cd $ROOT && [ -L previous ] && p=\$(readlink previous) && ln -sfn \$(readlink current) previous && ln -sfn \$p current && echo current=\$p"; }
  each "$(aliases all)" _rb
  ACTION=restart cmd_start all
}

# --------------------------------------------------------------------------- #
# Observability (ADR-011): VictoriaMetrics + vmalert + Grafana on the monitoring
# node, an agent on every node. Binaries are fetched and checksum-verified on
# the operator machine (the nodes cannot reach dl.grafana.com).
VM_VERSION=v1.102.1
GRAFANA_VERSION=11.2.0
GRAFANA_SHA256=a7e717b78c11e37b147994fc04655da5f434280e1f01ceb84e8f38ca7fdef050

fetch_monitoring_binaries() {
  local dir="$BUILD/monitoring-bin"; mkdir -p "$dir"
  local base="https://github.com/VictoriaMetrics/VictoriaMetrics/releases/download/$VM_VERSION"
  for pkg in victoria-metrics vmutils; do
    local f="$pkg-linux-amd64-$VM_VERSION.tar.gz"
    [[ -f "$dir/$f" ]] || curl -fsSL --retry 3 -o "$dir/$f" "$base/$f"
    curl -fsSL --retry 3 "$base/${pkg}-linux-amd64-${VM_VERSION}_checksums.txt" | grep " $f\$" | (cd "$dir" && sha256sum -c -) >/dev/null \
      || die "checksum mismatch for $f"
  done
  local g="grafana-$GRAFANA_VERSION.linux-amd64.tar.gz"
  [[ -f "$dir/$g" ]] || curl -fsSL --retry 3 -o "$dir/$g" "https://dl.grafana.com/oss/release/$g"
  echo "$GRAFANA_SHA256  $g" | (cd "$dir" && sha256sum -c -) >/dev/null || die "checksum mismatch for $g"
  echo "$dir"
}

cmd_monitoring() {
  local dir; dir=$(fetch_monitoring_binaries)
  say "monitoring stack on $MON"
  r "$MON" "mkdir -p $ROOT/monitoring $ROOT/data/vm $ROOT/data/grafana $ROOT/logs/grafana"
  r "$MON" "cd $ROOT/monitoring && [ -x victoria-metrics-prod ] || tar xzf - victoria-metrics-prod" < "$dir/victoria-metrics-linux-amd64-$VM_VERSION.tar.gz"
  r "$MON" "cd $ROOT/monitoring && [ -x vmalert-prod ] || tar xzf - vmalert-prod" < "$dir/vmutils-linux-amd64-$VM_VERSION.tar.gz"
  r "$MON" "cd $ROOT/monitoring && [ -x grafana/bin/grafana ] || { tar xzf - && rm -rf grafana && mv grafana-v$GRAFANA_VERSION grafana; }" < "$dir/grafana-$GRAFANA_VERSION.linux-amd64.tar.gz"
  r "$MON" "ls $ROOT/monitoring; $ROOT/monitoring/victoria-metrics-prod -version"

  say "read-only PostgreSQL role for the node agents"
  local monpw; monpw=$(grep ^PG_MONITOR_PASSWORD= "$HERE/secrets/cluster.env" | cut -d= -f2)
  rsudo pg1 "sudo -u postgres psql -v ON_ERROR_STOP=1 -q <<SQL
DO \\\$\\\$BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='opencs_monitor') THEN CREATE ROLE opencs_monitor LOGIN; END IF;
END\\\$\\\$;
ALTER ROLE opencs_monitor PASSWORD '$monpw';
GRANT pg_monitor TO opencs_monitor;
GRANT CONNECT ON DATABASE opencs TO opencs_monitor;
SQL
sudo -u postgres psql -q -d opencs -c 'GRANT SELECT ON jobs, notifications TO opencs_monitor'"
  for a in pg1 pg2; do
    r "$a" "cat > /tmp/pg_hba.opencs" < "$BUILD/$a/pg_hba.opencs"
    rsudo "$a" "h=/etc/postgresql/16/main/pg_hba.conf; sed -i '/# BEGIN opencs/,/# END opencs/d' \$h
      { echo '# BEGIN opencs'; cat /tmp/pg_hba.opencs; echo '# END opencs'; } >> \$h; rm -f /tmp/pg_hba.opencs
      sudo -u postgres psql -qc 'select pg_reload_conf()' >/dev/null && echo hba reloaded"
  done

  say "agents everywhere, monitoring services, edge reload"
  each "$(aliases all)" _start
  for a in edge ctl; do r "$a" "nginx -p $ROOT -c $ROOT/env/edge.conf -t -q && kill -HUP \$(cat $ROOT/run/edge.nginx.pid) && echo reloaded"; done
}

# Config-only change: re-render, ship env + node scripts, restart named
# services (default: agents + monitoring).  deploy.sh config [service ...]
cmd_config() {
  cmd_render
  _cfg() {
    r "$1" "mkdir -p $ROOT/env $ROOT/bin && umask 077 && tar -C $ROOT/env -xf -" < <(tar -C "$BUILD/$1" -cf - .)
    r "$1" "cat > $ROOT/bin/opencs.sh && chmod +x $ROOT/bin/opencs.sh" < "$HERE/node/opencs.sh"
    r "$1" "cat > $ROOT/bin/agent.py" < "$HERE/node/agent.py"
    r "$1" "cat > $ROOT/bin/watchdog.sh" < "$HERE/node/watchdog.sh"
  }
  each "$(aliases all)" _cfg
  local services=("$@"); [[ ${#services[@]} -gt 0 ]] || services=(agent vm vmalert)
  _restart() {
    local s running; running=$(svc_for "$1")
    for s in "${services[@]}"; do [[ " $running " == *" $s "* ]] && r "$1" "bash $ROOT/bin/opencs.sh restart $s" | tail -1; done
  }
  each "$(aliases all)" _restart
}

# Search logs across the cluster:  deploy.sh logs <alias|role|all> [service] [grep-pattern]
cmd_logs() {
  local which=${1:-all} svc=${2:-} pattern=${3:-}
  _log() {
    r "$1" "cd $ROOT/logs 2>/dev/null || exit 0; files=\$(ls ${svc:+$svc.log} ${svc:-*.log} 2>/dev/null); [ -n \"\$files\" ] || exit 0
            if [ -n '$pattern' ]; then grep -H -E '$pattern' \$files | tail -n ${LINES_N:-40}; else tail -n ${LINES_N:-20} \$files; fi"
  }
  each "$(aliases "$which")" _log
}

cmd="${1:-}"; shift || true
case "$cmd" in
  render|preflight|cleanup|release|runtimes|postgres|migrate|start|stop|status|verify|rollout|rollback|monitoring|logs|config) "cmd_$cmd" "$@" ;;
  *) sed -n '2,25p' "$0"; exit 64 ;;
esac
