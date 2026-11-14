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

## 9. Person 3 backend tests (WS-A to WS-D, added 2026-11-14)

Entries for the contract tests added by the four person-3 workstreams and the integration fixes. Written by reading the test code and running each file once (local run, not CI) on the tuned test database; counts are `passed / xfailed`. Everything uses fixture (invented) commerce and the 10-product fixture catalog; nothing here calls the live supplier or an LLM, and every order is the demo order service's mock acceptance.

A **strict xfail** is a known gap written as a test of the desired behaviour: it is expected to fail today and turns red (XPASS) the moment the gap is closed, which is the signal to delete the mark. It is not a pass, and it proves the behaviour is still missing.

### 9.1 WS-A: catalog and supplier evidence

Draft entries for `tests/TEST-GUIDE.md`, written by reading the test code. Counts are from one run per file on branch `p3/integration-fix` against the `aimo_p3_tg_a_test` database: 13 files, 377 passed, 52 xfailed, 0 failed, 0 errors. Everything uses fixture (invented) commerce, the 10-product fixture catalog and fixture vectors; no live supplier, no LLM. Tests that republish a catalog restore the shared fixtures afterwards.

A strict xfail is a known gap, not a pass: the test states what the requirement should do, fails today for the stated reason, and turns into an error (XPASS) the day the gap is closed so the marker gets removed.

#### test_catalog_cleanup.py (JNP3-DIS-011, DIS-012; both Draft) - 9 passed

Checks removal of withdrawn products (flagged `deleted`) from the stored catalog. DIS-011: `cleanup_withdrawn()` removes withdrawn products that no pending proposal names. DIS-012: when withdrawn products exceed 10 percent of the active generation's rows, the oldest by `withdrawn_since` are removed (run by `publish(..., trim_withdrawn=True)`, which `ingest_file` uses). "Pending" means not committed, not rejected/expired/superseded; a closed saved-recipe proposal tied to a recipe plan with no order is also protected because it can be refreshed.

| Test | Scenario | Asserts | Catches |
| --- | --- | --- | --- |
| Two controls | One committed order (464306), one pending proposal (464398), one unused product (463380), all flagged withdrawn; and an expired recipe proposal with its product flagged | Rows stay stored and flagged; order and proposal still readable; the recipe proposal has a plan link, no order | A setup that cannot show the protection rule at all |
| Cleanup keeps what a pending proposal names (2 tests) | Run `cleanup_withdrawn()` | 464398 (pending) kept and still withdrawn; 463380 and the committed-only 464306 removed; live products untouched; same for the refreshable recipe product | Deleting a product a buyer is still deciding on, or keeping garbage nobody uses |
| Ten percent boundary | 2 of 20 withdrawn, then 3 of 20 withdrawn with back-dated withdrawal dates | At exactly 10 percent nothing goes. At 15 percent the oldest goes first, then the next, until at most 10 percent (2 removed, newest kept); generation row count still matches its product count | Off-by-one at the limit; removing by id order instead of age; leaving a generation that cannot be re-activated |
| Trim skips protected products (2 tests) | Oldest withdrawn product is named by a pending (or refreshable recipe) proposal | It stays; the next-oldest ones are removed instead (2 removed) | The automatic rule deleting protected data |
| Nothing withdrawn | Ingest with no flagged product | 0 trimmed | The rule deleting data when nothing is withdrawn |

Passing proves the rules on small invented catalogs. It does not measure a real 84 MB catalog or timing.

#### test_ingest_malformed.py (JNP3-SUP-002) - 19 passed

The catalog download is treated as a supplier response: each record is checked before anything is published.

| Test | Scenario | Asserts | Catches |
| --- | --- | --- | --- |
| Control | A snapshot of three good records | Ingest publishes 3 products and activates | A guard that rejects everything |
| `test_a_malformed_record_is_a_clean_error_naming_the_record` (14 cases) | One of three records broken: missing, non-string or empty id; unit without id or size, non-numeric size, units not a list; name without language; classification without name or value id; non-numeric measurement; non-numeric or negative lot size; `synkkaData` not an object | A `ValueError` (not `KeyError`) whose text says "record" and the position `#1`, plus the product id when it has one; the active generation is unchanged | A crash with an unreadable error; half a snapshot being published |
| Record is not an object (4 cases) | The middle record is `None`, 7, a string or a list | `ValueError` naming `#1` | A non-object record crashing the loader |

#### test_ingest_rerun.py (JNP3-DIS-002) - 4 passed

Drives the real `aimo ingest` command into the test database with synthetic snapshots.

| Test | Scenario | Asserts | Catches |
| --- | --- | --- | --- |
| Whole snapshot published | Ingest two products | A new active generation holding exactly those two synthetic ids | Old rows leaking into the new generation |
| Rerun of an unchanged snapshot | Same file ingested twice | A second, different generation id; same ids; 0 new vectors, at least 2 reused; no duplicate or partial rows and the row count equals the stored count | Row-by-row updates, duplicates, needless re-embedding |
| Refused run | Wrong sha, then wrong expected count | `ValueError` both times and the active generation is unchanged | A failed run changing the live catalog |
| Rerun keeps a rollback | Old catalog, new catalog, new catalog again | The old generation survives (the identical copy gave up its slot); re-activating it restores the old product set | A rerun deleting the only different earlier catalog |

#### test_lookup_batching.py (JNP3-SUP-007, Draft) - 4 passed, 6 xfailed

A price and availability lookup must be split into batches within the supplier's 1 to 1000 ids per request. `httpx.MockTransport` records the POSTs; no network.

| Test | Scenario | Asserts | Catches |
| --- | --- | --- | --- |
| Control and splitting (4 passing tests) | 3 ids; 1500 ids with the batch size env set to 250; 1500 ids with no setting; batch order | One request per endpoint for a short lookup; no request over the configured size; default 100 gives 15 requests per endpoint; batches in order equal the requested ids with no duplicates and the merged response covers every id | A 1500-id lookup sent in one oversized request; lost or repeated ids |
| Settings (xfail) | `Settings.supplier_lookup_batch_size` | See below | The setting not existing in `config.py` |

STRICT XFAIL (6): the `supplier_lookup_batch_size` setting (JNP3-SUP-007 d) is absent from `Settings` (`config.py`; "waiting for person 1"). The cases are: 1000 ids is one call and 1001 is two (via the env var, which is ignored today); default 100 and env override; 1 and 1000 accepted (2 cases); 0 and 1001 rejected (2 cases). Batching itself works (module default 100); only the configurable, validated setting is missing.

#### test_lookup_delivery_date.py (engineering guard, cites JNP3-TCT-003) - 8 passed

`LookupRequest` accepts delivery dates from 2000-01-01 to 2100-12-31 (4 cases, including a `date` object) and rejects `0001-01-01`, 1999-12-31, 2101-01-01 and 9999-12-31 with a validation error located at `delivery_date` whose message names a limit. Catches an implausible date reaching the supplier call and being reported as "retry later". The window is fixed, not relative to today. Not an owner rule.

#### test_lookup_units.py (JNP3-TCT-005, JNP3-SUP-007) - 19 passed

TCT-005: lookup evidence states its units. Case product sold in `KI` with base unit `BOT`: evidence reports sales unit, base unit, `price_basis: per_sales_unit`, quantity unit and stock. A priced product missing from the catalog map (deposit material) gets null units, never guessed. An unpriced reply has no price basis. The pre-existing evidence keys are unchanged (4 tests).

SUP-007 merge behaviour (15 cases, mocked transport; the batch-size field is simulated on `Settings` because `config.py` lacks it): size 1000 splits 1000 into one batch and 1001 into 1000+1; out-of-range settings are clamped (5000 to 1000, 0 and -3 to 1, text to 100); with no setting the module default 100 gives 100, 100, 50; batches run one after another, all price batches then all availability batches, ids kept in order; the merged reply keeps customer id, currency, pricing date, requested date and time; batches that disagree on customer, currency or date (5 cases) or return a non-list `products` raise `UPSTREAM_SCHEMA_INVALID`. Catches a merge that mixes replies for different customers or dates. Passing does not prove the real setting exists (see the xfails above).

#### test_search_contract.py (JNP3-DIS-004 to 007, DIS-009) - 8 passed

