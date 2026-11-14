# Implementation validation — 14 November 2026

Implemented on `codex/valio-aimo-mvp` in an isolated worktree, originally based on main `76296c1`. The original checkout remained clean on `codex/valio-aimo-plan` during implementation. PR #2 was closed **without merging**; this implementation includes the agreed brief while preserving PR #3's reference work. PR #4 now targets the shared integration branch, `develop`.

## PR #4 review fixes — 14 November 2026

Fixed the four findings against `6acfe89`, starting from the current PR head `cd16b09`:

- A changed effective authorization decision creates a new immutable revision in the locked commit transaction, even when prices and buyer policy version are unchanged. The €17 purchase/€10 agent-limit regression creates one pending buyer approval; without an eligible approver it becomes `needs_resolution`. Reads flag stale authority instead of recommending commitment.
- A historical approval stays superseded and carries no accepted order ID/status belonging to another revision. Its authenticated current-purchase link works both when the new revision needs approval and when it can commit autonomously. Direct links also survive sign-in.
- `/docs` has a fresh script nonce and documentation-specific CSP. Swagger assets still come from jsDelivr; the buyer UI keeps its original restrictive policy.
- All eight HTTP/MCP operations share typed output contracts. Commit preserves the flat receipt/revised-proposal alternatives, distinguished by `status`. OpenAPI and browser types were regenerated.

Checks executed on these fixes:

| Check | Actual result |
| --- | --- |
| Backend regression suite | **53 passed** against PostgreSQL/pgvector in isolated `aimo_review_test`, including all eight operations over HTTP and MCP, both commit responses, authority changes, historical/current terms, cross-buyer access and nonce/CSP scope. |
| Production frontend build; Ruff; `git diff --check` | Passed. |
| Chromium/Playwright | **6 passed** against the local server and compiled frontend, using the separate `aimo_review_browser` database. New tests cover the actual persisted €1,700 → €1,870 revision flow, links after login/relogin, and rendered Swagger operations with zero CSP violations. The four original browser flows also passed. Repeated development runs hit the intended login limit; only the isolated test database's counters were reset before the final run. |
| Official MCP SDK | All eight tools invoked over authenticated stateless HTTP; mock commitment and identical receipt on retry passed. |
| New product response model | Validated all **17,546 existing normalized catalog products**, with zero validation errors. No reingestion, new embeddings or catalog export. |

These fixes do not add services, migrations or dependencies. The Docker image was not rebuilt for this review pass. Live supplier integration and Kubernetes deployment remain unverified; the earlier initial-image checks below are historical results, not a claim of a fresh deployment.

## Initial MVP checks

| Check | Actual result |
| --- | --- |
| `uv run ruff check src tests scripts` | Passed. |
| `uv run pytest -q --disable-warnings` | **47 passed**, using a real PostgreSQL/pgvector instance and an isolated `aimo_test` database. No SQLite substitution. |
| `npm ci --prefix frontend`; `npm run build --prefix frontend` | Passed, including TypeScript compilation and Vite production assets. Python-generated OpenAPI/TypeScript types regenerated. |
| `npm run test --prefix frontend` | **4 browser tests passed** against the running application: independent inbox/login/approval/agent resume and retry; inbox error state and mobile login; conflicting decisions in two tabs; refresh paused while hidden. Desktop/mobile screenshots were inspected. |
| `uv run python scripts/mcp_smoke.py` | Official SDK initialized stateless authenticated HTTP, discovered **all eight tools**, searched, read policy, prepared and committed an autonomous purchase, retrieved the order and received an identical receipt on retry. |
| `uv run python scripts/demo.py` | Demonstrated autonomous €17.00 purchase and retry, denied hard budget, unresolved 1,000 L shortage, and €1,700 mission pending in the independent inbox. Commerce is explicitly fixture data; order acceptance is mock. |
| `scripts/restart_smoke.py --container aimo-mvp-verify --base-url http://localhost:8001` | Actual container restart between buyer approval and agent commitment: browser session and approval survived, agent resumed, one mock order and identical retry. Runtime UID 10001, no Node executable, CPU-only PyTorch. |
| Full local catalog import | **17,546 products** published using actual pinned multilingual E5 embeddings. No source catalog copied into Git. |
| Identical full import rerun | **0 new / 17,546 reused embeddings**; active generation updated atomically. |
| `scripts/verify_catalog.py` | **7 actual source products verified**, including dimensional/packaging cases and both allergen conflicts. `460035` is also variable-weight. |
| `scripts/evaluate_search.py` | Thirty curated Finnish/English/identifier/exclusion cases; results below and in `search-evaluation.json`. |
| Docker image | Multi-stage image built successfully with compiled frontend, CPU-only Python dependencies and pinned model cache. Read-only-root container at localhost:8001 passed readiness with offline model loading, HTML frontend routes and JSON 404 separation, all four browser tests, the eight-tool official MCP flow and the HTTP demo. |
| Deployment YAML | Compose and Kubernetes YAML parsed successfully. No Kubernetes apply or live deployment performed. |
| `git diff --check`; credential scan | Passed. Configured private credential values absent from every tracked file and frontend bundle. Raw catalog, `.env`, weights and generated test artifacts are not tracked. |
| `npm audit --omit=dev` | Reported zero production-dependency vulnerabilities at verification time. |

