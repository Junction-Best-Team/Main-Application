# Tests and CI procedure

```sh
tests/ci.sh          # hermetic, no API key needed
tests/ci.sh --live   # real Valio price/stock, your .env database with the full catalog ingested
```

Needs Docker (PostgreSQL + pgvector, started by the script) and `uv`. The script stops at the first failing step.

| Step | What it proves |
| --- | --- |
| `ruff check` | Lint on `src`, `tests`, `scripts`. |
| `pytest` (`tests/test_*.py`) | Policy, workflow, evidence and HTTP behaviour against real PostgreSQL in an isolated `aimo_test` database. Always uses fixtures, never the live API. |
| `tests/sweep/run_sweep.py` | Black-box check of every agent tool through the public HTTP API and MCP, the way an external agent calls them. |

## What the sweep checks

| Tool / behaviour | Check |
| --- | --- |
| auth | No token and a wrong token are refused. |
| `get_purchase_policy` | Returns the policy, read-only to the agent. |
| `search_products` | Exact ID ranks first; a text query returns results; an unsupported filter is rejected. |
| `get_product` | Known ID returns the product; unknown ID is 404. |
| `check_price_and_availability` | Evidence for every requested ID, labelled `mode: live` or `fixture`. |
| `prepare_order` | One of the four outcomes with revision and `next_action`. |
| `get_proposal` | Same proposal and revision come back. |
| commit gate | A denied proposal cannot be committed. |
| `commit_order` | Commits (after buyer approval if required); a retry returns the identical receipt. |
| approval path | A split purchase is refused before the buyer decides, appears in the buyer inbox, and commits after approval. |
| `get_order` | Returns the receipt; unknown ID is 404. |
| MCP | All eight tools are discovered and callable. |

## Modes, and what a pass means

- **Hermetic (default).** Own database `aimo_ci`, authored fixture catalog, fixture price/stock. Proves the code works; says nothing about Valio's real data. The sweep prints `upstream commercial data in this run: FIXTURE`.
- **Live (`--live`).** Uses `UPSTREAM_MODE=live`, so it fails closed without `VALIO_AIMO_API_KEY`. The key exists and teammates have it. Real stock decides the outcome: a check that cannot run (for example nothing is committable against current live stock) is reported as `SKIP` with the reason, never as a pass. Pass `SWEEP_ARGS=--strict` to make a skip fail the run. Live stock for the default product `464306` is the unknown-quantity sentinel, so expect skips; `SWEEP_ARGS="--product 463380"` commits for real (see F-MVP-006 in `docs/findings.md`).
- Never printed or logged: the agent token, buyer password and API key.

## Coverage

Python line and branch coverage of `src/aimo`, measured on the pytest suite and, separately, on the real uvicorn server (plus the `migrate`/`seed`/`fixture-catalog` steps) that the black-box sweep drives, then combined:

```sh
CI_COVERAGE=1 tests/ci.sh                  # data goes to .coverage/ (gitignored); behaviour is unchanged without the variable
uv run python tests/coverage_report.py     # pytest only / sweep only / combined, per file, lines only the sweep reaches, HTML + XML in .coverage/
```

- **Gate.** `fail_under` in `pyproject.toml` (`[tool.coverage.report]`), currently **84**, is applied to the combined total by `coverage_report.py` (exit 1 below it). It is the only place to change it. Do not run bare `pytest --cov` expecting a pass: pytest alone is about 84.5%, so add `--cov-fail-under=0` (`tests/ci.sh` does).
- **CI.** `.github/workflows/coverage.yml` (pull requests, manual) runs the above with fixtures and no API key, prints the table in the log and the job summary, uploads the HTML/XML report and fails below the gate. The quick `ci.yml` is unchanged.
- **Excluded.** Only `if __name__ == "__main__":` blocks. `tests/`, `scripts/`, `frontend/` and the live Valio path (not reachable without a key) are not measured.
- **Frontend: not measured.** Browser tests need a `.env` and a coverage fixture in the specs; see F-MVP-007 for the options.
- **Measured 2026-11-14** (fixture mode): pytest only 84.5%, sweep only about 73%, combined about 87% (runs differ by about 0.5 point). Weakest: `ingest.py` 51%, `cli.py` 69%, `upstream.py` 81% (live HTTP branches), `purchases.py` and `catalog.py` about 83-86%.

## Running pieces on their own

```sh
uv run pytest -q
uv run python tests/sweep/run_sweep.py --base-url http://localhost:8000   # against a running server
```

The directory is `tests/` (not `Tests/`) on purpose: a second folder differing only in case would collide on macOS and Windows checkouts.