| Test | Scenario | Asserts | Catches |
| --- | --- | --- | --- |
| Candidate shape (3 strategies) | Search "milk" in keyword, semantic, hybrid | Reply validates as `SearchResponse`; note says "candidates only"; each hit has provenance matching its id, a float score, `match_is_suitability_proof` false and the claims/allergens/free-from/units/measures/order-step fields | Search presenting a match as proof of suitability |
| Response model | Try to set the proof flag true | Model validation fails | The contract being loosened |
| Supported requirements | `vegan` filter rejected; lactose-free search | Unsupported filters raise, never silently ignored; every hit carries the lactose claim | A filter ignored quietly |
| Withdrawn product (3 strategies) | 464398 flagged deleted | Not a candidate for a name, text or id query, but other results still exist and `get_product` returns it with `deleted` true | Offering withdrawn goods while still allowing exact lookup |

#### test_search_filters.py (JNP3-DIS-013) - 95 passed

Allergen free-from and country-of-origin filters on a modified fixture catalog (five milk products with different declarations: A contains milk and is free from eggs and wheat, origin fi; B free from eggs and milk, se; C no declaration, no country; D may contain eggs, de; E free from all three, fi).

| Theme | Scenario | Asserts | Catches |
| --- | --- | --- | --- |
| Matrix (21 cases x 3 strategies) | Each filter alone, two codes (all required), country any-of, upper-case input, unknown code or country, combined with lactose-free and milk-free, all four together | The exact set of product ids in every strategy | A filter leaking or dropping a product in one search mode |
| Missing proof (3 strategies) | Product C has no declaration | Present with no filter, excluded by free-from or by any country filter | Treating "no data" as safe |
| Conflicting data | 468044 and 469429 list milk as contained and free-from | Excluded from a milk free-from search | Trusting a contradictory listing |
| Python recheck | Facts that contradict each other | `denied` `FREE_FROM_REQUIREMENT_VIOLATED`; unaffected code gives no reason | Trusting the database listing alone |
| Exact-id path (3 strategies) | Search by product id with filters | Same filtering as text search | A bypass via id lookup |
| Invalid input (15 cases) | Empty, SQL-like, too long, wrong shape, more than 8 items, 3-letter country, unknown field | Model validation error, both directly and in `SearchRequest` | Bad input reaching SQL |
| Normalisation and wire shape | Mixed case and duplicates | Upper-case codes, lower-case countries, empty lists omitted from JSON so old request fingerprints are unchanged; schema has the five expected fields and is closed | Silent change of stored fingerprints |
| Purchase lines (5 cases + 1) | `prepare_order` with an undeclared or contradicted requirement | `FREE_FROM_UNVERIFIED` / `ORIGIN_UNVERIFIED` give `needs_resolution`; `*_VIOLATED` gives `denied`; satisfied requirements add no filter reason | A purchase going ahead on unverified origin or allergen |

#### test_substitutions.py (JNP3-DIS-010, Draft) - 3 passed

Supplier substitution rules for 464306 (valid target, self-substitution, target absent from the catalog, target withdrawn, another valid target). Passing tests: the raw rules are readable through `get_product` and a line declaring a substitute needs approval; `list_substitution_candidates` returns exactly the two valid targets in rule order with `source: supplier_rule` and no suitability claim; a product without rules gets no supplier-rule candidates. Catches offering invalid rule targets as candidates. NOTE: the file docstring still says "nothing is built yet, so the tests ... are strict xfails"; there are no xfail markers and all three pass, so the docstring is stale. Does not cover buyer-list candidates.

#### test_supplier_mode.py (JNP3-SUP-006) - 5 passed

Every supplier result says whether it is live or fixture, using `LiveLabelled` (invented fixture data labelled `live`; no supplier call). Tests: lookup result and each product carry the mode (2 cases); the stored proposal snapshot, each line's evidence, the receipt and `get_order` carry the mode (2 cases); committing a fixture-priced proposal with a "live" service creates revision 2 with mode `live` rather than ordering on old terms. Catches fixture terms being committed as live. Proves labelling only.

#### test_tool_surface.py (JNP3-TCT-001, 002, 003, 005) - 188 passed, 45 xfailed

The 13 agent tools driven through `ToolSession.invoke`. Passing: all 13 registered with no flag (8 purchasing, 5 recipe); each has a described closed schema and no human-authority name; each tool has its own input model; non-object arguments (7 payloads x 13 tools), unknown fields including identity, retry-key and authority (4 x 13), and a wrong-typed value in each field are rejected as `INVALID_TOOL_ARGUMENTS` (422) before any service call; a list of missing, range and shape violations; unregistered names such as `commit_order` or `approve` give `TOOL_NOT_ALLOWED` pointing to customer confirmation; unknown ids give `NOT_FOUND`; workflow errors name the tool to use first; errors contain no connection strings or traces; the runner returns a `{code, message}` envelope with `purchase_authorized` false; out-of-range delivery date is not reported as "retry later". TCT-005: search, product, lookup, meal plan, proposal, receipt and recipe results carry units, conversion basis, mode, observation time and currency; a guard fails when a tool is added without a result check. Proves shape and error handling of fixture output; it does not exercise the language model.

STRICT XFAIL (45), all gaps:
- TCT-002, 13: no tool input model has an example in its JSON schema.
- TCT-002, 13: the tool spec has no declared output model (`response`/`output`/`result`).
- TCT-003, 13: the invalid-argument message is one fixed text and does not name the field to correct (`agent_tools.py` discards the validation details).
- TCT-003, 3 + 2 + 1: a NUL byte in a string argument (product, search, lookup, recipe tools) reaches PostgreSQL as a raw driver error, not a `Problem`, and the runner ends the whole turn with `TOOL_EXECUTION_FAILED` (503) instead of returning a correctable error.

#### test_upstream_default.py (JNP3-SUP-005) - 8 passed, 1 xfailed

Fixture mode only when asked for or when no key exists; live otherwise. Passing: the Terraform default for `upstream_mode` is not `fixture`; code and `.env.example` default to `auto`; `auto` without a key logs a FIXTURE warning and labels every result `fixture`; with a key and no mode the client is live; explicit `fixture` gives the fixture client; `live` without a key fails closed with `UPSTREAM_CREDENTIALS_MISSING`; an unknown mode is rejected; a local run (`SECURE_COOKIES=false`) without a key still starts and serves `/health/live`. Catches a silent fall-back to invented prices. The Terraform test only checks the default is not "fixture"; it does not prove the deployment is live.