Backend checks include gross spending boundaries, hard purchase budgets, all four outcomes, supported dietary evidence, whole-unit/lot rounding, variable weight, deposit totals/units, missing price/validity, tax mismatch, missing/duplicate supplier IDs, date/customer mismatch, unknown/sentinel stock, unavailable schedules, unit mismatch, expired cutoff, changed price/stock, seed preservation, policy version changes, approver amount/exception limits, identity revocation, rejection/expiry, strict input schemas, CSRF/origin protection, login rate limiting, account isolation, completed retry without upstream, and persistent receipt recovery through a new service instance. Competing operations use separate connections/threads against PostgreSQL. Eight same-key commits produce one order; different keys and competing approve/reject/commit requests preserve one legal outcome. Failed imports leave the active generation intact; unchanged/metadata-only texts reuse embeddings.

## Retrieval results and limits

Snapshot SHA-256: `50651aae31ca842112afdc16fcce92f9858d7f5d05e9928a3748aef16b22ea02`. Model: `intfloat/multilingual-e5-small` at `614241f622f53c4eeff9890bdc4f31cfecc418b3`, CPU, normalized 384 dimensions, `query:`/`passage:` prefixes.

| Strategy | Top-one relevant / 30 | Top-five hit or correct exclusion / 30 | Supported constraint violations | Warm median latency |
| --- | ---: | ---: | ---: | ---: |
| Keyword | 20 | 21 | 0 | 9.5 ms |
| Semantic | 21 | 26 | 0 | 76.5 ms |
| Hybrid RRF | 21 | 26 | 0 | 77.2 ms |

Six cases are exact identifiers, 21 descriptive queries, and three exact-ID dietary exclusions. Hybrid descriptive top-five is **17/21**. Labels are curated and not exhaustive; this is not a held-out benchmark or a claim that this is the best model. The first semantic query including model load took about **4.5 seconds**. HNSW iterative scanning is enabled so generation/dietary filters do not prematurely exhaust the candidate list.

Broad English milk queries can rank flavored drinks, coffee products or sweets too highly. The explicit mandatory filters are only lactose-free and milk-free. Unsupported structured filters are rejected. Discovery returns candidates and evidence; semantic relevance is never treated as dietary, physical-quantity or fulfillment proof. Agents must inspect the shortlist and choose explicit products. Exact identifiers excluded by requirements return no substitute result silently.

## Honest integration boundaries

- **Live sponsor price/availability integration was not authenticated in this session:** no configured API key was available in the project environment. The connector follows the supplied contract and regression fixtures, but the earlier teammate live findings remain attributed observations. A fresh natural shortage is therefore not claimed. The bounded `scripts/probe_upstream.py` is ready when credentials are supplied; no real webshop automation was attempted.
- **Every order is persistent mock acceptance.** There is no supplier order endpoint, payment, stock reservation or guarantee of fulfillment. The receipt states this explicitly. Delivery/service charges are zero only by the demo adapter's definition; production needs a complete charges/acceptance contract.
- Variable-weight settlement, unknown supplier stock, passed cutoffs, missing deposit-unit/price evidence and conflicting requirements remain unresolved. A buyer decision cannot repair them. Source price validity is conservatively required for both current order time and requested delivery date until sponsor semantics are clarified.
- Demo identity/password/bearer auth is implemented, not identity federation or MCP OAuth discovery. Seed runs are privileged and preserve existing settings. No policy-editing endpoint or autonomous approval tool exists.
- Kubernetes resources are templates for an existing environment; cluster, registry, ingress/TLS and deployment resource adequacy have not been verified. No paid infrastructure or live deployment was created.
- Existing policies/revisions/audit records are immutable by database trigger. Old catalog generations and model-cache entries are retained; retention and production operations remain an operator concern.
