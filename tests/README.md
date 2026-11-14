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
- **Live (`--live`).** Uses `UPSTREAM_MODE=live`, so it fails closed without `VALIO_AIMO_API_KEY`. The key exists and teammates have it. Real stock decides the outcome: a check that cannot run (for example nothing is committable against current live stock) is reported as `SKIP` with the reason, never as a pass. Pass `SWEEP_ARGS=--strict` to make a skip fail the run. Live stock for the default product `464306` is the unknown-quantity sentinel, so expect skips; `SWEEP_ARGS="--product 463380"` commits for real (see F-MVP-005 in `docs/findings.md`).
- Never printed or logged: the agent token, buyer password and API key.

## Running pieces on their own

```sh
uv run pytest -q
uv run python tests/sweep/run_sweep.py --base-url http://localhost:8000   # against a running server
```

The directory is `tests/` (not `Tests/`) on purpose: a second folder differing only in case would collide on macOS and Windows checkouts.
