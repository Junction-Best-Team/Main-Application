# Tests and CI procedure

One command runs the checks locally. GitHub Actions (`.github/workflows/ci.yml`) runs them as parallel jobs on every PR into `develop` or `main`; the `CI gate` job waits for all of them. For a plain-language explanation of each test, see [TEST-GUIDE.md](TEST-GUIDE.md).

```sh
tests/ci.sh                          # lint + pytest + tool sweep, hermetic (no API key needed)
tests/ci.sh --browser                # ... plus frontend build and Playwright browser tests
tests/ci.sh --skip-unit              # only the sweep (the CI "Tool sweep" job)
tests/ci.sh --skip-unit --no-sweep --browser   # only the browser tests (the CI "Browser tests" job)
tests/ci.sh --live                   # sweep against the real Valio API (needs VALIO_AIMO_API_KEY)
SWEEP_ARGS=--strict tests/ci.sh      # a skipped check counts as a failure
```

Needs Docker (PostgreSQL + pgvector, started by the script), `uv`, and for `--browser` Node 24 and a one-time Chromium download. The script stops at the first failing setup step but always reports sweep and browser results together.

## Where each check runs

| Layer | What it is | Needs | CI job in `ci.yml` | Local only |
| --- | --- | --- | --- | :-: |
| `ruff check src tests scripts` | Lint | nothing | Python lint and tests | |
| `pytest` (`tests/test_*.py`) | Unit and integration tests against real PostgreSQL, fixture upstream and embeddings | pgvector DB | Python lint and tests | |
| Frontend `npm run build` | TypeScript check and production build | Node | Frontend types and build | |
| `tests/sweep/run_sweep.py` | Black-box sweep of the eight agent tools, MCP and the buyer controls, against a running server | server + DB | Tool sweep | `--live` too |
| `frontend/e2e` (Playwright) | Six browser flows in real Chromium against the built UI | server + DB + Chromium | Browser tests | |
| `scripts/mcp_smoke.py` | Official MCP SDK over authenticated HTTP | running server | | yes |
| `scripts/demo.py` | The demo story as a reference client | running server | | yes |
| `scripts/restart_smoke.py` | Real container restart between approval and commit | Docker image | | yes |
| `scripts/verify_catalog.py`, `scripts/evaluate_search.py` | Seven golden catalog cases; 30-case retrieval evaluation | full catalog | | yes |
| `tests/ci.sh --live` | Sweep with real Valio price and stock | API key | | yes |
| `tests/coverage_report.py` | Combines pytest, sweep and browser coverage; fails below `fail_under` | coverage data | Coverage (95% minimum) | |
| `infra/` Terraform checks (`terraform.yml`) | Format, `validate`, mocked-provider `terraform test` plans, ingress Helm render and Python unit tests for the cloud and Kubernetes modules; no cloud token | Terraform | Terraform | |

Not covered by any CI: the Docker image build, Kubernetes manifests, the live Valio API (key not stored in GitHub), and search quality (the evaluation needs the 84 MB catalog and real embeddings).

## pytest (`tests/test_*.py`)

Fixture upstream and fixture embeddings only; never the live API. Descriptions are taken from the test names.

