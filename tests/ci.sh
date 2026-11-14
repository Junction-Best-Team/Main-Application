#!/usr/bin/env bash
# CI procedure: lint, unit/integration tests, then a black-box sweep of the buyer-facing API.
#
#   tests/ci.sh           hermetic: own database (aimo_ci), fixture catalog, FIXTURE price/stock.
#                         Needs no API key and never touches your dev database.
#   tests/ci.sh --live    your .env database + full catalog, LIVE price/stock (fails closed
#                         without VALIO_AIMO_API_KEY; the key exists, ask a teammate).
#   --skip-unit           skip ruff + pytest (the quick pipeline already runs them).
#   --no-sweep            skip the API sweep.
#
#   CI_COVERAGE=1         (env var, any mode) measure code coverage of pytest and of the server the
#                         sweep drives into .coverage/; report with tests/coverage_report.py.
#
# Requires Docker (PostgreSQL + pgvector via compose) and uv. See tests/README.md.
set -euo pipefail
cd "$(dirname "$0")/.."

LIVE=0; UNIT=1; SWEEP=1
for arg in "$@"; do
  case "$arg" in
    --live) LIVE=1 ;;
    --skip-unit) UNIT=0 ;;
    --no-sweep) SWEEP=0 ;;
    *) echo "unknown option: $arg"; exit 2 ;;
  esac
done
PORT="${SWEEP_PORT:-8765}"
BASE="http://127.0.0.1:${PORT}"

step() { printf '\n== %s\n' "$1"; }

# --- coverage (CI_COVERAGE=1); behaviour is unchanged when unset -----------------------------------
PYTEST_COV=()
aimo_cli() { uv run aimo "$@"; }
if [ "${CI_COVERAGE:-0}" = 1 ]; then
  rm -rf .coverage
  PYTEST_COV=(--cov --cov-fail-under=0)  # the gate applies to the combined total, not pytest alone
  aimo_cli() { COVERAGE_FILE=.coverage/sweep uv run coverage run -m aimo.cli "$@"; }
fi
# ---------------------------------------------------------------------------------------------------

step "Database"
if [ -z "${CI:-}" ]; then docker compose up -d --wait db >/dev/null; fi

if [ "$UNIT" = 1 ]; then
  step "Lint (ruff)"
  uv run ruff check src tests scripts

  step "Tests (pytest, real PostgreSQL, isolated aimo_test)"
  COVERAGE_FILE=.coverage/pytest uv run pytest -q --disable-warnings ${PYTEST_COV[@]+"${PYTEST_COV[@]}"}
fi

if [ "$LIVE" = 0 ]; then
  step "Sweep setup: hermetic aimo_ci database, fixture catalog"
  export DATABASE_URL="${CI_DATABASE_URL:-postgresql://aimo:aimo@localhost:55432/aimo_ci}"
  uv run python - <<'PY'
import os
from urllib.parse import urlsplit, urlunsplit
import psycopg
from psycopg import sql
url = urlsplit(os.environ["DATABASE_URL"]); name = url.path.lstrip("/")
assert name.endswith("_ci"), "hermetic database name must end in _ci"
with psycopg.connect(urlunsplit(url._replace(path="/postgres")), autocommit=True) as c:
    if not c.execute("SELECT 1 FROM pg_database WHERE datname=%s", (name,)).fetchone():
        c.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
PY
  export EMBEDDING_BACKEND=fixture UPSTREAM_MODE=fixture VALIO_AIMO_API_KEY="" LLM_API_KEY=""
  export DEMO_BUYER_PASSWORD="ci-buyer-$(head -c 18 /dev/urandom | base64 | tr -dc 'A-Za-z0-9')"
  export APPROVAL_SESSION_SECRET="ci-session-$(head -c 36 /dev/urandom | base64 | tr -dc 'A-Za-z0-9')"
  aimo_cli migrate
  # The CI database is disposable, so rotate the seeded credentials on every run.
  uv run python - <<'PY'
from aimo.db import connection
with connection() as c:
    c.execute("TRUNCATE buyers, login_attempts, purged_proposals RESTART IDENTITY CASCADE")
PY
  aimo_cli seed
  aimo_cli fixture-catalog >/dev/null
else
  step "Sweep setup: live mode with your .env (full catalog must already be ingested)"
  export UPSTREAM_MODE=live
  step "Read-only live supplier price and availability check"
  uv run python tests/sweep/check_live.py
fi

export SECURE_COOKIES=false PUBLIC_BASE_URL="$BASE" DEMO_BASE_URL="$BASE" LLM_API_KEY=""

step "Start server on ${BASE}"
if [ "${CI_COVERAGE:-0}" = 1 ]; then
  COVERAGE_FILE=.coverage/sweep uv run coverage run -m uvicorn aimo.api:app --host 127.0.0.1 --port "$PORT" --log-level warning &
else
  uv run uvicorn aimo.api:app --host 127.0.0.1 --port "$PORT" --log-level warning &
fi
SERVER=$!
# Coverage data is written when the server exits, so wait for it (harmless without coverage).
trap 'kill $SERVER 2>/dev/null || true; wait $SERVER 2>/dev/null || true' EXIT
for _ in $(seq 1 90); do
  curl -fsS "${BASE}/health/live" >/dev/null 2>&1 && break
  kill -0 $SERVER 2>/dev/null || { echo "server exited early"; exit 1; }
  sleep 1
done

RESULT=0

if [ "$SWEEP" = 1 ]; then
  step "API sweep (sign-in, CSRF/Origin, conversations, purchases, approvals)"
  uv run python tests/sweep/run_sweep.py --base-url "$BASE" ${SWEEP_ARGS:-} || RESULT=1
fi

[ "$RESULT" = 0 ] && echo && echo "ALL CI STEPS PASSED" || { echo && echo "CI FAILED"; }
exit $RESULT
