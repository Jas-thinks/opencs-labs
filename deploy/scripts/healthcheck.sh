#!/usr/bin/env bash
# Verify the deployed stack from the load-balancer node.
#
# Usage (on stu87_sys1, or over SSH):
#   deploy/scripts/healthcheck.sh [base-url]
#
# Exits non-zero if any check fails, so it is usable as a CI post-deploy gate.
set -uo pipefail

BASE="${1:-http://127.0.0.1}"
FAILED=0

pass() { printf '  \033[32mPASS\033[0m %s\n' "$1"; }
fail() { printf '  \033[31mFAIL\033[0m %s\n' "$1"; FAILED=$((FAILED + 1)); }

check_status() {  # check_status <label> <expected> <url> [extra curl args...]
  local label="$1" expected="$2" url="$3"; shift 3
  local code
  code=$(curl -sS -m 10 -o /dev/null -w '%{http_code}' "$@" "$url" 2>/dev/null || echo 000)
  if [ "$code" = "$expected" ]; then pass "$label ($code)"; else fail "$label (got $code, want $expected)"; fi
}

echo "== Reverse proxy =="
check_status "proxy /healthz" 200 "$BASE/healthz"

echo "== Backends (through LB) =="
check_status "GET /health" 200 "$BASE/health"
check_status "GET /ready (DB)" 200 "$BASE/ready"
check_status "GET /api/v1/config" 200 "$BASE/api/v1/config"
check_status "GET /api/docs" 200 "$BASE/api/docs"

echo "== Frontend =="
check_status "GET / (SPA)" 200 "$BASE/"

echo "== Auth contract =="
check_status "unauthenticated /api/v1/me is 401" 401 "$BASE/api/v1/me"

echo "== Each backend directly (one worker each) =="
for ip in 172.17.0.61:8000 172.17.0.57:8000 172.17.0.39:8000; do
  check_status "backend $ip /health" 200 "http://$ip/health"
done

echo "== Database =="
if command -v pg_isready >/dev/null 2>&1; then
  if pg_isready -q -h 127.0.0.1 -p 5432 2>/dev/null; then pass "pg_isready"; else fail "pg_isready"; fi
fi

echo
if [ "$FAILED" -eq 0 ]; then
  echo "All checks passed."
else
  echo "$FAILED check(s) failed."
fi
exit "$FAILED"