| File | Covers |
| --- | --- |
| `test_evidence.py` | Supplier-response validation, unit conversion only through known factors, packaging levels and name conflicts, missing claims are unknown (not "no"), the gross spend boundary, missing currency, malformed upstream, unchanged embeddings reused and a failed import keeping the old index, dietary filters on both search paths |
| `test_workflow.py` | Autonomous purchase and idempotency after a restart, independent inbox approval and agent resume, reduced agent authority creating a new revision, the four outcomes and hard requirements, denied before unknown, changed price and stock invalidating approval, rejection, expiry and revocation, policy version changes, approver amount and exception scope, concurrent same-key and different-key commits, competing decisions, deposit totals and overbuy, invalid policy never defaulting to permission |
| `test_http.py` | Login, inbox, CSRF and logout, cross-account and agent isolation, input validation and error shape, login rate limit and wrong origin, `/docs` nonce and scoped CSP, all eight typed operations and both commit outcomes, historical approval linking to current terms |
| `test_upstream_client.py` | The live Valio client over a mock transport (headers and body, retries on 429/5xx/transport errors, retries exhausted, no key leak, redirects not followed, malformed JSON, missing credentials) and 25 supplier-reply defects through `validate_lookup`; price validity caps proposal expiry |
| `test_ingest.py` | Catalog import from a synthetic snapshot (deleted products skipped, embeddings reused, refused snapshots leave the active catalog unchanged) and the catalog download (key required, HTTPS redirect without the key, HTTP errors leave no file) |
| `test_cli.py` | `configure` (mode 0600, no overwrite, secrets not printed), idempotent `migrate`, `seed` credential checks, every `main()` subcommand |
| `test_purchases.py`, `test_catalog.py` | Proposal snapshot failures (past date, unknown product, variable weight, missing price, short stock, seven deposit failures) and catalog normalisation, requirement reasons and quantity rounding |
| `test_workflow_races.py` | Changes injected between a commit's lookup and its locked re-check (policy, revision, expiry), duplicate commits, agents deciding, closed approvals, authority drift |
| `test_edges.py` | Policy branches, session/bearer/CSRF edge cases, MCP error results, `/health/ready` states, static frontend serving, search index and model errors |
| `test_upstream_mode.py` | `UPSTREAM_MODE=auto` uses live with a key and labelled fixtures without; `fixture` ignores a key; `live` without a key fails closed |

## Tool sweep (`tests/sweep/run_sweep.py`)

Uses only the public HTTP and MCP surface, like an external agent. The mode actually used is read from the server and printed (`upstream commercial data in this run: FIXTURE|LIVE`).

| Check | Verifies |
| --- | --- |
| health/ready | Server and index ready; reports `upstream_mode` |
| auth required | No token and a wrong token are refused |
| `get_purchase_policy` | Returns the seeded policy, read-only to the agent |
| `search_products` (3 checks) | Exact ID ranks first; a text query returns results; an unsupported filter is rejected |
| `get_product` | Known ID returns the product; unknown ID is 404 |
| `check_price_and_availability` | Evidence for every ID, labelled `mode: live` or `fixture` |
| `prepare_order` | One of the four outcomes, with revision and `next_action` |
| `get_proposal` | Same proposal and revision come back |
| commit gate | A denied proposal cannot be committed |
| `commit_order` | Commits (with buyer approval if required); a retry returns the identical receipt |
| buyer/agent separation | The agent token cannot use the inbox; a wrong password is refused; a buyer session cannot call the agent API |
| approval path | A split purchase is refused before the buyer decides, appears in the inbox, and commits after approval |
| reject path | A decision without a CSRF token is refused; rejection is recorded; commit stays refused |
| `get_order` | Returns the receipt; unknown ID is 404 |
| MCP | All eight tools discovered; `get_purchase_policy` callable |

A check that cannot run is reported as `SKIP` with its reason, never as a pass. In live mode the approval and reject paths skip when real stock does not produce an approvable proposal (see F-MVP-007 in `docs/findings.md`); `SWEEP_ARGS="--product 463380"` uses a product with finite live stock.

## Browser tests (`frontend/e2e/approval.spec.ts`)

Real Chromium against the built UI, fixture commerce only. Credentials come from the environment (CI) or the ignored `.env` (local).

1. Historical approval stays superseded and links to the committed terms.
2. Swagger `/docs` loads its operations with no CSP violations.
3. Independent buyer inbox, exact-revision approval, agent resume and retry.
4. Inbox error state, inaccessible routes and mobile login.
5. Competing buyer tabs keep the first decision and refresh the stale page.
6. Inbox polling pauses when the tab is hidden.

## Feature coverage

Mapped by test name; a feature with only a local check is not protected by CI.

