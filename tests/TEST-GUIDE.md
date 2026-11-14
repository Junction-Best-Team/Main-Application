# What the tests really check

Written by reading the test code, not the test names. Branch `tests-ci-coverage`, rewritten after the chat-purchasing cutover (PR #15) removed the external agent API and MCP. If a claim says "unclear from the code", I could not settle it by reading.

> Scope of this guide: it explains line by line the tests this branch's author read and wrote (supplier checking, policy, workflow, upstream mode, the sweep, the coverage files). The tests teammates added in PRs #4 and #15 (`test_agent.py`, `test_agent_integration.py`, `test_conversations.py`, `test_hardening.py`, `test_retries.py`, `frontend/e2e/chat.spec.ts`) are summarised in section 2.8 **from their names and a skim, not read test by test**. The per-test tables in 2.1 to 2.6 were written against the earlier gateway; their scenarios still pass, and where Otto's later changes altered a test, the table says so.

## 1. How to read this

1. **Lint** (`ruff check src tests scripts`): style and obvious code errors. It checks no behaviour.
2. **pytest** (`tests/test_*.py`, 327 cases): calls the Python code directly against a real PostgreSQL test database, with invented ("fixture") prices, stock and search vectors. Fast, precise, no browser.
3. **Frontend build** (`npm run build`): TypeScript type check and bundle. Proves the UI compiles, nothing more.
4. **Sweep** (`tests/sweep/run_sweep.py`, 10 checks): talks to a running server over HTTP like the browser does (sign-in, CSRF/Origin, conversations, purchases, approvals). Proves the server, database and buyer-facing endpoints work together. It needs no LLM.
5. **UI tests: none in CI.** The UI is an old mockup; CI only type-checks and builds it. A teammate's Playwright specs (`frontend/e2e/`) exist but nothing runs them automatically.
6. **Local-only scripts** (`scripts/*.py`): need a running server, Docker, the full catalog or the real API key. Not run by CI. See section 6.
7. `tests/ci.sh` is only the runner. It starts the database and server, then runs lint, pytest and the sweep. CI sets `SWEEP_ARGS=--strict`, so a skipped sweep check fails the build there (`.github/workflows/ci.yml`, jobs "Tool sweep" and "Browser tests").
8. All pytest and sweep tests use **fixture** commerce: invented price and stock from `src/aimo/upstream.py::FixtureClient` and a 10-product catalog from `src/aimo/fixtures.py`. A pass says nothing about Valio's real data.
9. Fixture facts worth knowing: product `464306` costs 1.70 EUR gross per litre, has 600 in stock; `464398` has 400; `463380` has 698; everything else has 5000. The autonomous limit is 1500 EUR.
10. Search "vectors" are fake in tests (`EMBEDDING_BACKEND=fixture`), so meaning-based search quality is never measured by CI.

### Terms used below

- **Proposal / revision**: `prepare_order` stores a priced basket as a proposal, revision 1. If price, stock or rules change, a later `commit_order` creates revision 2 instead of ordering, and approvals of revision 1 no longer count.
- **Policy outcome**: one of `ready_to_commit` (agent may order alone), `approval_required` (a human buyer must approve), `denied` (forbidden, approval cannot fix it), `needs_resolution` (facts missing or conflicting; approval cannot fix it). Precedence: denied, then needs_resolution, then approval_required, then ready (`approval_policy.py::evaluate_purchase`).
- **Mock order**: the supplier has no order API. A "commit" only stores a receipt with status `accepted_mock`. Nothing is sent to Valio.
- **Buyer vs agent**: since PR #15 there is no external agent API (`/api/agent/*` and `/mcp` are gone and return JSON 404). The agent is the server's own internal assistant: it acts for the signed-in buyer through a privileged mapping (`internal_agents`), never through a bearer token. The buyer is the human (username and password, cookie session). Tests still call the `Service` functions with an `agent` identity, which is that internal identity.
- **CSRF**: a check that a browser POST came from our own page, not a hostile site. Here: an `X-CSRF-Token` header plus a matching `Origin` header.
- **Idempotency key**: a client-chosen string. Sending the same commit again with the same key must return the same receipt and not create a second order.
- **Gross**: price including tax and deposits.

## 2. pytest

Shared setup is `tests/conftest.py`. It forces a database whose name ends in `_test`, fixture upstream and fixture embeddings, clears buyers and login attempts before every test, and re-seeds the demo buyer, agent and policy v1. `request_data` is 10 L of `464306`, delivery in 2 days, lactose-free required. `mission` is 600 L of `464306` plus 400 L of `464398` as a substitute, which totals 1700.00 EUR and needs approval.

### 2.1 Supplier (upstream) response checking

`tests/test_evidence.py` unless noted. All use `validate_lookup`, the function that decides whether a price/stock reply can be trusted.

| Test | Scenario | Asserts | Catches |
| --- | --- | --- | --- |
| `test_supplier_regressions` (12 cases) | Take a good fixture reply and break one field: price missing; price expired (2020); tax rate that does not match the gross price; wrong customer id; duplicated product row; no delivery schedule; `logisticModel` not "Stock"; placeholder stock 9999999999; order cutoff in the past; unknown sales unit; sales block; availability date in 2099 | The expected reason code is among the reasons: `MISSING_PRICE`, `PRICE_OUTSIDE_VALIDITY`, `MISSING_PRICE`, `UPSTREAM_CONTEXT_MISMATCH`, `UPSTREAM_PRODUCT_MISMATCH`, `DELIVERY_UNRESOLVED`, `UNVERIFIED_STOCK` (twice), `CUTOFF_PASSED`, `AVAILABILITY_UNIT_UNKNOWN`, `SALES_BLOCK`, `DELIVERY_TOO_LATE` | A bad supplier reply being treated as a valid price or stock. Only checks the code appears, not that it is the only reason and not the final outcome |
| `test_sales_unit_mismatch_converts_only_known_factors` | Supplier reports stock of 2 in unit `KI` (case) while the product sells in `ST` (piece); `KI` = 20 `ST` | No reasons; available quantity is exactly 40 | Wrong or guessed unit conversion on stock. Unknown units are covered by the `MYSTERY` case above |
| `test_malformed_upstream_has_explicit_failure` | Price list contains `None` instead of a product row | Raises error code `UPSTREAM_SCHEMA_INVALID` | A garbled supplier reply crashing as a generic error or being half-used |

### 2.2 Product data, units and search

| Test | Scenario | Asserts | Catches |
| --- | --- | --- | --- |
| `test_evidence.py::test_dimensions_packaging_levels_and_name_conflicts` | A synthetic raw product: 1 L per piece. Then change the volume unit to grams; then set volume to 20 L while the name says 1 l; then label the measurement as a CASE level | 1000 L maps to 1000 pieces. Grams give litres "unknown" and no quantity. Gross packaging weight does not become food kilos (kg "unknown"). 20 L vs name 1 l gives "conflicting". A case-level volume gives "unknown" for litres | Guessing litres or kilos from the wrong packaging level or a wrong unit |
| `test_evidence.py::test_missing_claim_is_unknown_not_dietary_denial` | A product with no lactose-free and no milk-free claims, buyer asks for both | Two reasons, both severity `unresolved` (not `denied`) | Treating "no claim in the data" as "contains lactose" (or as "safe") |
| `test_evidence.py::test_supported_filters_and_conflicts_on_both_search_paths` | Search "milk" with lactose-free required in keyword, semantic and hybrid mode; then milk-free required (default mode only) | Every hit has the lactose-free claim; conflicting-allergen products `468044`, `469429` never appear; milk-free search returns an empty list | A dietary filter that lets a wrong product through in any search mode. Uses only the 10-product fixture catalog and fake vectors |
| `test_evidence.py::test_unchanged_embeddings_and_failed_import_keep_generation` | Re-import the catalog; re-import with only a metadata change while the embedding function is rigged to fail; then import with a changed name (needs a new vector) while it fails | Metadata-only import reuses all vectors and computes none. The failing import raises and the active catalog generation id does not change. Search for `464306` still works | A failed or partial catalog import replacing the working catalog; wasteful re-embedding. It checks the active-generation pointer only, not that no half-written rows remain |

### 2.3 Policy rules and the four outcomes

| Test | Scenario | Asserts | Catches |
| --- | --- | --- | --- |
| `test_evidence.py::test_gross_boundary` (3 cases) | Pure policy function with limit 1500 and totals 1499.99, 1500.00, 1500.01 | ready, ready, approval_required | Off-by-one at the spending limit (limit itself is allowed) |
| `test_evidence.py::test_missing_currency_is_unresolved` | Snapshot with no currency or total | `needs_resolution` | Ordering when the currency is unknown |
| `test_workflow.py::test_four_outcomes_and_hard_requirements` (8 cases) | Change `request_data`: unlisted destination; hard budget 16.99 against 17.00; milk-free required; 1000 L when 600 in stock; product with unverified litre size; 12 kg of variable-weight steak; two products with conflicting allergen data | Outcome and code: denied `DESTINATION_NOT_ALLOWED`; denied `HARD_BUDGET_EXCEEDED`; denied `MILK_REQUIREMENT_VIOLATED`; needs_resolution `INSUFFICIENT_STOCK`, `QUANTITY_UNRESOLVED`, `VARIABLE_WEIGHT_UNRESOLVED`, `DIETARY_EVIDENCE_CONFLICT` (x2). Always: no approval is opened and `commit_order` fails with `COMMIT_BLOCKED` | Letting an unfit proposal reach a buyer or the commit step. Note: the request keeps `lactose_free` on, so the non-milk products also get an unresolved dietary reason; the specific-code assertion is what proves the intended rule fired |
| `test_workflow.py::test_denied_precedes_unknown` | Forbidden destination and an unusable unit "boxes" together | `denied`, and both reason codes are listed | An unresolved fact masking a hard prohibition |
| `test_workflow.py::test_deposit_totals_and_overbuy` | 10 cases of bottles with deposits; then 10.5 L of milk (sold only in whole pieces); then the same with overbuy forbidden | Deposit lines 120 units, deposits 15.60, total 32.60. 10.5 L rounds up to 11 and needs approval. With `allow_overbuy=false`: denied | Missing deposit charges; silent over-ordering; rounding bugs |
| `test_workflow.py::test_invalid_policy_does_not_default_to_permission` | Insert policy v2 with `substitution` set to a made-up mode | `prepare_order` raises `INVALID_POLICY_CONFIGURATION` | A typo in policy turning into "allowed". Only this one field is tried; the check is a type validation, so other fields are likely covered by the same mechanism (unclear from tests alone) |

### 2.4 Autonomous purchase, commit and idempotency

| Test | Scenario | Asserts | Catches |
| --- | --- | --- | --- |
| `test_workflow.py::test_autonomous_and_idempotent_after_restart` | 10 L, within limit. Commit. Then retry using a new `Service` whose supplier connection raises if called | `ready_to_commit`, total 17.00; receipt labelled "Accepted by demo order service", `upstream_order_placed` false, status `accepted_mock`. Retry returns the identical receipt without asking the supplier; `get_order` and `get_proposal` agree | A retry re-checking the supplier, or creating a second order. "Restart" here is a new Python object, not a process restart |
| `test_workflow.py::test_concurrent_same_key_one_order` | 8 threads commit the same request with the same key | One order id; 1 row in `orders`, 1 in `idempotency` | Double orders from client retries racing |
| `test_workflow.py::test_concurrent_different_keys_and_conflicting_payloads` | 4 threads commit the same proposal with different keys. Then reuse one key for a different proposal | Exactly one `accepted_mock`, three `ALREADY_COMMITTED`. Key reuse gives `IDEMPOTENCY_CONFLICT` | Two orders for one proposal; a key being reused for something else |

### 2.5 Human approval, rejection, and invalidation

| Test | Scenario | Asserts | Catches |
| --- | --- | --- | --- |
| `test_workflow.py::test_independent_inbox_and_agent_resume` | `mission` (1700 EUR, substitution). Check buyer inbox; agent tries to commit; buyer approves (twice); a fresh `Service` resumes | `approval_required`, next action `wait`; proposal is in the inbox; commit fails `APPROVAL_REQUIRED`; approval status approved but order `not_placed`; approving twice is harmless; after approval next action is `commit` and commit gives `accepted_mock`. Policy read-back shows limit 1500.00 | An agent ordering before the human decides; approval itself creating an order |
| `test_workflow.py::test_changed_price_creates_revision_and_invalidates_approval` | Buyer approves revision 1, then the price rises 10% | Commit returns status `revised`, revision 2, approval pending. Old approval shows `superseded`; deciding or committing revision 1 gives `STALE_REVISION`; revision 2 needs its own approval and then commits. The old approval page still shows 1700.00, no order, cannot be decided, and links to current revision 2 (1870.00, with the order) | Approving one price and paying another; history being rewritten |
| `test_workflow.py::test_stock_change_blocks_old_revision` | Approved, then stock of `464306` drops to 10 | Commit returns outcome `needs_resolution` with no approval id | Ordering against stock that vanished. Does not check that the old approval is marked superseded |
| `test_workflow.py::test_rejection_expiry_and_revocation` | (a) buyer rejects; (b) buyer approves, then the buyer account is deactivated; (c) proposal waits past its lifetime (workflow clock +1 h) | (a) commit fails `APPROVAL_REJECTED`, second decision `DECISION_CONFLICT`. (b) commit returns a revised proposal with `needs_resolution`; committing that fails `COMMIT_BLOCKED`. (c) commit fails `PROPOSAL_EXPIRED` and status reads `expired` | Rejected, revoked or stale approvals still working |
| `test_workflow.py::test_policy_version_reauthorizes_and_seed_preserves` | Approve, then add policy v2 (limit 500) and run `seed` again | `seed` keeps v2 (does not reset to v1). Old approval reads `policy_changed`; commit makes a new revision under policy v2, pending | Policy edits not applying to earlier approvals; setup script overwriting live policy |
| `test_workflow.py::test_reduced_agent_authority_revises_without_policy_change` (2 cases: an eligible approver exists, or not) | Agent limit lowered to 10 EUR after a 17 EUR proposal was ready; second case also deactivates the buyer | `get_proposal` reads `authority_changed` and does not offer commit. Commit returns revision 2, same policy version, reason `AUTONOMOUS_LIMIT_EXCEEDED`; old revision then gives `STALE_REVISION`; no orders exist. With an approver: pending approval, commit blocked until approved, then `accepted_mock`. Without: `needs_resolution`, no approval id, next action `revise_request`, commit `COMMIT_BLOCKED` | An agent keeping spending power after its authority is cut |
| `test_workflow.py::test_approver_amount_and_exception_scope` | Buyer's authority set to max 1600 EUR, spend exceptions only; then a new `mission` | Approving gives `APPROVAL_SCOPE`; page `can_decide` false; a newly prepared mission is `needs_resolution` with `NO_ELIGIBLE_APPROVER` | An approver approving beyond their rights. The scenario fails both the amount (1700 > 1600) and the exception type (no "substitution"), so it cannot tell which check works |
| `test_workflow.py::test_competing_decisions_and_commit` | Approve, reject and commit race on one proposal (3 threads) | Final state is approved or rejected; never both outcomes in the results; if an order exists, the proposal must be approved | Two contradictory decisions both being recorded. The outcome is timing-dependent and the assertions are loose |

### 2.6 Upstream mode choice (`tests/test_upstream_mode.py`)

| Test | Scenario | Asserts | Catches |
| --- | --- | --- | --- |
| `test_auto_without_key_falls_back_to_labelled_fixtures` | mode `auto`, no key | effective mode `fixture`, client is `FixtureClient` | Silent use of live API without a key |
| `test_auto_with_key_uses_live_client` | mode `auto`, a made-up key | mode `live`, client is `ValioClient` | Key being ignored. No network call is made |
| `test_explicit_fixture_ignores_a_configured_key` | mode `fixture` with a key | fixture client | Accidentally hitting the live API in tests |
| `test_explicit_live_without_key_fails_closed` | mode `live`, no key | Calling the client raises `UPSTREAM_CREDENTIALS_MISSING` | Falling back to fixture data when live was demanded |

### 2.7 HTTP, security and interfaces (`tests/test_http.py`)

PR #15 rewrote the first, third and sixth tests below for the chat product; the rows describe the current code.

These use FastAPI's in-process `TestClient` (no real socket).

| Test | Scenario | Asserts | Catches |
| --- | --- | --- | --- |
| `test_auth_inbox_csrf_and_logout` | Anonymous calls to the inbox and a purchase page; an old bearer token on the inbox; the removed `/api/agent/purchase-policy` and `/mcp/`; buyer login; decide without CSRF, with a hostile Origin, then correctly; logout | 401 without a session and for a bearer token; 404 for the removed agent and MCP routes. Decision without CSRF or Origin: 403; hostile Origin with a valid token: 403; correct: 200 and `order_status` `not_placed`. Logout gives 204 and the session is then 401 | Missing login checks; CSRF bypass; the removed external interfaces coming back. A wrong token value (header present but wrong) is not tried here (the sweep does). After logout the test client drops the cookie, so server-side invalidation is not proven here |
| `test_cross_account_and_agent_isolation` | A second company (agent and approver) is created. It requests company A's proposal and inbox | Foreign agent: 404 on the proposal. Foreign buyer: empty inbox, 404 on the approval, 404 on the purchase page, 404 when trying to approve | One customer seeing or deciding another customer's purchase. Only reads and the approve action are tried; foreign `commit_order` and `get_order` are not |
| `test_input_validation_and_api_errors` | Create a conversation without an idempotency key, then with an extra `buyer_id` field; removed and unknown routes with GET and POST; a huge `limit`; health | 422, 422; 404 with a JSON content type for each route; `limit=100000` is 422 (the test now logs in first); health 200 | A client choosing another buyer; removed interfaces answering with HTML; unbounded list sizes |
| `test_login_rate_limit_and_wrong_origin` | Login without Origin; then 11 wrong passwords | 403; then ten 401 followed by one 429 | Password guessing; cross-site login |
| `test_documentation_nonce_and_scoped_csp` | Fetch `/docs`, the approvals page, session and OpenAPI | Docs page has a per-request nonce on both script tags; `script-src` has no `unsafe-inline`; styles allow `cdn.jsdelivr.net`; docs are `no-store`; the nonce changes per request; other pages get the strict policy without the CDN | A loose Content Security Policy leaking from the docs page to the rest |
| `test_shared_purchasing_operations_and_both_commit_outcomes` | Calls the `Service` functions the internal assistant uses (policy, product, search, price lookup, prepare, proposal, commit, order) directly | Policy limit 1500.00; product litre value "1"; exact-id search ranks first; unknown id gives no results; price 1.70 gross; with a 10% price rise the first commit returns `revised` revision 2 (18.70); the second returns `accepted_mock`; a retry returns the same receipt; `get_order` equals the receipt | A purchasing operation missing, renamed or returning the wrong shape. Success paths only. It no longer goes over HTTP or MCP, because those transports were removed |
| `test_historical_approval_links_current_autonomous_revision` | Approve via HTTP, then the price halves so revision 2 is within the limit and needs no approval; commit | Old approval is `superseded` with no order; the current purchase page shows revision 2, 850.00, with the order | The "view current terms" link breaking when the new revision no longer needs approval. Overlaps `test_changed_price_creates_revision_and_invalidates_approval` |

### 2.8 Tests added by teammates (from names and a skim, not read test by test)

| File | Covers, by test name |
| --- | --- |
| `test_agent.py` | The internal assistant with a scripted provider: carbonara clarification to real products and a verified basket; the model cannot choose identity, permissions or retry key, cannot authorize or commit a purchase; incomplete or fabricated plans cannot prepare; assistant text alone never creates a proposal; failed tools never become a basket; bounded tool rounds and repeated errors; missing, rate-limited, transient and malformed provider behaviour; provider failure after preparation keeps the verified basket |
| `test_agent_integration.py` | The whole carbonara flow over HTTP with the real catalog, policy, customer confirmation and persisted receipt; only the LLM provider is scripted |
| `test_conversations.py` | Conversations persist and retry safely; a failed turn resumes with the same key; confirmation cannot be fabricated and survives a restart; repricing needs another explicit confirmation; another account cannot read or confirm; expired turns resume without duplicate messages; blocked states are preserved; another authorized customer can resume after the original authority is revoked |
| `test_hardening.py` | Product scope cannot be bypassed; missing scope fails closed; exact pack rounding; atomic, restart-safe and per-agent prepare retries; cached identity cannot bypass current authority; bounded inbox queries; login-limit behaviour and trusted-proxy handling; connection pool rollback; withdrawals stay denials; ingestion keeps withdrawal markers; search survives concurrent catalog pruning |
| `test_retries.py` | Supplier retry rules: permanent failures are not retried, transient ones back off, Retry-After is respected or returned to the caller, invalid JSON is not retried |
| `test_catalog_sync.py` | Scheduled catalog sync (`aimo sync-catalog`, [catalog sync](../docs/catalog-sync.md)). An identical rerun is `unchanged`, with no embedding calls and unchanged generation/product row counts. Changed data is refused until supplied with its own hash/count. Embedding-model, import-profile, legacy NULL-profile and missing-row catalogs rebuild instead of skipping. Eight invalid snapshot kinds and download/embedding failures keep the active generation and search working. A retry after an embedding failure or lost lock reuses completed batches. A concurrent scheduled + manual run (and `aimo ingest`) gets `already-running`. A lost lock blocks publication. A search started before activation and pruning still returns the old generation. A prepared purchase is revised and denied after a sync withdraws its product. The dedicated role can sync but cannot read identities, sessions, orders, revisions or the ledger. Download bounds: retries, size limit, deadline, redirect hops and HTTPS, no signed URL or exception text in results |
| `test_memory.py` | Buyer/personal memory (read by its author): a chat save persists into a new conversation and runner and is bound to the turn's user message; two users of one buyer share buyer items but not personal ones, and another buyer sees nothing even by exact ID; a queued turn carries the requesting human, and model arguments cannot name owners/buyers/sources; temporary requests, supplier text and earlier assistant replies cannot authorize a save under an enforcing fake classifier; ambiguous scope, authority-like content and existing keys cause no write; bounded deterministic context loading and search/paging; value, size, secret and per-owner limits; idempotent replays, concurrent revision conflicts; a worker retry after a crash replays its save and a superseded or completed attempt cannot write; forgetting removes the item and every content hash; inactive users are refused; saved memory cannot change policy, outcomes or confirmation; database constraints |
| `test_memory_http.py` | `/api/memories`: 401 without a session, CSRF/Origin on create/update/delete, create/retry/conflict/list/search/update/delete with revisions, validation and secret errors, and another user's or buyer's item is 404 |

My own `test_upstream_client.py` repeats part of `test_retries.py` for the live client (headers, key never leaked, redirects not followed, transport errors); the overlap is deliberate but wasteful.

## 3. Sweep (`tests/sweep/run_sweep.py`)

Runs against a live server process with the fixture catalog and no LLM provider (the server is started with `LLM_API_KEY` empty in every mode). It uses `httpx`. Result is PASS, SKIP (with reason) or FAIL; a check that throws is FAIL. The eight purchasing tools run only inside an LLM-driven chat turn, so they are **not** swept here; `test_agent*.py` and `test_http.py::test_shared_purchasing_operations...` cover them.

| Check | Scenario | Asserts | Catches |
| --- | --- | --- | --- |
| `health/ready` | GET `/health/ready` | 200; records `upstream_mode` | Server or DB not up |
| `sign-in required` | Anonymous GET of the session, conversations, purchases, approvals and a purchase page | 401 each time | An endpoint open to anonymous callers |
| `login controls` | Wrong password; correct password from a foreign Origin; correct login and session | 401, 403 or 429; 403; then 200 and a valid session | Password guessing and cross-site login; broken login |
| `CSRF and Origin enforced` | Create a conversation with no token, a wrong token, and a foreign Origin | 403 each time and no conversation named "csrf probe" exists afterwards | State changes without CSRF protection |
| `create conversation (+ retry)` | Create with a key; repeat the identical request; reuse the key with a different title | Same id both times; the conflicting reuse is refused (any 4xx) | Duplicate conversations from a retry; a key reused for something else |
| `list and get conversation` | List, fetch, fetch an unknown id | Present in the list; empty messages and purchases; unknown is 404 | Lost or leaking conversations |
| `message CSRF enforced` | Send only a message without CSRF | 403 and no messages stored; never submits an authenticated chat turn | Unexpected model usage by a standalone sweep |
| `purchases and approvals` | List both; fetch an unknown purchase and an unknown approval | 200 with an `items` list; 404 | Broken list endpoints |
| `confirm and decide controls` | Confirm and decide an unknown proposal without CSRF, then with it | 403; then 404 | Confirming or deciding without CSRF; accepting an unknown proposal |
| `logout` | Log out, then call a protected endpoint with the old cookie | 204; then 401 | A session surviving logout |

## 4. UI tests

None run in CI. The UI in the repository is an old mockup, so the frontend job only type-checks and builds it. `frontend/e2e/` holds a teammate's Playwright specs (not read in detail here, not run by CI). When the real UI design is added, the UI test approach should be decided then; see the history entry of 2026-11-14 for what was tried and dropped.

## 5. Lint and build

- `ruff check src tests scripts`: Python style and common bug patterns. No behaviour.
- `npm run build` (`tsc -b && vite build`): TypeScript type errors and a failing production build.

## 6. Local-only scripts

None are run by any workflow. `tests/README.md` lists them as local only. The real-key sweep (`tests/ci.sh --live`) also needs a key that is not stored in GitHub.

| Script | What it checks | Needs | Built for CI? |
| --- | --- | --- | --- |
| `scripts/demo.py`, `scripts/restart_smoke.py` | Rewritten by PR #15 for the chat product (the older versions drove the removed agent API and MCP). **Not read or re-run in this branch**; `restart_smoke.py` restarts a Docker container, so it is local only | Running server; for `restart_smoke.py` Docker and a dedicated container | No |
| `scripts/verify_catalog.py` | Seven real products from the 84 MB catalog file: SHA-256 of the file; 1000 L maps to 1000 pieces; 5 pieces per case for `465039` with litres unresolved; 12 kg steak rounds to 20 kg; lettuce 4 kg to 6; allergen conflicts on `468044`, `469429`; deposit total 120 for 10 cases | The private catalog JSON path as an argument (gitignored). No server or DB | No. The data is gitignored. This is the only check of unit logic on real records |
| `scripts/evaluate_search.py` | Runs 30 curated queries through keyword, semantic and hybrid search on the full catalog with real embeddings; counts top-1 and top-5 hits, constraint violations, latency; writes `docs/search-evaluation.json` | Database with the full catalog ingested; the embedding model | No. It has no pass/fail threshold: it reports numbers and exits 0 |
| `scripts/probe_upstream.py` | Not a test. Calls the real price and availability API for 1 to 20 product ids and prints the validated evidence | `VALIO_AIMO_API_KEY`, database with catalog. Hits a rate-limited real API | No. Asserts nothing |

Also present: `scripts/export_schema.py` (8 lines, writes the API schema; not a check) and `tests/coverage_report.py` (reports line coverage, fails below the configured gate; only runs when `CI_COVERAGE=1` was used).

## 7. What these tests do NOT check

Each item is traced to code I read.

**Real supplier behaviour**
- The live client `ValioClient.post` is now exercised over a mock transport (`test_upstream_client.py`, `test_retries.py`): headers, retries and back-off, Retry-After, permanent 4xx rejection, malformed JSON, missing credentials. It has never been run against the real API by CI, and `tests/ci.sh --live` is the only real check.
- Fixture replies are generated to be internally consistent (`FixtureClient.lookup`): fresh timestamp, price validity 2020 to 2099, stock for any unknown id 5000. So `UPSTREAM_CLOCK_STALE` and `UPSTREAM_CLOCK_UNKNOWN` are never tested, and real-world oddities exist only as the 12 hand-made mutations in `test_evidence.py::test_supplier_regressions`.
- Live stock is described in the README as an unknown-quantity placeholder for the default product; the live probe uses `463380` instead and rejects unresolved evidence; the approval flow remains untested against live stock.

**Policy rules**
- Policy branches were extended in `test_edges.py` (currency outside authority, missing authority, product scope unconfigured, outside-scope substitution, an unknown exception rule). Not checked by name: `SUBSTITUTION_FORBIDDEN`, `LACTOSE_FREE_UNVERIFIED`, `MILK_FREE_UNVERIFIED` (unverified: re-grep before relying on this).
- The spending-limit boundary is tested on the pure function only (`test_evidence.py::test_gross_boundary`), not on the combination of agent limit and policy limit (the code uses the smaller of the two; the test passes 1500 vs 2000 so the min path is taken once, and the reverse is not).
- Approver amount limit and approver exception types are not tested separately (`test_workflow.py::test_approver_amount_and_exception_scope`).

**Security**
- Cross-company isolation covers one proposal read for the agent and read/decide for the buyer (`test_http.py::test_cross_account_and_agent_isolation`). Foreign `commit_order`, `get_order` and `check_price_and_availability` are not tried over HTTP; `test_conversations.py` covers another account reading or confirming a conversation.
- CSRF is tested for a missing token and a hostile Origin (`test_auth_inbox_csrf_and_logout`, sweep `reject path`). A present but wrong token, an expired session cookie, and reuse of an old cookie after logout are not tested.
- Rate limiting is tested only for login.

**Error handling over the wire**
- Most error codes are asserted through Python calls (`expect_code`), not over HTTP. The HTTP status for `APPROVAL_REQUIRED`, `STALE_REVISION`, `COMMIT_BLOCKED`, `IDEMPOTENCY_CONFLICT` and similar is rarely asserted in `test_http.py`.
- The sweep's `create conversation (+ retry)` accepts any 4xx when a key is reused for another body; it does not check the code.

**Expiry and time**
- Expiry is tested by moving only the workflow module's clock one hour (`test_workflow.py::test_rejection_expiry_and_revocation`). The proposal lifetime is 900 s, but expiry can also come from the supplier cutoff or price end date (`validate_lookup`). Which of these the test hits is unclear from the code; the commit-time cutoff path has no test. `CUTOFF_PASSED` is tested only at prepare time.

**Concurrency and restart**
- Concurrency tests use threads in one Python process sharing one `Service`. Several server processes or pods are not tested.
- No automated test restarts a process. The pytest "restart" is a new `Service` object. The only real restart is `scripts/restart_smoke.py` (local), whose retry happens after the restart, not across it.

**Search**
- Search relevance and ranking are untested in CI: fake vectors and 10 products. `test_supported_filters...` checks filters, not ordering. The sweep only checks that exact id ranks first and a text query returns at least one result. Real quality is measured only by `scripts/evaluate_search.py`, which has no pass threshold.
- Milk-free filtering is tested only in the default strategy, not in all three (`test_evidence.py::test_supported_filters_and_conflicts_on_both_search_paths`).
- Real-catalog unit conversions (the 17,546 products) are checked for 7 products by a local script only.

**Frontend**
- The UI has no automated test in CI (old mockup): only `tsc` and the production build. Frontend code is not measured for coverage.
- The chat assistant's wording and the real LLM provider are never tested: the provider is always scripted.

**Mock ordering**
- Orders are mocks. Tests assert `upstream_order_placed` is false once (`test_autonomous_and_idempotent_after_restart`). No test inspects outgoing HTTP calls to prove a real supplier order is never sent. Unclear from the code whether any such code path exists; the README says there is no order endpoint.

**Database**
- Migrations are run at test start only on an empty or existing test DB. No test of upgrading an older schema, or of the Kubernetes and Docker image (README says so).

## 8. Weak or redundant tests

| Test | Why |
| --- | --- |
| `test_http.py::test_input_validation_and_api_errors` (`/health/live`) | Repeated by `tests/ci.sh`, which polls `/health/live` before running anything |
| Sweep `message CSRF enforced` | Checks CSRF rejection only; missing-provider behavior is covered by backend tests |
| `test_workflow.py::test_stock_change_blocks_old_revision` | Asserts only the new revision's outcome and no approval id. Does not check the old approval or that commit is blocked |
| `test_workflow.py::test_competing_decisions_and_commit` | Result depends on thread timing. Assertions allow several valid orderings; it would catch only a flagrant contradiction |
| `test_upstream_mode.py::test_auto_with_key_uses_live_client`, `test_explicit_fixture_ignores_a_configured_key` | Check only class type; no behaviour |
| `test_http.py::test_historical_approval_links_current_autonomous_revision` | Repeats most of `test_workflow.py::test_changed_price_creates_revision_and_invalidates_approval`; the new part is the "no approval needed at revision 2" case |
| `tests/test_evidence.py::test_gross_boundary` | Fine as a boundary test, but the same rows are all `spend`; nothing else about the limit rule is varied |
| Commit and retry flow | Checked in `test_autonomous_and_idempotent_after_restart`, `test_shared_purchasing_operations_and_both_commit_outcomes`, `test_conversations.py` and `test_agent_integration.py`. Overlap is deliberate (different layers), but a failure will show in many places |