STRICT XFAIL (1): a hosted deployment (`SECURE_COOKIES=true`, no supplier key) must fail at startup (owner decisions Q-01 and Q-55); today the app starts, because the startup guard is not built (person 1, issue #73).

#### test_withdrawn_absent.py (JNP3-DIS-008, DIS-009; both Draft) - 7 passed

Real `ingest_file` with synthetic snapshots (60 live filler rows so the 10 percent trim does not remove the product under test). Passing: a product dropped from snapshot B stays stored with `deleted` true and the result counts withdrawn products; it survives a third snapshot; ordering it is `denied` with `PRODUCT_DELETED` and no `PRODUCT_UNKNOWN`; it is never a candidate by name, id or GTIN in any of the 3 strategies while its neighbours are found; a control with an explicitly flagged product. Catches an absent product vanishing or being offered again. NOTE: the file docstring still says "each test is a strict xfail"; there are no xfail markers, so it is stale.

### 9.2 WS-B: meal plan and basket arithmetic (10 files)

All of these use authored (invented) fixtures: the 10-product fixture catalog (`aimo.fixtures`), `FixtureClient` for supplier answers, and authored recipe and product-evidence files written to a temp folder. Nothing here calls the live supplier or reads the real catalog. Counts below are from one run per file against the `_test` database, on this tree. Totals: 231 passed, 17 xfailed, 0 failed. A "strict xfail" is a test that asserts the behaviour we want, is expected to fail today, and turns red (XPASS) as soon as someone builds the feature. It is a recorded gap, not a pass.

#### `tests/test_arithmetic_contract.py` (JNP3-BAS-006, MEA-009, PRP-006, BAS-005, BAS-007) - 27 passed, 1 xfailed

Checks that the quantity maths is exact: purchased amounts are whole multiples of the product's lot size, the needed amount is kept next to the rounded purchase amount, deposit charges are part of the total, no `float` is used in the money and quantity code, and a variable-weight product is still flagged.

| Test | Scenario | Asserts | Catches |
| --- | --- | --- | --- |
| Lot size six (5 needs x 2 modes) | Need 7, 6, 6.0001, 1, 13 pieces of a product sold in steps of 6, with whole-packs on and off | Buys 12, 6, 12, 6, 18; excess 5, 0, 5.9999, 5, 5; status `derived` | Rounding to the wrong multiple, or dropping a tiny excess |
| Kilogram step kept; every need 1..60 | A weight-sold product with step 3 and need 4 kg; then every need from 1 to 60 against step 6 | 6 kg bought (step is kept even with whole-packs); every result is an exact multiple, at least the need, and under one lot too many | Over-buying a whole extra lot; fractional lots |
| Missing lot size | Step "0" | No quantity, status `unknown` | Guessing a lot size |
| Required next to purchased (2 tests) | 20.0001 request units against a 1.5 step; and a full order of 10.5 L of milk | `requested_amount` stays as typed, `proposed_amount` is the rounded purchase, excess = purchased minus required; the original request is not overwritten (10.5 L buys 11, excess 0.5) | The need being replaced by the rounded number |
| Gross total with deposits | 10 cases of bottles | Total = price + deposits, deposits are above zero, snapshot and line agree | Missing or double-counted deposit charges |
| Unknown deposit price | Supplier marks the deposit price as an error | Reasons `DEPOSIT_UNRESOLVED` and `TOTAL_UNRESOLVED`; totals are `None`; outcome `needs_resolution` | A missing deposit price being counted as 0 |
| No-float guard (1 helper test + 7 modules) | Parses the source of the arithmetic modules (catalog, numeric, purchases, approval policy, workflow, service, recipes) for `float(...)` or float literals | No hits; the detector itself is shown to catch both forms | Binary floating point creeping into money or quantities. Checks source text only, so a float built another way would not be seen |
| Variable weight still flagged | A raw product with no `variableUnit` flag, then with it set false | Missing means flagged (`True`); explicit false means `False` | Treating unknown as "fixed weight" |

Strict xfail:
- `test_variable_weight_line_is_flagged_but_does_not_block` stands for BAS-007 (owner decision: warn only). Today a variable-weight line (12 kg of product `460675`) still makes the outcome `needs_resolution`, because `purchases.py` and `recipes.py` still block it (implementation deferred, ISS-JCT-001). The flag half of the test already holds; the "must not block" half fails.

#### `tests/test_basket_contract.py` (JNP3-BAS-001 to BAS-005, plus BAS-008 shortfall) - 33 passed, 1 xfailed

Checks how a basket is built from needs: whole packs, one line per product, unit conversion from catalog evidence only, excess per line, and exact decimal money. It does not repeat what `test_arithmetic_contract.py` already proves.

| Test | Scenario | Asserts | Catches |
| --- | --- | --- | --- |
| Whole packs (2) | Default policy; four products (10.5 L, 0.3 L, 7 L, 30 bottles at 12 per box) | Policy flag is on; every line is a whole number of packs covering the need and tagged `buyer_policy.whole_sales_units`. With the flag off (policy v2) 10.5 L is bought as 10.5 | Part packs ordered when policy forbids; the flag being ignored |
| One line per product (2 passing) | Two lines for the same product in a request; the agent tool with split lines, a wrong sum, then the correct sum | Schema says "Combine quantities for duplicate product IDs"; the tool gives `INVALID_TOOL_ARGUMENTS`, then `MEAL_BASKET_MISMATCH`, then one correct 10.5 L line | Duplicate lines for one product reaching pricing |
| Conversion evidence (4) | Cases ST, KI, L, a kg-based product, and "piece" with and without a reviewed count | The `basis` lists exactly the catalog facts used; pieces convert only with reviewed count evidence | Conversions without a named source |
| No evidence, no conversion (5 cases + 1 service test) | Unknown unit, kg with no weight value, name hint only, conflicting measure, conflicting units; then a basket with one such line | No quantity, no amount, no excess; status `unknown`/`conflicting`; whole total is `None` and outcome `needs_resolution` | Guessing a conversion from a name or leaving a hole priced as zero |
| Excess (3 + 3) | Many needs against several steps; exact fit; 30 bottles; short stock (3 of 10) | Excess is never negative and equals purchased minus required; zero only on an exact fit; `INSUFFICIENT_STOCK` says "Only 3 ST available"; `shortfall` is "7" | Negative or wrong excess; missing shortfall (BAS-008 now implemented) |
| Exact money (7) | 2.675, 0.005 rounded half up; JSON `0.1` read as a decimal; ceil(2.1 / 0.3); snapshot money fields; a 16.66666 amount; repeating decimals | Money has 2 decimals and adds up; no float enters; over-long or non-terminating amounts are refused or shown as long decimal strings (characterisation, to be updated if an exact form is added) | Float rounding errors, such as 2.1 / 0.3 giving 8 packs |
| Third-of-a-unit deposit | Deposit worth 1/3 of a unit at 0.165 EUR | Charged 0.06, equal to the exact fraction rounded half up | Rounding before dividing |
| Deposit text and retry (2) | Whole-number deposits; a repeated prepare with the same key | Text matches the old calculation (it feeds the fingerprint); the retry returns the saved proposal without calling the supplier or recomputing money | Changing the fingerprint of existing proposals |

Strict xfail:
- `test_combined_line_keeps_each_contributing_ingredient` (BAS-002): through the agent tool `prepare_order`, the snapshot line has no `contributions` (which ingredients it serves). The backend model supports them (the free-form test in `test_contributions_contract.py` passes), but `ToolSession.prepare` in `agent_tools.py` (person 2) does not attach them yet.

#### `tests/test_basket_errors.py` (Q-44 / BAS-009) - 23 passed, 0 xfailed

Pure tests, no database or supplier. When the agent sends a basket that does not match the meal plan, the error must say exactly what to send (owner decision: units attached, we supply the answer). Covers `required_basket`, `mismatch_details` and the error objects.

| Test | Scenario | Asserts | Catches |
| --- | --- | --- | --- |
| Required basket (6) | Same-unit contributions summed; input order shuffled; milk in L and KI; unknown conversion; no product facts; decimal inputs | Sorted by product id, ingredient names listed, combined amounts in the priority unit (5 L + 1 KI = 25 L); unknown conversion gives `None` plus a reason; amounts are exact strings; a float input raises `TypeError` | Order-dependent or float results; silent guessing |
| Mismatch details (11) | Exact basket, one missing, one extra, wrong unit (20000 G), wrong amount, "20.000" vs "20", several faults at once, object-style lines, shuffled input | Separate lists `missing`, `unexpected`, `wrong_amount_or_unit` with required vs sent; equal values in different spelling match; output is order independent. Two units of one product are combined before comparing; unknown-conversion products are not compared | A wrong basket being described vaguely or wrongly |
| Problem objects (6) | Build the errors and read their message | `MEAL_BASKET_MISMATCH` and `UNIT_CONVERSION_UNKNOWN`, status 422, still an ordinary `Problem`; the message contains "Send exactly: eggs 100 piece; ..." and "Missing: ..."; details survive JSON and hold no floats | The agent not being told the fix |

#### `tests/test_contributions_contract.py` (MEA-005, MEA-009, BAS-002 stricter readings) - 17 passed, 1 xfailed

Checks that a basket line names the ingredients it serves, with each ingredient's share of the pack purchase, and that rejected product choices are recorded. Shares must add up exactly to the line.

| Test | Scenario | Asserts | Catches |
| --- | --- | --- | --- |
| Pure allocation (6) | Splits of 33 purchased / 2.5 excess; three equal shares of 10; a 20/10/7 split of 39; unknown line amount; other unit | Shares sum exactly to the line (fractions such as `10/3` are kept exact, not rounded), are proportional, each covers its own need; no share when the line is unknown or units differ; inputs not changed | Shares that lose or invent a pack |
| Request model (3) | Line with and without contributions; mismatched sum; a saved-recipe request | Dump unchanged when empty; contributions must add up to the line amount ("add up"); not accepted on a saved-recipe request | Hand-made contributions that disagree with the line |
| Free-form path (2) | Prepare with contributions (5 L + 5.5 L) and without | Snapshot line carries them with exact shares summing to the purchase; none when not given | Contributions lost in the snapshot |
| Saved-recipe path (4) | Three ingredients (20, 10, 7 kg) on one 3 kg product; three separate products; line not on the basket; fingerprint | Shares 20/10/7 of 39 kg bought (13 packs, excess 2), each ingredient on its own product alone; plan ingredients not on the basket are ignored; the material fingerprint is the same with or without contributions | A change in contributions altering approval fingerprints |
| Rejected selections (2) | Match a wrong product through the batch call, then another, then the right one | Rejections are stored per revision and appended (`recipe-egg`, then `recipe-pepper`), kept after the final match; an older revision keeps its own history | History overwritten |

Strict xfail:
- `test_gap_meal_plan_accepts_a_rejected_selection_on_an_ingredient` (MEA-005 "selections"): the stored plan ingredient now carries `rejected`, but `chat_schemas.Ingredient` forbids extra fields, so `MealPlan.model_validate` raises `ValidationError`. It needs the field added by person 1.

#### `tests/test_draft_contract.py` (MEA-011, MEA-012, MEA-013, SUP-007, BAS-008, BAS-009, PRP-006 line bug) - 12 passed, 3 xfailed

Requirements that are still "Draft" or newly approved. Each test asserts the wanted behaviour. Some now pass because the feature arrived (supplier batching, shortfall, line bug, 1000 lines/ids); the rest are still gaps.

| Test | Scenario | Asserts | Catches |
| --- | --- | --- | --- |
| Terminating quantity unchanged | 150 g x 200 / 6 | Exactly "5" | Rounding touching an exact value (guard for MEA-012) |
| 1000 purchase lines; 1000 lookup ids | Build requests with 1000 items | Accepted | Early caps on large requests |
| Lookup batching (SUP-007) | 2500 ids with a stub supplier transport | Every request has at most 1000 products; no id lost or repeated in price or availability | One oversized supplier call |
| Numeric shortfall (BAS-008) | Stock 3, need 10 L | `shortfall` equals packs needed minus available | Only a text reason existing |
| Unpriced deposit on the line | Deposit price missing | Line gross, deposits, net, tax are `None`, not zero | A line looking cheaper than it is |
| No shortfall when covered | Stock is enough | No `shortfall` key | Changing old fingerprints |
| Material cap | Constants | `MAX_BASKET_LINES == MAX_LOOKUP_IDS == MAX_MATERIALS == 1000` | Limits drifting apart |

Strict xfails (3):
- `test_absurd_quantity_per_portion_is_rejected` (MEA-011): `scaled_plan` has no maximum per portion (the value is pending), so 9,999,999 kg per serving x 10,000 portions is accepted.
- `test_scaled_quantity_is_rounded_up_to_four_decimals` (MEA-012, 3 cases): a quantity needing more than 4 decimals is left unresolved (`None`), not rounded up (3.3334, 6.6667, 0.0334 expected).
- `test_meal_plan_accepts_one_thousand_ingredients` (MEA-013): `MealPlan.ingredients` in `chat_schemas.py` (person 1) is still capped at 30.
- `test_recipe_with_one_thousand_ingredients_can_be_scaled` (MEA-013): `Recipe` (100) and `scaled_plan` (30) in the recipe files (person 2) are not raised.

#### `tests/test_matching_contract.py` (MEA-014) - 14 passed, 0 xfailed

Checks the batch call that matches many ingredients to products in one step, using an authored 3-ingredient recipe and 3 authored products.

| Test | Scenario | Asserts | Catches |
| --- | --- | --- | --- |
| Request shape (3) | Valid pairs; empty, 1001, bad revision, bad uuid, extra fields; `Service.match_ingredients` exists | Up to 1000 pairs accepted; all malformed forms refused | Loose input |
| One revision (2) | Match all three at once, then the same matches one by one on a second plan | Plan moves from revision 1 to 2 (one step), single matching needs 4; ingredient results are identical | Batch behaving differently from single matching |
| Wrong or absent product (2) | Wrong product for spaghetti; a product id that is not in the catalog | That ingredient is `unresolved` with a reason (product id `None`, rejection recorded), others matched; "absent" in the reason; not an error | A bad guess failing the whole batch or being accepted |
| Partial batch | Only one pair | Others stay unresolved | Untouched ingredients changing |
| Atomic failures (4) | Stale revision, unknown ingredient, duplicate ingredient, locked plan | `RECIPE_PLAN_CHANGED`, `INGREDIENT_UNKNOWN`, `INGREDIENT_DUPLICATE` (422), `RECIPE_PLAN_LOCKED`; revision count unchanged each time | Half-written batches |
| Other agent; service path | Another agent id; call through `Service` | `NOT_FOUND` or `AUTHORITY_REVOKED`, no revision; service writes revision 2 | Cross-agent access |

#### `tests/test_persistence_contract.py` (JNP3-PER-001, PER-003, PER-004) - 17 passed, 4 xfailed

Checks that plans, proposals, approvals, confirmations and orders are kept in PostgreSQL and survive a "restart" (all pooled connections closed and a new `Service`; not a process restart). It also checks reading by id, scoping, and that history cannot be changed.

| Test | Scenario | Asserts | Catches |
| --- | --- | --- | --- |
| PER-001 restart (4) | Fully matched plan (revisions 1 to 4); recipe source and evidence; confirmed order; chat message with plan and proposal | All four revisions, selections, conversion numbers, attribution/licence/source hash, approval, confirmation fingerprint, order receipt and audit events are in the database after the pool restart; a new `Service` returns the same order | Data held only in memory |
| History tables (3 cases) | UPDATE and DELETE on `proposal_revisions`, `customer_confirmations`, `audit_events` | Database raises "immutable history" | Editing the approval record after the fact |
| Failed prepare | An error injected before commit | Zero rows in proposals, revisions, approvals, audit events, prepare requests; plan unlocked, four plan revisions kept | Half-saved proposals |
| Tool session memory | New turn after matching | Session state (plan, verified products) is gone, `PRODUCT_NOT_VERIFIED` is raised; the plan reloads from the database | Hidden reliance on in-memory state |
| PER-003 read by id (7) | Plan by id; via `Service`; HTTP read of a proposal; plan and proposal link each other; old revision read by its approval id; outsiders; chat copy | Current revision is named; totals equal the stored ones and line prices plus deposits; plan locked at the revision used; old approval shows `superseded` and points to the current one; other agent, other buyer, other buyer's approver get `NOT_FOUND`; the chat copy of a plan carries its own revision number but goes stale (recorded, no totals copied) | Leaking another buyer's data; unlabelled stale copies |
| PER-003 revision stays readable | After restart | The plan revision a proposal names is still stored and equals what the agent saw (owner decision Q-46: enough, no read-by-number API) | A proposal pointing at a lost revision |

Strict xfails (4, one test with 4 statements):
- `test_per_004_plan_revisions_and_recipe_versions_are_append_only_in_database` (PER-004, Draft, Q-47): UPDATE and DELETE on `recipe_plan_revisions` and `recipe_versions` succeed because those tables have no `immutable_record` trigger (only `proposal_revisions`, `audit_events`, `policies`, `customer_confirmations` do), although `docs/recipes.md` calls plan revisions immutable.

Recorded as current behaviour: the same buyer's approver can read a proposal but not the plan by id, because plan reads filter on the creating agent.

#### `tests/test_recipe_arithmetic.py` (JNP3-MEA-001 to MEA-009) - 54 passed, 2 xfailed

Largest file. Pure tests call `scaled_plan` directly; database tests use the authored carbonara recipe (base 2 servings) scaled to 200 portions with 3 authored products. Grouped by requirement.

| Group | Scenario | Asserts | Catches |
| --- | --- | --- | --- |
| MEA-003 arithmetic (8 + 5) | 8 unit conversions (g, kg, ml, l, piece); 1500 random cases against an independent exact `Fraction` calculation; 100 g / 3 servings; 15-digit results; no-float guard on `recipes.py` | Amounts are exact (200 g x 200 / 4 = 10 KG); a result needing more than 4 decimals or 14 digits is `None` with the reason "exceeds supported precision", never rounded; inputs not mutated | Rounding or float drift in a scaled quantity |
| MEA-002 validation (4 groups) | Servings 0, -1, 10001; portions 0, -1, 10001; units `tbsp`, `KG`, `Kg`, `kg `, `dl`; scaling `damped`, `sublinear`, `fixed`; missing quantity; 30 vs 31 ingredients | Bad numbers refused; unsupported units and scalings are `unresolved` with a reason, unit names match exactly; 31 ingredients give `RECIPE_TOO_LARGE` | Guessing a conversion or rule |
| MEA-004 scaling basis (3 + 1 + 1) | Feeding scaled amounts back as a recipe; only one caller of `scaled_plan`; import with serving basis 0; a new turn for the same recipe | The only correct second scaling uses portions as base; the only caller scales a stored recipe version; a new turn starts from the stored base (20 KG, not 2000) | Scaling twice |
| MEA-001 demo | Reviewed recipe to proposal | Rows: spaghetti 20 KG -> 7 packs, eggs 100 pieces -> 4, pepper 0.2 KG -> 1; proposal agrees, `recipe_basis` `saved_recipe`, no order | The end-to-end chain breaking |
| MEA-005 explanation (4 passing) | Proposal links to the plan revision; all revisions kept; shared product line | Every line traces to one ingredient; selection history is revisions 1..4; the request line holds no breakdown but the snapshot line names its ingredients (20 and 10 KG) | Untraceable lines |
| MEA-006 count to weight (3) | 100 pieces against a product with a known 1 kg weight; egg with the count evidence removed; operator override | No weight is invented from pieces (unknown without count evidence); the unresolved egg blocks preparation with `INCOMPLETE_MEAL_PLAN`; the only fix is a reviewed unit/quantity override at import | Inventing a piece-to-kg conversion |
| MEA-007 matched or unresolved (4) | Unmatched plan; saved plans through full, partial, wrong-product and unreviewed-form cases | Every ingredient is exactly `matched` (with product and conversion) or `unresolved` (with reason, no product); never `proposed` | Half-states |
| MEA-008 incomplete basket (3 passing) | Egg unresolved; basket with only matched lines, then all three; agent tool; free-form basket in a later turn | `INCOMPLETE_MEAL_PLAN`, no proposal created, plan not locked; same through the tool; a free-form basket from a later turn is accepted but labelled `free_form` (documented limit) | Ordering a half-resolved meal |
| MEA-009 required vs bought (3) | Amounts per ingredient; `purchase_amount` naming; shared pack split | Required 20 KG vs bought 21 vs excess 1 and so on, bought > required, request keeps the required amount; `purchase_amount` is a copy of `amount` (a naming trap, recorded); shared-pack shares add up to the line (30 KG) | Showing the rounded number as the need |

Strict xfails (2):
- `test_gap_rejected_product_selection_is_recorded` (MEA-005 "selections"): single `match_ingredient` leaves the ingredient with `product_id=None` and a reason but does not record the refused product (`recipe-egg`); the batch call does (see `test_contributions_contract.py`), but the single call needs a patch from person 2.
- `test_gap_free_form_basket_for_a_dish_with_unresolved_saved_plan_is_refused` (MEA-008): a later-turn free-form plan for the same dish as an unresolved saved plan is prepared and only labelled `free_form`. The backend guard exists (`aimo.recipe_guard`, `Service.ensure_saved_plan_resolved`) but `ToolSession.prepare` (person 2) does not call it yet.

#### `tests/test_recipe_guard.py` (MEA-008) - 10 passed, 0 xfailed

Checks the guard that refuses a free-form basket for a dish whose saved recipe plan still has unresolved ingredients. Plans are inserted straight into the tables; no catalog or supplier.

| Test | Scenario | Asserts | Catches |
| --- | --- | --- | --- |
| Refusal | Saved "Spaghetti Carbonara" with two unresolved ingredients; same title asked again | `RECIPE_PLAN_UNRESOLVED` (422), the message names the two unresolved items, not the matched one, and tells the agent to use `match_ingredient` or wait for a new customer message | An agent skipping the unfinished dish |
| Matching rules (4) | Different case/whitespace; all matched; `proposed` status; a different title | Title compare ignores case and spacing; only `matched` counts as done; unrelated titles pass | Over- or under-blocking |
| Visibility (2) | Another buyer's plan, a sibling agent's plan; a locked (already prepared) plan | Not seen; not counted | Cross-buyer blocking |
| Age and conversation (2) | Without a conversation, 25 h vs 1 h old; with conversations, other turns | Outside a conversation only plans under 24 h count; inside one, only that conversation's plans count however old, and a different conversation's plan does not | Stale or unrelated plans blocking |
| Service method | Through `Service` | Same refusal; unrelated dish returns `None` | The guard existing but not exposed |

Note: this passes on the backend only. Whether the agent tool calls the guard is the open gap above.

#### `tests/test_unit_priority.py` (BAS-009, catalog part) - 29 passed, 0 xfailed

Pure tests of `combine_in_priority_unit`: when one product is requested in two units, merge them into one unit by the configured order (KG, then L, then pieces), using only catalog evidence.

| Test | Scenario | Asserts | Catches |
| --- | --- | --- | --- |
| Priority (7) | KG+L, KG+pieces, L+pieces, L+box, only pieces, two piece units, single item | KG wins (2 KG + 3 L = 3.5 KG); L beats pieces; a box converts through its size (1 KI + 5 L = 25 L); among piece units the sales unit wins, else alphabetical, whatever the request order | Order-dependent unit choice |
| Needs evidence (3) | Product with no known weight; name says 1 L but volume unverified; kg-based product | No kg from pieces without known weight; names and hints are never evidence; kg-based product converts by its own factors | Guessing conversions |
| Exactness (4) | Thirds (1 KG = 1/3 ST); 4 decimals; 5 decimals; repeating decimal; 15 digits | Exact; a total needing more than 4 decimals or 14 digits is `unknown` with a reason, not rounded | Float or rounding errors |
| Unknown cases (5) | Unconvertible item; conflicting measure or product; missing sales unit factor; empty, zero or negative request | The whole result is `unknown`: no amount, no unit, a reason | A partial answer from bad input |
| Configuration and order (4 incl. 2 permutation cases) | Change `UNIT_PRIORITY`; permute items; inputs inspected | Priority is the constant `("KG", "L")` and changing it changes the result; result is the same for any order; inputs untouched | Hidden hard-coded order |
| Pieces and unchanged `quantity()` (6) | Reviewed piece count (PR #38); 3 `quantity()` cases; unknown and conflicting results | Piece unit converts only with count evidence; the existing `quantity()` output is identical | The new helper breaking the old path |

### 9.3 WS-C: policy, identity and isolation (new files)

Counts below are from one run per file on the worktree against the test database (`passed / xfailed`). All use fixture commerce and the 10-product fixture catalog; no live supplier. Only 2 of the 15 files contain strict xfails (`test_additive_migrations.py`: 4 cases, `test_policy_rules.py`: 1). A strict xfail is a known gap: it is expected to fail today and will turn red the moment the gap is closed, so it is not a pass.

`tests/wsc_support.py` is a helper, not a test file. It provides `add_second_buyer()` (a full second buyer "other" with its own policy, approver with a password, legacy agent and internal agent), `counts()` (row counts of 12 history and working tables, used to prove a refused call wrote nothing) and `login_headers()` (real cookie sign-in returning the Origin and CSRF headers).

#### `test_policy_rules.py` (JNP3-POL-002/003/004/006/009; 55 passed, 1 xfailed)

Drives `evaluate_purchase` (the pure policy function) through a grid of invented rules, requests and priced snapshots, then repeats the key rules through `Service` (prepare, commit, audit log). It proves each duty in the policy words produces a named reason code and the right outcome; it does not prove the reasons are phrased well or that the real catalog hits them.

| Test | Scenario | Asserts | Catches |
| --- | --- | --- | --- |
| Each policy duty has a reason code (15 cases) | Unlisted destination; hard budget below total; currency missing or outside authority; substitution forbidden, declared or needing approval; overbuy forbidden, refused by the request or needing approval; no approver covers the total; approver lacks the exception; empty rules; no approver; approver in another currency | The expected code is present, every such reason has the expected severity, and the outcome is denied / needs_resolution / approval_required as listed | A rule silently dropped or mapped to the wrong outcome |
| Dietary reasons and clean request | Snapshot already carries `unresolved` or `denied` dietary reasons; a request with nothing wrong | Unresolved gives needs_resolution, denied gives denied, both gives denied; the clean request is exactly `ready_to_commit` with no reasons | The policy dropping dietary evidence it was given |
| Four outcomes, fixed precedence | 3x3x2x4x3x2 grid of scope, substitution rule, outside product, total, injected reason severity, request flag | Outcome is always one of the four and equals denied > needs_resolution > approval_required > ready, computed independently in the test | An outcome outside the four or a precedence slip |
| Missing scope blocks (7 tests) | Standing product list absent or `None`, with each substitution rule and request flag; also `[]` | `PRODUCT_SCOPE_UNCONFIGURED`, never ready, severity `unresolved`, no approver exception can repair it. `[]` counts as configured and approves nothing | A buyer with no configured list auto-ordering anything |
| Outside-scope products (7 tests) | Product outside the list, declared substitution inside the list, `allowed` rule, request refusing substitution | Forbidden denies; requires_approval needs the `substitution` exception; `allowed` passes but leaves reason `SUBSTITUTION_ALLOWED_BY_POLICY` (owner decision 2026-11-14) only on the outside line; a request refusal still denies | Substitutions slipping through unrecorded |
| Unresolved or denied snapshot reasons (13 cases) and unknown total (3 tests) | Each of 13 snapshot reason codes; total `None`; total `None` plus an existing total reason; total `None` plus a bad destination | Never ready; total `None` gives needs_resolution once (no duplicate reason); a denial is not hidden | Readiness with a missing fact |
| Service level (5 tests) | Missing scope with each rule; `allowed` substitution; `requires_approval` substitution through a real proposal | Missing scope gives `COMMIT_BLOCKED` and zero orders; allowed commits (mock receipt) and the reason is in the stored `proposal_prepared` audit event; requires_approval needs customer confirmation, then approval, then commits | The pure rules not being wired into the real flow |

POL-008 (`test_unconfirmed_assumption_never_loosens_hard_limits`, formerly a strict xfail) now passes: `evaluate_purchase` takes a server-only `constraints` record (see `docs/internal-agent.md`). Extra pure-function cases follow it in `test_policy_rules.py`; transport, revision, commit re-read and the model-cannot-set-it checks are in `test_constraints_transport.py`. Nothing yet fills the record in production (person 1, #75).

#### `test_spend_authority.py` (JNP3-POL-013, POL-014; 64 passed)

Checks the spend model after owner decision Q-35: only human approvers have a maximum, the agent has no spend authority, there is no autonomous limit, and the request's hard budget still denies. Pure policy cases, then Service cases with the demo agent's stored authority changed. It does not test the browser confirm button.

| Test | Scenario | Asserts | Catches |
| --- | --- | --- | --- |
| Totals vs approver maximum | Totals 1.00 to 5000.00, 5000.01 and 100000.00, boundary at exactly the maximum and one cent above | At or below: ready, no reasons. Above every maximum: needs_resolution with only `NO_ELIGIBLE_APPROVER`. Never `AUTONOMOUS_LIMIT_EXCEEDED` or a `spend` exception | Off-by-one at the approver limit; the old spend model coming back |
| Approver set (POL-014) | Zero approvers, zero or missing maximum, two approvers (small and large), wrong currency, unknown total, denial plus no approver | Only a covering active approver counts; denial still wins; unknown total adds no reason | Orders ready with nobody able to approve them |
| Hard budget | Budget equal to total, one cent below, none, 0.01 or 9.99 with no approver | Equal passes; one cent over is denied and wins over a missing approver | A budget limit loosened by the removal of the autonomous limit |
| Agent authority is irrelevant | `evaluate_purchase` signature; demo agent's stored authority set to `{}` and three legacy shapes | No authority parameter; identical outcome, reasons and next action for every shape; the agent commits after customer confirmation whatever is stored | Hidden dependence on agent limits |
| Approver maximum at Service level | Approver maximum 0.01, only approver inactive, small plus large approver, wrong currency, none at all, boundary equal or one cent over | needs_resolution with `NO_ELIGIBLE_APPROVER` at prepare time; boundary commits, one cent over blocks commit | The maximum only working in the pure function |
| Confirmation by a human below the total | Maximum lowered to 0.01 after prepare, versus exactly equal to the total | `APPROVAL_SCOPE` 403 and no order; equal total gives the mock receipt | A buyer confirming beyond their own maximum |
| Legacy key tolerance | Policy with old `autonomous_limit`, approver with old `spend` exception, unknown keys | Old keys validate and are dropped; any other unknown key or exception value is rejected; legacy and new-shape policies give the same Service outcome | Old databases breaking; typos in rules accepted |

No strict xfails. (The docstring says so and the run shows 64 passed.)

#### `test_agent_cannot_purchase.py` (owner decision Q-14; 14 passed)

Proves the assistant's tool list has no way to confirm, approve or commit. It reads the code (AST) as well as calling it; it does not run the language model.

| Test | Scenario | Asserts | Catches |
| --- | --- | --- | --- |
| Registry contents | Build a `ToolSession` with a recording stand-in for `Service` | Registered names are exactly the 7 read/prepare tools, 5 recipe tools and `publish_meal_plan`; none contains confirm/approve/commit/decide; advertised definitions equal the registry | A purchasing tool added to the model's list |
| Invoke purchasing names (9 cases) | `invoke` with `commit_order`, `confirm`, `record_human_decision`, `set_product_scope`, `update_purchase_policy`, `withdraw_meal_authorization` and others | `TOOL_NOT_ALLOWED` 422 and no Service call | Calling a verb by name |
| Source scans (1 + 3 cases) | Parse `agent_tools.py`; parse `agent.py`, `agent_tools.py`, `agent_provider.py` | Handlers call only the allowed Service methods; none of the files mentions a purchasing function name | A hidden call path |

#### `test_agent_tool_verbs.py` (JNP3-TCT-007; 74 passed)

Closes gaps left by the file above: what the model is actually sent, hidden paths into `Service`, name tricks and smuggled arguments.

| Test | Scenario | Asserts | Catches |
| --- | --- | --- | --- |
| Provider-facing schemas (4 tests) | Walk every property of every tool schema; tool names; descriptions; request models | No field named approve/confirm/decision/actor_id/buyer_id/idempotency_key/rules/limit/scope etc.; no verb in a tool name; descriptions mentioning authority deny it; every request model forbids extra fields | A model being offered a way to set identity or policy |
| Runner/provider wiring (1 test) | AST of `agent.py` and `agent_provider.py` | The only tool list sent is `session.definitions`; no tool name or schema literal in the provider | A second tool list bypassing the registry |
| No hidden route (2 tests) | Every `ToolSession` method that touches `self.service`; source of `invoke` | Only registered handlers do, and only allowed methods; `invoke` resolves names only via the registry (no `getattr`/`eval`) | Dynamic dispatch |
| Every other operation refused (1 test) | All public `Service` and `approval_workflow` functions not in the registry, derived from the code | Each gives `TOOL_NOT_ALLOWED` 422, zero Service calls; a future method is covered automatically | A newly added operation reachable by name |
| Name variants (22 cases + 1) | Case changes, whitespace, NUL, `functions.`/`tools.` prefixes, `a;b`, `edit_policy`, `__init__`, `registry`, empty; non-string names | All refused with `TOOL_NOT_ALLOWED` (non-strings raise) | Name-matching tricks |
| Smuggled arguments (42 cases) | Six read tools each given an extra `commit`, `confirm`, `approve`, `decision`, `policy`, `actor_id` or `buyer_id` | `INVALID_TOOL_ARGUMENTS` before any Service call | A model passing a decision as an argument |
| Real prepare (1 test) | Real `prepare_order` through the tool with the demo agent | One new proposal; orders, confirmations, idempotency and policies unchanged; no approved approval; policy version unchanged; no audit event containing confirm/commit/approved/policy | Prepare having purchasing side effects |

#### `test_in_process_tools.py` (JNP3-TCT-006; 13 passed)

Evidence that the tools are plain Python calls inside the app, not a separate tool server. Static scans plus a run with the network blocked. It proves the tool path makes no HTTP call; it does not prove how the app is deployed.

| Test | Scenario | Asserts | Catches |
| --- | --- | --- | --- |
| Static scans (8 tests) | AST/string scans of `agent_tools.py`, modules it imports, `agent.py`, `agent_provider.py`, all `src/aimo/*.py`, `worker.py` | No HTTP client or server import and no URL strings in the tool module; `self.service` used only as a direct method call; the runner's HTTP client goes only to the provider and guardrail classifier; only `api.py`, `cli.py`, `worker.py` import a server framework; the worker's only listener serves `/health/live` and `/health/ready` | A tool endpoint or client being added |
| Network guard control (1 test) | Block socket connect, `create_connection`, `getaddrinfo` | The guard really raises | The next two tests passing vacuously |
| Tools with the network blocked (2 tests) | A stub Service; the real Service with fixture upstream (database access is outside Python sockets) | `search_products`, `get_purchase_policy`, `check_price_and_availability` work and attempt no connection | A hidden network hop |
| Handlers and routes (2 tests) | Registry handlers; API route table and OpenAPI | Handlers are plain methods of `aimo.agent_tools`; the API has no mount or route containing tool/mcp/agent/rpc/invoke, no tool-name path segment | A tool exposed over HTTP |

#### `test_no_mcp.py` (JNP3-IDN-005, IDN-003; 7 passed)

| Test | Scenario | Asserts | Catches |
| --- | --- | --- | --- |
| No MCP in code and packages (3 tests) | AST of every `src` import; `pyproject.toml` and `uv.lock`; import the app modules and inspect `sys.modules` | No module or package with "mcp" in its name | An MCP library creeping back |
| No MCP or agent route (1 test) | App routes and OpenAPI | No path starting `/mcp` or `/api/agent` | A revived external agent API |
| Bearer token ignored (1 test) | Insert an agent whose stored credential is the digest of a token; call every non-public route with and without `Authorization: Bearer` | Same status with and without, never 2xx, never 5xx; login with the token or its digest gives 401 `LOGIN_FAILED`; `/mcp` and `/api/agent/*` give 404; no rows written | The removed bearer scheme still authenticating |
| Agent identities cannot sign in (2 cases) | `demo-agent` and an external agent via `/api/login` | 401 | Agent logging in as a human |

#### `test_provisioning.py` (JNP3-IDN-002, Draft, Q-35; 13 passed)

Checks what `seed()` creates: agent identities with empty authority, policies with no autonomous limit, approver keeps `max_gross` 5000.00 and exceptions substitution and overbuy only, agent credentials are non-usable `!` placeholders, exactly one internal agent mapped to the demo buyer. Also: `seed()` twice changes nothing; `seed()` does not overwrite an existing agent row (a custom authority survives); a legacy-shaped database (old autonomous limits and a `spend` exception) still builds policy context for every role and still prepares a purchase. It does not test a per-buyer provisioning command, which does not exist yet.

#### `test_revoked_identity.py` (JNP3-SEC-003; 21 passed)

A deactivated identity, or one whose role changed, must be refused everywhere, must write nothing (row counts equal) and must never reach the supplier connector (made to raise if called).

| Test | Scenario | Asserts | Catches |
| --- | --- | --- | --- |
| Revoked agent, every tool (16 cases) | 8 tools (search, get product, policy, price lookup, prepare, get proposal, get order, commit) x inactive or role-changed | `AUTHORITY_REVOKED` 403, no writes | A tool that skips the identity check |
| Internal agent (2 tests) | Internal agent deactivated | Turn cannot start (`AGENT_NOT_CONFIGURED` 503); customer confirm gives `AUTHORITY_REVOKED` and no order | A stale internal agent buying |
| Revoked human (2 cases) | 11 entry points (confirm, decision, lists, details, conversations, enqueue) | `AUTHORITY_REVOKED` 403, or `NOT_FOUND` 404 when the lookup comes first (no data returned) | Revoked buyers keeping access |
| Live cookie (1 test) | Sign in, deactivate the buyer, call the HTTP API | 401 on session, lists and confirm; no writes | A session outliving the account |

#### `test_isolation.py` (JNP3-SEC-001/002; 4 passed)

Buyer A (demo-hotel) has a conversation, a confirmed order and a pending approval; buyer B ("other") is a full second buyer. B's human, legacy agent and internal agent each try to read or act on A's records.

| Test | Scenario | Asserts | Catches |
| --- | --- | --- | --- |
| Cross-buyer access | Service and workflow calls: get proposal/order, commit, approval detail and decision, conversation detail and enqueue, replaying A's confirmation | Every one gives `NOT_FOUND` 404; B's lists are empty; counts unchanged | A missing buyer filter on any query |
| Same prepare key per buyer | B prepares the same request and key as A | A separate proposal for B, and repeating returns B's | Idempotency leaking across buyers |
| Forged `buyer_id` | Identities edited to name the other buyer | `AUTHORITY_REVOKED` 403 or `NOT_FOUND` 404, no writes | Trusting a caller-supplied buyer id |
| Over HTTP | B signs in with a real cookie | Own session only, empty lists, A's ids give 404 on read, message, confirm and decision | The same leaks at the API layer |

#### `test_meal_authorization.py` (JNP3-POL-010; 19 passed)

A per-meal authorization is the customer's approval (or stored confirmation) of one proposal revision. The tests cover granting, withdrawal (a customer-only Service operation), expiry and the append-only record.

| Test | Scenario | Asserts | Catches |
| --- | --- | --- | --- |
| Granting (2 tests) | Agent prepares; customer approves | `not_granted` until the customer approves; then `active` for revision 1, granted by the buyer, expiring with the proposal | The agent granting itself |
| Withdrawal blocks buying (4 tests) | Withdraw after approval, before approval, on a ready basket, after a confirmation whose commit failed | Commit gives `AUTHORIZATION_WITHDRAWN`, zero orders, the approval becomes `superseded`, next action is a fresh proposal, approving a withdrawn one gives `DECISION_CONFLICT`, a fresh proposal needs a fresh decision | A withdrawn meal still orderable |
| Idempotent and audited (1) | Withdraw twice with different reasons | One row, one audit event, first reason kept | Duplicate records |
| By recipe plan (2) | Plan linked to a proposal; plan with none | Finds the proposal; none gives `not_granted` and no row | Wrong target lookup |
| Committed and expired (2) | Withdraw after the mock order; clock moved forward | `ALREADY_COMMITTED`; status `expired` with no withdrawal | Rewriting history |
| Who may withdraw (4) | Agent, internal agent, other buyer, revoked buyer; request validation | Agents get `FORBIDDEN`; other buyer `NOT_FOUND`/`FORBIDDEN`; revoked `AUTHORITY_REVOKED`; target and reason required | Agent or stranger withdrawing |
| Invariants (4) | Standing list; append-only; not an agent tool; migration 010 | Policy rows unchanged; UPDATE/DELETE on withdrawals raises; tool refused; migration registered with expected columns | Withdrawal editing the product list |

#### `test_confirm_keeps_policy.py` (JNP3-POL-005; 3 passed)

Confirming a basket must leave `buyers.current_policy` and all `policies` rows untouched. Cases: a normal confirm, its replay (same receipt) and a second confirm (refused); a confirmed outside-scope basket (`464398` stays off the list); a denied basket refused with `COMMIT_BLOCKED`. Catches "confirm adds the product to the standing list". Does not cover withdrawal (see above).

#### `test_historical_actors.py` (JNP3-IDN-004; 4 passed)

Actor ids (`demo-agent`, `buyer`) recorded in audit, proposals and approvals still resolve to identity rows after revocation, `migrate()` and `seed()`; the revoked agent stays inactive with a `!` placeholder credential and the proposal history still resolves. Deleting a referenced identity (2 cases) fails with a foreign-key error. The internal agent keeps a `!internal-no-bearer-login` credential. Catches history pointing at deleted identities.

#### `test_runtime_truncate.py` (PER-002; 10 passed)

Creates a throwaway restricted role inside a rolled-back transaction using the real `configure_runtime_role` (twice, as release jobs do). Proves it cannot TRUNCATE the six history tables plus `buyers` and `identities` (3 statement forms each, 8 cases); that no ownership, membership, PUBLIC or default-ACL route grants TRUNCATE; and, as a positive control, that an explicit grant does make TRUNCATE work. Skips if the database user cannot create roles (it did not skip here). Proves the privilege is absent for that role; does not prove the deployed database role was built this way, or protect against the schema owner.

#### `test_unsupported_requirements.py` (JNP3-POL-009, unsupported half; 9 passed)

A requirement the catalog cannot check (for example gluten-free) arrives as `Requirements.unsupported` and becomes an `unresolved` `REQUIREMENT_UNSUPPORTED` reason per entry. Pure cases: none or empty list is ready; one entry gives needs_resolution with the entry named and no approver exception; two entries give two reasons; a denial still wins; the list is bounded (at most 10 entries, 1 to 80 characters) and an unknown key such as `gluten_free` is still rejected. Service cases: such a prepare has no approval, next action is revise the request, and commit gives `COMMIT_BLOCKED` even after customer confirmation; without the field nothing changes. Does not check how the assistant fills the field.

#### `test_additive_migrations.py` (JNP3-PER-002; 55 passed, 4 xfailed)

Two layers. First, a regex scanner over every `migrations/*.sql` that flags non-additive statements; the flagged set must equal a reviewed table with a written justification, so a new risky statement fails until a person reads it. Second, live checks that the `immutable_record` trigger rejects UPDATE and DELETE on four history tables. It does not run the migrations on a populated database (that is `test_migrations.py`).

| Test | Scenario | Asserts | Catches |
| --- | --- | --- | --- |
| Scanner self-tests (21 + 13 + 1 cases) | Synthetic SQL: DROP/TRUNCATE/DELETE/RENAME/type change/UPDATE/trigger drops/disable, also inside `DO $$` bodies; additive SQL; line numbers | Every non-additive form is flagged; every additive form and comments are not; line number is true | A scanner that silently misses a form |
| Real migrations (5 tests) | Scan all files | Flagged set equals the 9 reviewed entries (e.g. 004 sets historical turn state, 006 and 009 and 011 backfill new columns); none is DROP TABLE/COLUMN, TRUNCATE, DELETE, RENAME or trigger/function change; none touches the four immutable tables; `INSERT` only into `identities` and `internal_agents`, only in 003 | An unreviewed destructive migration |
| Trigger definitions and catalog (2) | Parse trigger definitions; read `pg_trigger` | Four tables guarded (plus `orders` in 008 and new tables in later files); function defined only in 001; each guard is enabled, row-level, BEFORE, UPDATE and DELETE, not INSERT | Guard removed or weakened |
| Ledger (1) | `schema_migrations` | Every packaged file is recorded under its original name | A renamed migration |
| Live immutability (8 + 4 cases) | Real proposal, audit event, policy, confirmation; UPDATE and DELETE on each table; then an append | Each rewrite raises "immutable history" and the table is unchanged; appending still works | A trigger that blocks too much or too little |

STRICT XFAIL (4 cases of `test_immutable_tables_also_reject_truncate`, one per table) stands for JNP3-PER-002 (history cannot be erased). It fails today because the guard is a row-level UPDATE/DELETE trigger, which PostgreSQL does not fire for TRUNCATE; the runtime role lacks the TRUNCATE privilege (covered by `test_runtime_truncate.py`) but the schema owner can still truncate.

### 9.4 WS-D: proposal, confirmation and receipt

Every test here confirms through `conversations.confirm` (the browser route's logic) or records a confirmation with the `confirm_terms` fixture in `tests/conftest.py`. Fixture prices, mock orders ("Accepted by demo order service"); nothing here proves anything about the live supplier. The internal agent has a zero autonomous limit, so its baskets are always `approval_required`; `ready_to_commit` cases use the retained `demo-agent`.

#### `tests/test_confirmation_contract.py` (JNP3-CNF-002, 003, 004, 006, 008, 009, 011, 012, 013, 016, 019, PRP-005): 19 passed, 1 strict xfail
| Theme | Scenario | Asserts | Catches |
| --- | --- | --- | --- |
| Every agent role needs a confirmation | The retained agent commits a `ready_to_commit` and an `approval_required` proposal; a human approval decision alone is tried; then the buyer confirms | `CUSTOMER_CONFIRMATION_REQUIRED` until a confirmation is recorded for that exact revision; the agent's replay then returns the receipt | a commit path with no human in it |
| Binding | Confirm, then read the stored row; a forged buyer id; revisions 2 and 3 that keep the same fingerprint (authority-only changes); a price change | the row carries buyer, proposal, revision, actor, key and the revision's fingerprint; it cannot be updated or deleted; a confirmation of one revision never authorizes a later one | a confirmation reused on other terms. Only the identical-terms case catches a lookup that ignores the revision |
| One click, one set of terms | Confirm an `approval_required` proposal | the approval row and the confirmation row share proposal, revision, fingerprint and actor | an exception approval recorded against other terms |
| Re-fetch | Commit a proposal with a deposit product | exactly one supplier lookup, for the proposal's product plus its deposit material, no other id | extra or missing products in the re-check |
| Saved receipt | Repeat the same key | equal receipt, zero supplier lookups. `prior_result(..., any_key=True)` finds the order of the same revision for any key, refuses a key used for other terms, and returns nothing for another revision | a repeat that calls the supplier again |
| No lock across a supplier call | While the supplier is called (prepare and commit), another session locks buyers, identities, proposals, approvals | locks are free within 300 ms and no session is "idle in transaction" | a transaction held across a network wait. Mutation-checked |
| No LLM on the commit path | A fresh interpreter imports the workflow modules; a confirmation runs with every HTTP send patched to fail | no `aimo.agent*` module loaded; the receipt is still issued | an agent or provider call in the commit path |
| Outcome versus confirmation | Confirm a `ready_to_commit` and an `approval_required` proposal | the stored `policy_outcome` is unchanged; the confirmation is a separate table with no shared columns | the two states stored in one field |
| Evidence per line | A two-line proposal | each line has product id, name, quantity, net, gross, tax, product evidence and commercial evidence with price source and expiry | a line with a missing price or product fact |
| Concurrency | 8 threads with one key; 6 threads with six keys; a repricing that lands while the first caller waits on the supplier | one order, one confirmation; the rest get the receipt or `DECISION_CLOSED`/`ALREADY_COMMITTED`; the first caller gets `STALE_REVISION` and no order exists for a revision it did not confirm | double orders and an order on unseen terms |

Strict xfail: `test_repeated_confirmation_with_another_key_returns_the_saved_receipt` (CNF-011 route half): a second key still gets `DECISION_CLOSED` from `conversations.confirm`; it needs one line in that file (patch text in the evidence folder). It turns red the moment the line is applied, which is the signal to remove the mark.

#### `tests/test_orders_immutable.py` (CNF-017, CNF-020; migration 008): 4 passed
Update and delete of an order are rejected ("immutable history"); a normal commit and the receipt replay still work and `proposals.order_id` stays mutable; `orders` carries the same guard function as the other history tables; the migration file can be applied again to a populated database without changing a row. A row trigger does nothing on an empty table and does not fire on TRUNCATE, so a pass proves protection of stored orders against the application, not against someone who owns the table.

#### `tests/test_proposal_revisions_contract.py` (PRP-003, PRP-007): 7 passed
A supplier price change or an availability change at commit time gives revision 2 of the same proposal (the old revision stays readable, no order); a changed quantity under a new key is a different proposal; under the same key it is `IDEMPOTENCY_CONFLICT`. Confirming the revision that contains a substitute accepts it: the substitute line, the `substitution` exception, the confirmation, the approval and the order bind one revision and fingerprint, and a repriced revision 2 needs its own confirmation. It proves nothing about live prices.

#### `tests/test_receipt_and_expiry_contract.py` (CNF-014, 015, 017, 018, PRP-002): 7 passed, 1 strict xfail
An expired proposal is refused on the route (`DECISION_CLOSED`, 409) and on commit (`PROPOSAL_EXPIRED`) with no supplier call and nothing written; the expiry comes from `PROPOSAL_TTL_SECONDS`. `denied` and `needs_resolution` stay `COMMIT_BLOCKED` on both paths. Every receipt carries the label "Accepted by demo order service" and both false flags, in `orders.receipt`, `get_order` and the audit event; three orders and their audit history are still readable 400 days later. Strict xfail: `test_proposal_response_carries_every_required_field` (PRP-002): the fingerprint is stored but not returned in `ProposalResponse`.

#### `tests/test_refresh_contract.py` (CNF-008, 010, 011, 012, PRP-004): 5 passed
On PR #38's in-place refresh of an expired recipe proposal: the old confirmation and approval do not attach to revision 2 (replaying the old key is `IDEMPOTENCY_CONFLICT`); after an order exists a refresh is `RECIPE_PLAN_LOCKED` and the receipt is unchanged; two preparation keys can point at one proposal and each stays idempotent (migration 007 keeps the primary key); a recipe-backed prepare holds no buyer or plan lock during the supplier call; and with a real 2.3 s expiry (no patched clock) the old confirmation still stays on revision 1. It imports the recipe fixtures from `tests/test_recipes.py`.

#### `tests/test_lock_order_and_login_contract.py` (CNF-005, CNF-003): 3 passed
Every row-locking statement across a prepare, a decision, a confirmation and a commit is recorded; each purchasing transaction locks the buyer, then identities, then the proposal. Agent identities get `LOGIN_FAILED` at `/api/login`; a session row forged for an agent authenticates nothing (the same forgery works for the real approver, so the check is meaningful).

#### `tests/test_requirements_wire_shape.py` (integration of WS-A filters and WS-C `unsupported`): 3 passed
`Requirements` omits `free_from`, `country_of_origin` and `unsupported` from the stored wire shape when empty and includes each when used, so stored request fingerprints from before these fields existed do not change. Local models only; no database use.

#### `tests/test_unfinished_cleanup_contract.py` (CNF-021): 1 passed, 1 strict xfail
A guard that fails if a new table starts referencing `proposals` or `proposal_revisions` without the cleanup design covering it (and shows history deletes are rejected today). Strict xfail: the proposed `purge_unfinished_proposals`: nothing removed inside the 30-day period, afterwards unfinished proposals and approvals disappear with their rows and one `purged_proposals` row each, while an ordered proposal, its audit history and the immutable orders stay. Nothing is built yet.

#### Q-44 / BAS-009 wiring (`tests/test_agent.py`, `tests/test_basket_contract.py`)

- `test_q44_basket_mismatch_says_exactly_what_to_send`: the plan needs 20.5 KG of one product, the line says 20 KG; `prepare_order` returns `MEAL_BASKET_MISMATCH` whose message names "pasta 20.5 KG" and whose `details` list the required lines, the missing and unexpected ones and the wrong amount or unit; no prepare call is made.
- `test_q44_model_sees_the_details_in_the_tool_error`: the same refusal reaches the model through `agent.run_turn` with `error.details`.
- `test_one_product_in_two_units_can_be_prepared` (BAS-002): milk 5 L plus 1 KI is prepared as one 25 L line.
