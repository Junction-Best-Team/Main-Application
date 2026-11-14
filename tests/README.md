# Tests and CI procedure

One command runs the checks locally. GitHub Actions (`.github/workflows/ci.yml`) runs them as parallel jobs on every PR into `develop` or `main`; the `CI gate` job waits for all of them. For a plain-language explanation of each test, see [TEST-GUIDE.md](TEST-GUIDE.md).

```sh
tests/ci.sh                          # lint + pytest + tool sweep, hermetic (no API key needed)
tests/ci.sh --skip-unit              # only the sweep (the CI "API sweep" job)
tests/ci.sh --live                   # sweep against the real Valio API (needs VALIO_AIMO_API_KEY)
SWEEP_ARGS=--strict tests/ci.sh      # a skipped check counts as a failure
```

Needs Docker (PostgreSQL + pgvector, started by the script), `uv`, and, for the frontend tests, Node 24 (`npm ci --prefix frontend`, then `npm run test:coverage --prefix frontend`; they are separate from this script). The script stops at the first failing setup step but always reports sweep and browser results together.

## Where each check runs

| Layer | What it is | Needs | CI job in `ci.yml` | Local only |
| --- | --- | --- | --- | :-: |
| `ruff check src tests scripts` | Lint | nothing | Python lint and tests | |
| `pytest` (`tests/test_*.py`) | Unit and integration tests against real PostgreSQL, fixture upstream and embeddings | pgvector DB | Python lint and tests | |
| Frontend `npm run build` | TypeScript check and production build | Node | Frontend types and build | |
| `tests/sweep/run_sweep.py` | Black-box sweep of the buyer-facing API (sign-in, CSRF/Origin, conversations, purchases, approvals) against a running server; no LLM | server + DB | API sweep | `--live` too |
| `npm run test:coverage` (Vitest, jsdom) | Eight component tests of the chat UI against canned API responses, with a frontend coverage floor | Node | Frontend types and build | |
| `tests/test_frontend_fixtures.py` | The canned responses are valid responses of the real API (server models) | nothing extra | Python lint and tests | |
| `scripts/demo.py` | Demo helper rewritten for the chat product in PR #15 (not re-run here) | running server | | yes |
| `scripts/restart_smoke.py` | Real container restart between approval and commit | Docker image | | yes |
| `scripts/verify_catalog.py`, `scripts/evaluate_search.py` | Seven golden catalog cases; 30-case retrieval evaluation | full catalog | | yes |
| `tests/ci.sh --live` | Sweep with real Valio price and stock | API key | | yes |
| `tests/coverage_report.py` | Combines pytest and sweep coverage; fails below `fail_under` | coverage data | Coverage (95% minimum) | |
| `infra/` Terraform checks (`terraform.yml`) | Format, `validate`, mocked-provider `terraform test` plans, ingress Helm render and Python unit tests for the cloud and Kubernetes modules; no cloud token | Terraform | Terraform | |

Not covered by any CI: the Docker image build, Kubernetes manifests, the live Valio API (key not stored in GitHub), and search quality (the evaluation needs the 84 MB catalog and real embeddings).

## pytest (`tests/test_*.py`)

Fixture upstream and fixture embeddings only; never the live API. Descriptions are taken from the test names.

| File | Covers |
| --- | --- |
| `test_evidence.py` | Supplier-response validation, unit conversion only through known factors, packaging levels and name conflicts, missing claims are unknown (not "no"), the gross spend boundary, missing currency, malformed upstream, unchanged embeddings reused and a failed import keeping the old index, dietary filters on both search paths |
| `test_workflow.py` | Autonomous purchase and idempotency after a restart, independent inbox approval and agent resume, reduced agent authority creating a new revision, the four outcomes and hard requirements, denied before unknown, changed price and stock invalidating approval, rejection, expiry and revocation, policy version changes, approver amount and exception scope, concurrent same-key and different-key commits, competing decisions, deposit totals and overbuy, invalid policy never defaulting to permission |
| `test_http.py` | Login, inbox, CSRF and logout, removed agent/MCP routes return JSON 404, cross-account isolation, input validation and error shape, login rate limit and wrong origin, `/docs` nonce and scoped CSP, the shared purchasing operations and both commit outcomes, historical approval linking to current terms |
| `test_upstream_client.py` | The live Valio client over a mock transport (headers and body, retries on 429/5xx/transport errors, retries exhausted, no key leak, redirects not followed, malformed JSON, missing credentials) and 25 supplier-reply defects through `validate_lookup`; price validity caps proposal expiry |
| `test_ingest.py` | Catalog import from a synthetic snapshot (deleted products skipped, embeddings reused, refused snapshots leave the active catalog unchanged) and the catalog download (key required, HTTPS redirect without the key, HTTP errors leave no file) |
| `test_cli.py` | `configure` (mode 0600, no overwrite, secrets not printed), idempotent `migrate`, `seed` credential checks, every `main()` subcommand |
| `test_purchases.py`, `test_catalog.py` | Proposal snapshot failures (past date, unknown product, variable weight, missing price, short stock, seven deposit failures) and catalog normalisation, requirement reasons and quantity rounding |
| `test_workflow_races.py` | Changes injected between a commit's lookup and its locked re-check (policy, revision, expiry), duplicate commits, agents deciding, closed approvals, authority drift |
| `test_edges.py` | Policy branches, session/CSRF edge cases, internal-agent resolution, product scope, `/health/ready` states, static frontend serving, search index and model errors |
| `test_agent.py`, `test_agent_integration.py`, `test_conversations.py`, `test_hardening.py`, `test_retries.py` | Teammates' tests (PRs #4 and #15): the internal assistant with a scripted provider, persistent conversations and confirmation, security and performance hardening, supplier retry rules |
| `test_upstream_mode.py` | `UPSTREAM_MODE=auto` uses live with a key and labelled fixtures without; `fixture` ignores a key; `live` without a key fails closed |