| Feature (from `docs/brief.md`) | Automated in CI | Local only |
| --- | --- | --- |
| Structured search with dietary filters | pytest filters on both paths; sweep search checks | `evaluate_search.py` quality |
| Product detail, unit and quantity normalisation | `test_evidence.py`; sweep `get_product` | `verify_catalog.py` golden cases |
| Live price and availability | fixture only | `tests/ci.sh --live` |
| Proposal maths, rounding, deposits | `test_workflow.py`, `test_evidence.py` | |
| Four policy outcomes, hard limits | pytest; sweep `prepare_order` | |
| Human approval, rejection, exact revision | pytest; sweep approval and reject paths; browser flows 1, 3, 5 | |
| Changed price, stock or authority | pytest | |
| Idempotent commit, concurrency, restart | pytest | `restart_smoke.py` (container) |
| Buyer/agent separation, CSRF, isolation, rate limit | `test_http.py`; sweep separation and reject | |
| HTTP and MCP interfaces, typed responses | `test_http.py`; sweep MCP | `mcp_smoke.py` |
| Buyer UI | browser flows 1 to 6; frontend build | |
| Key-or-fixture fallback | `test_upstream_mode.py`; hermetic sweep | |
| Catalog ingestion, embeddings reuse | `test_evidence.py` | full 17,546-product import |
| Docker image, Kubernetes | | `restart_smoke.py` only |

Known gaps: the approval flow is not exercised against live stock; there are no frontend unit tests (only browser flows); the audit/decision history is checked only through the approval detail page; nothing yet measures what percentage of the code these checks execute.

## Modes, and what a pass means

- **Hermetic (default).** Own database `aimo_ci`, authored fixture catalog, fixture price and stock. Proves the code works; says nothing about Valio's real data.
- **Live (`--live`).** `UPSTREAM_MODE=live`, so it fails closed without `VALIO_AIMO_API_KEY`. The key exists and teammates have it. Run with your `.env` database and the full catalog ingested. Live stock for the default product `464306` is an unknown-quantity sentinel, so expect skips; `SWEEP_ARGS="--product 463380"` commits for real (F-MVP-007).
- The agent token, buyer password and API key are never printed or logged.

## Coverage

Python line and branch coverage of `src/aimo`, measured on the pytest suite and, separately, on the real uvicorn server (plus the `migrate`/`seed`/`fixture-catalog` steps) that the black-box sweep drives, then combined:

```sh
CI_COVERAGE=1 tests/ci.sh                  # data goes to .coverage/ (gitignored); behaviour is unchanged without the variable
uv run python tests/coverage_report.py     # pytest only / sweep only / combined, per file, lines only the sweep reaches, HTML + XML in .coverage/
```

- **Gate: 95%.** `fail_under` in `pyproject.toml` (`[tool.coverage.report]`) is applied to the combined total by `coverage_report.py` (exit 1 below it). It is the only place to change it, and it is required: the CI job "Coverage (95% minimum)" is part of the `CI gate`. Do not run bare `pytest --cov` expecting a pass: pytest alone is lower than the combined total, so add `--cov-fail-under=0` when you only want the table.
- **CI.** The `Python lint and tests`, `Tool sweep` and `Browser tests` jobs each upload their coverage data; the `Coverage` job downloads and combines them, prints the table in the log and the job summary, uploads the HTML/XML report and fails below the gate.
- **Excluded.** Only `if __name__ == "__main__":` blocks. `tests/`, `scripts/`, `frontend/` and the live Valio path (not reachable without a key) are not measured.
- **Frontend: not measured.** Browser tests need a `.env` and a coverage fixture in the specs; see F-MVP-008 for the options.
- **Measured 2026-11-14** (fixture mode, on the merge with `develop`): combined 99.4% with 282 pytest tests, re-measured after merging `develop` (Otto's hardening). The gate is 95%, so the margin is about 4 points. The few unreached lines are listed by `tests/coverage_report.py`.

## Running pieces on their own

```sh
uv run pytest -q
uv run python tests/sweep/run_sweep.py --base-url http://localhost:8000   # against a running server
npm run test --prefix frontend                                            # browser tests; set UPSTREAM_MODE=fixture first
```

The directory is `tests/` (not `Tests/`) on purpose: a second folder differing only in case would collide on macOS and Windows checkouts.
