#!/usr/bin/env bash
# CI procedure: lint, unit/integration tests, then a black-box sweep of every agent tool.
#
#   tests/ci.sh           hermetic: own database (aimo_ci), fixture catalog, FIXTURE price/stock.
#                         Needs no API key and never touches your dev database.
#   tests/ci.sh --live    your .env database + full catalog, LIVE price/stock (fails closed
#                         without VALIO_AIMO_API_KEY; the key exists, ask a teammate).
#   --browser             also build the frontend and run the Playwright browser tests
#                         (hermetic only: they need fixture commerce).
#   --skip-unit           skip ruff + pytest (the quick pipeline already runs them).
#
# Requires Docker (PostgreSQL + pgvector via compose) and uv. See tests/README.md.
set -euo pipefail
cd "$(dirname "$0")/.."

LIVE=0; BROWSER=0; UNIT=1
for arg in "$@"; do
  case "$arg" in
    --live) LIVE=1 ;;
    --browser) BROWSER=1 ;;
    --skip-unit) UNIT=0 ;;
    *) echo "unknown option: $arg"; exit 2 ;;
  esac
done
if [ "$LIVE" = 1 ] && [ "$BROWSER" = 1 ]; then
  echo "--browser needs fixture commerce; it cannot be combined with --live"; exit 2
fi
PORT="${SWEEP_PORT:-8765}"
BASE="http://127.0.0.1:${PORT}"

step() { printf '\n== %s\n' "$1"; }

step "Database"
if [ -z "${CI:-}" ]; then docker compose up -d --wait db >/dev/null; fi

if [ "$UNIT" = 1 ]; then
  step "Lint (ruff)"
  uv run ruff check src tests scripts

  step "Tests (pytest, real PostgreSQL, isolated aimo_test)"
  uv run pytest -q --disable-warnings
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
  export EMBEDDING_BACKEND=fixture UPSTREAM_MODE=fixture VALIO_AIMO_API_KEY=""
  export DEMO_AGENT_TOKEN="ci-agent-$(head -c 24 /dev/urandom | base64 | tr -dc 'A-Za-z0-9')"
  export DEMO_BUYER_PASSWORD="ci-buyer-$(head -c 18 /dev/urandom | base64 | tr -dc 'A-Za-z0-9')"
  export APPROVAL_SESSION_SECRET="ci-session-$(head -c 36 /dev/urandom | base64 | tr -dc 'A-Za-z0-9')"
  uv run aimo migrate
  # The CI database is disposable, so rotate the seeded credentials on every run.
  uv run python - <<'PY'
from aimo.db import connection
with connection() as c:
    c.execute("TRUNCATE buyers, login_attempts RESTART IDENTITY CASCADE")
PY
  uv run aimo seed
  uv run aimo fixture-catalog >/dev/null
else
  step "Sweep setup: live mode with your .env (full catalog must already be ingested)"
  export UPSTREAM_MODE=live
fi

if [ "$BROWSER" = 1 ]; then
  step "Frontend build and Playwright browser"
  npm ci --prefix frontend --no-audit --no-fund
  npm run build --prefix frontend
  npm exec --prefix frontend -- playwright install ${PLAYWRIGHT_DEPS:+--with-deps} chromium
fi

export SECURE_COOKIES=false PUBLIC_BASE_URL="$BASE" DEMO_BASE_URL="$BASE"

step "Start server on ${BASE}"
uv run uvicorn aimo.api:app --host 127.0.0.1 --port "$PORT" --log-level warning &
SERVER=$!
trap 'kill $SERVER 2>/dev/null || true' EXIT
for _ in $(seq 1 90); do
  curl -fsS "${BASE}/health/live" >/dev/null 2>&1 && break
  kill -0 $SERVER 2>/dev/null || { echo "server exited early"; exit 1; }
  sleep 1
done

RESULT=0

step "Tool sweep (all eight tools + MCP + controls)"
uv run python tests/sweep/run_sweep.py --base-url "$BASE" ${SWEEP_ARGS:-} || RESULT=1

if [ "$BROWSER" = 1 ]; then
  step "Browser tests (Playwright, real Chromium)"
  # The login limiter counts attempts per window; start the browser run with a clean counter.
  uv run python - <<'PY'
from aimo.db import connection
with connection() as c:
    c.execute("TRUNCATE login_attempts")
PY
  BASE_URL="$BASE" npm run test --prefix frontend || RESULT=1
fi

[ "$RESULT" = 0 ] && echo && echo "ALL CI STEPS PASSED" || { echo && echo "CI FAILED"; }
exit $RESULT