## API sweep (`tests/sweep/run_sweep.py`)

Uses only the public HTTP surface, like the browser. It needs no LLM provider and no Valio key (the server runs with `LLM_API_KEY` empty). The purchasing tools run only inside an LLM-driven chat turn, so they are covered by the scripted-provider pytest suites, not by the sweep. The mode actually used is read from the server and printed (`upstream commercial data in this run: FIXTURE|LIVE`).

| Check | Verifies |
| --- | --- |
| health/ready | Server and index ready; reports `upstream_mode` |
| sign-in required | Session, conversations, purchases, approvals and a purchase page refuse an anonymous caller |
| login controls | Wrong password and a foreign Origin refused; correct login opens a session |
| CSRF and Origin enforced | Creating a conversation is refused without a token, with a wrong token and from a foreign Origin, and creates nothing |
| create conversation (+ retry) | Same idempotency key returns the same conversation; reuse for a different body is refused |
| list and get conversation | Listed, fetched, empty; unknown id is 404 |
| message without provider | A message needs CSRF; with no LLM configured it fails with a 503 `LLM` error and stores no assistant reply |
| purchases and approvals | Lists open; unknown proposal and approval are 404 |
| confirm and decide controls | Confirming a purchase and deciding an approval need CSRF; unknown ids are 404 |
| logout | The old cookie is refused afterwards |

A check that cannot run is reported as `SKIP` with its reason, never as a pass (for example, the message check skips if a provider is configured on that server). Live price and stock are no longer exercised by the sweep; `tests/ci.sh --live` now only runs the sweep with `UPSTREAM_MODE=live`.

## Frontend component tests (`frontend/tests/chat.test.tsx`)

Vitest with React Testing Library in jsdom: the real `App` is rendered and `fetch` answers every API call from `frontend/tests/fixtures/api.json` (an unmocked call fails the test). No browser, no server, no database; the whole file runs in about a second. They replaced the Playwright tests: the real-server ones duplicated pytest (removed `/mcp` and `/api/agent/*` routes, historical approval), and the mocked ones are ported. One thing is deliberately no longer checked: the 390 px no-sideways-scroll layout assertion, which needs a real layout engine.

| Test | Verifies |
| --- | --- |
| Starts a conversation from the root | Example prompt and Send create the conversation and open its URL; the plan, the basket link and the "Messages never authorize a purchase." notice show; the CSRF token is sent; the input clears; a remount shows the same conversation without a second send |
| Lost response reuses the key | After a 503 the typed text survives a remount and the retry sends the same idempotency key |
| Restores an unfinished turn | A server-persisted `retry_message` fills the input and Send posts exactly that text and key |
| Deep link and explicit confirmation | A purchase URL survives sign-in; nothing is sent until "Confirm this purchase" is clicked; the request carries the proposal, revision 1, the CSRF token and a `customer-confirm-…` key; the button disappears afterwards |
| Changed terms | A "revised" answer shows "Terms changed" and revision 2; confirming again sends revision 2 |
| Legacy approval link and closed states | A superseded approval keeps revision 1 and links to the current one; superseded, rejected and expired purchases show no confirm button |
| Stale revision | A revision older than the current one shows no confirm button even if it could be decided |
| History | `/approvals` redirects to the purchase list; a completed purchase is listed; a failed refresh shows an actionable alert |

`test_frontend_fixtures.py` keeps these tests honest: it validates every fixture against `SessionResponse`, `ProposalResponse`, `ConversationResponse`, `ConversationList`, `InboxResponse` and `CommitResponse`. It already caught one drift on first run (the old mocked confirm answer was not a valid commit response). Mutation checks: ignoring the saved idempotency key, ignoring the persisted retry key, offering confirmation in terminal states, offering it for a stale revision, and sending a wrong revision each failed at least one test (the stale-revision mutation first survived, which is why that test exists).

