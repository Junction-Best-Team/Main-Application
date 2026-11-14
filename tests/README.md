# Tests and CI procedure

One command runs the checks locally. GitHub Actions runs them on every PR into `develop` or `main`.

```sh
tests/ci.sh                          # lint + pytest + tool sweep, hermetic (no API key needed)
tests/ci.sh --browser                # ... plus frontend build and Playwright browser tests
tests/ci.sh --skip-unit --browser    # only sweep + browser (what the e2e workflow runs)
tests/ci.sh --live                   # sweep against the real Valio API (needs VALIO_AIMO_API_KEY)
SWEEP_ARGS=--strict tests/ci.sh      # a skipped check counts as a failure
```

Needs Docker (PostgreSQL + pgvector, started by the script), `uv`, and for `--browser` Node 24 and a one-time Chromium download. The script stops at the first failing setup step but always reports sweep and browser results together.

## Where each check runs

| Layer | What it is | Needs | Quick CI (`ci.yml`) | End-to-end CI (`e2e.yml`) | Local only |
| --- | --- | --- | :-: | :-: | :-: |
| `ruff check src tests scripts` | Lint | nothing | yes | | |
| `pytest` (`tests/test_*.py`) | Unit and integration tests against real PostgreSQL, fixture upstream and embeddings | pgvector DB | yes | | |
| Frontend `npm run build` | TypeScript check and production build | Node | yes | | |
| `tests/sweep/run_sweep.py` | Black-box sweep of the eight agent tools, MCP and the buyer controls, against a running server | server + DB | | yes | `--live` too |
| `frontend/e2e` (Playwright) | Six browser flows in real Chromium against the built UI | server + DB + Chromium | | yes | |
| `scripts/mcp_smoke.py` | Official MCP SDK over authenticated HTTP | running server | | | yes |
| `scripts/demo.py` | The demo story as a reference client | running server | | | yes |
| `scripts/restart_smoke.py` | Real container restart between approval and commit | Docker image | | | yes |
| `scripts/verify_catalog.py`, `scripts/evaluate_search.py` | Seven golden catalog cases; 30-case retrieval evaluation | full catalog | | | yes |
| `tests/ci.sh --live` | Sweep with real Valio price and stock | API key | | | yes |

Not covered by any CI: the Docker image build, Kubernetes manifests, the live Valio API (key not stored in GitHub), and search quality (the evaluation needs the 84 MB catalog and real embeddings).

## pytest (`tests/test_*.py`)

Fixture upstream and fixture embeddings only; never the live API. Descriptions are taken from the test names.

| File | Covers |
| --- | --- |
| `test_evidence.py` | Supplier-response validation, unit conversion only through known factors, packaging levels and name conflicts, missing claims are unknown (not "no"), the gross spend boundary, missing currency, malformed upstream, unchanged embeddings reused and a failed import keeping the old index, dietary filters on both search paths |
| `test_workflow.py` | Autonomous purchase and idempotency after a restart, independent inbox approval and agent resume, reduced agent authority creating a new revision, the four outcomes and hard requirements, denied before unknown, changed price and stock invalidating approval, rejection, expiry and revocation, policy version changes, approver amount and exception scope, concurrent same-key and different-key commits, competing decisions, deposit totals and overbuy, invalid policy never defaulting to permission |
| `test_http.py` | Login, inbox, CSRF and logout, cross-account and agent isolation, input validation and error shape, login rate limit and wrong origin, `/docs` nonce and scoped CSP, all eight typed operations and both commit outcomes, historical approval linking to current terms |
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

A check that cannot run is reported as `SKIP` with its reason, never as a pass. In live mode the approval and reject paths skip when real stock does not produce an approvable proposal (see F-MVP-006 in `docs/findings.md`); `SWEEP_ARGS="--product 463380"` uses a product with finite live stock.

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
- **Live (`--live`).** `UPSTREAM_MODE=live`, so it fails closed without `VALIO_AIMO_API_KEY`. The key exists and teammates have it. Run with your `.env` database and the full catalog ingested. Live stock for the default product `464306` is an unknown-quantity sentinel, so expect skips; `SWEEP_ARGS="--product 463380"` commits for real (F-MVP-006).
- The agent token, buyer password and API key are never printed or logged.

## Running pieces on their own

```sh
uv run pytest -q
uv run python tests/sweep/run_sweep.py --base-url http://localhost:8000   # against a running server
npm run test --prefix frontend                                            # browser tests; set UPSTREAM_MODE=fixture first
```

The directory is `tests/` (not `Tests/`) on purpose: a second folder differing only in case would collide on macOS and Windows checkouts.