## Feature coverage

Mapped by test name; a feature with only a local check is not protected by CI.

| Feature (from `docs/brief.md`) | Automated in CI | Local only |
| --- | --- | --- |
| Structured search with dietary filters | pytest filters on both paths; `test_agent*.py` | `evaluate_search.py` quality |
| Product detail, unit and quantity normalisation | `test_evidence.py`; `test_http.py` | `verify_catalog.py` golden cases |
| Live price and availability | fixture only | `tests/ci.sh --live` |
| Proposal maths, rounding, deposits | `test_workflow.py`, `test_evidence.py` | |
| Four policy outcomes, hard limits | pytest | |
| Human approval, rejection, exact revision | pytest (`test_workflow.py`, `test_conversations.py`); sweep CSRF checks on confirm and decide; Vitest component tests | |
| Changed price, stock or authority | pytest | |
| Idempotent commit, concurrency, restart | pytest | `restart_smoke.py` (container) |
| Buyer sessions, CSRF, isolation, rate limit | `test_http.py`; sweep sign-in, login and CSRF checks | |
| Chat and purchase HTTP endpoints, typed responses | `test_http.py`, `test_conversations.py`; sweep conversation checks | |
| Chat UI | Vitest component tests; frontend build | |
| Key-or-fixture fallback | `test_upstream_mode.py`; the sweep prints the mode | |
| Catalog ingestion, embeddings reuse | `test_evidence.py` | full 17,546-product import |
| Docker image, Kubernetes | | `restart_smoke.py` only |

Known gaps: nothing exercises the purchasing tools over HTTP end to end (they sit behind a paid LLM), the approval flow is not exercised against live stock, the frontend is covered by component tests (82.6% of lines) but there is no real-browser test, so layout, real cookies and real routing are unchecked.

## Modes, and what a pass means

- **Hermetic (default).** Own database `aimo_ci`, authored fixture catalog, fixture price and stock. Proves the code works; says nothing about Valio's real data.
- **Live (`--live`).** `UPSTREAM_MODE=live`, so it fails closed without `VALIO_AIMO_API_KEY`. The key exists and teammates have it. Run with your `.env` database and the full catalog ingested. Live stock for the default fixture product `464306` is an unknown-quantity sentinel (F-MVP-007); the buyer-facing sweep does not depend on it.
- The buyer password and API key are never printed or logged.

## Coverage

Python line and branch coverage of `src/aimo`, measured on the pytest suite and, separately, on the real uvicorn server (plus the `migrate`/`seed`/`fixture-catalog` steps) that the black-box sweep drives, then combined:

```sh
CI_COVERAGE=1 tests/ci.sh                  # data goes to .coverage/ (gitignored); behaviour is unchanged without the variable
uv run python tests/coverage_report.py     # pytest only / sweep only / combined, per file, lines only the sweep reaches, HTML + XML in .coverage/
```

- **Gate: 95%.** `fail_under` in `pyproject.toml` (`[tool.coverage.report]`) is applied to the combined total by `coverage_report.py` (exit 1 below it). It is the only place to change it, and it is required: the CI job "Coverage (95% minimum)" is part of the `CI gate`. Do not run bare `pytest --cov` expecting a pass: pytest alone is lower than the combined total, so add `--cov-fail-under=0` when you only want the table.
- **CI.** The `Python lint and tests`, and `API sweep` jobs each upload their coverage data; the `Coverage` job downloads and combines them, prints the table in the log and the job summary, uploads the HTML/XML report and fails below the gate.
- **Excluded.** Only `if __name__ == "__main__":` blocks. `tests/`, `scripts/`, `frontend/` and the live Valio path (not reachable without a key) are not measured.
- **Frontend: measured separately, with a floor.** `npm run test:coverage --prefix frontend` measures `src/main.tsx` (v8, branches included) and fails below `thresholds` in `frontend/vitest.config.ts`: 80% lines, 75% statements, 72% functions, 68% branches. Measured 2026-11-14: 82.6% lines, 78.5% statements, 76.1% functions, 71.8% branches. That is below the 95% Python gate; it is a floor to ratchet up, not a claim of 95%.
- **Measured 2026-11-14** (fixture mode, on the merge with `develop`): combined 96.5% with 317 pytest tests, re-measured after merging `develop` (hardening and the chat cutover). `agent.py` and `api.py` (the streaming endpoint) are the lowest at 84%. The gate is 95%, so the margin is only about 1.5 points: adding untested code will trip it. The few unreached lines are listed by `tests/coverage_report.py`.

## Running pieces on their own

```sh
uv run pytest -q
uv run python tests/sweep/run_sweep.py --base-url http://localhost:8000   # against a running server
npm run test:coverage --prefix frontend                                   # frontend component tests with the coverage floor
```

The directory is `tests/` (not `Tests/`) on purpose: a second folder differing only in case would collide on macOS and Windows checkouts.
