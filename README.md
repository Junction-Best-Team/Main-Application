# Valio Aimo purchasing gateway

One seller-side FastAPI service exposes eight HTTP/MCP tools, serves a React buyer approval inbox, and commits **persistent mock orders**. PostgreSQL stores the catalog index, versioned buyer policy, identities, immutable proposal revisions, approvals, audit events and receipts. The buyer's purchasing agent is external.

The agreed scope is in [docs/brief.md](docs/brief.md). PR #2 was **closed without merging** before implementation; this branch starts from `main` at `76296c1`, preserves PR #3's reference documents, and implements the attached PR #2 brief. `Plan/post-mvp-plan.md` is a separate draft, not the implementation contract. See [actual validation and limitations](docs/validation.md).

[Terraform infrastructure](infra/README.md) provides the team's optional DigitalOcean Kubernetes/managed PostgreSQL stack and portable Kubernetes deployment. Provisioning is an explicit operator action.

## Working in parallel

- Start a task from the latest `develop`: `git switch develop`, then `git pull --ff-only` with a clean working tree. For an existing clone without that branch, first run `git fetch origin` and `git switch --track origin/develop`.
- Use a short task branch, for example `git switch -c otto/map-view`. Do not commit or push directly to `develop` or `main`.
- Say which feature/files you are changing. Coordinate edits to shared APIs, schemas, dependency files, and deployment configuration.
- Check the affected feature works, then open a PR into `develop`: `gh pr create --base develop`. All feature, fix, documentation, and maintenance PRs must target `develop`. Wait for the latest CI run to pass, then self-merge. Human approval is optional; request teammate review for risky authentication, database schema, or shared-interface changes.
- Keep `main` ready to demonstrate. Promote a tested snapshot with a release PR from `develop` to `main` only when a release is explicitly requested. Avoid force pushes to shared branches and preserve teammates' uncommitted work.
- Use a separate checkout/worktree and branch for each concurrent agent on the same machine.

## Lightweight CI

GitHub Actions runs on PRs into `develop` and `main`, and pushes to either branch:

- Python lint: `ruff check src tests scripts`.
- Backend regression tests: `pytest -q` against temporary PostgreSQL/pgvector, using fixture embeddings and supplier responses. Test dependencies come from `uv.lock`; the unused ML stack is pruned to keep installation small.
- Frontend TypeScript checks and production build: `npm ci` then `npm run build` in `frontend`.
- Terraform formatting, validation, mocked plan tests, helper tests and ingress chart rendering when `infra/` or either CI workflow changes.

Backend and frontend jobs run in parallel, dependency downloads are cached, and a new commit cancels outdated PR/develop runs. Main releases are serialized. Components are explicitly skipped only while their application code has not been added; incomplete manifests fail the workflow. No model weights, full catalog imports, Docker builds, browser tests, production credentials, or deployments are needed for PR validation. Run broader demo/browser checks locally when the change warrants them.

The always-present `CI gate` requires successful detection and every applicable application/Terraform check; it accepts a skipped job only when detection says that job is unnecessary. Branch protection requires this gate alongside the three existing application checks on both `develop` and `main`.

Our workflow is **task PR → green CI → self-merge**. Reviews are optional, and the optional `skip-review` label does not bypass CI. The repository is public, and GitHub protects both `develop` and `main`: pull requests and required checks apply even to administrators; force-pushes and branch deletion are blocked. Human approvals are not required. GitHub does not require updating a PR branch after every base-branch change. No special GitHub board is required. Use the team chat to coordinate.

## Build and deploy releases

After a release PR reaches `main` and CI passes, GitHub builds the application Docker image and pushes it to GHCR with a commit tag and immutable digest. Once the cluster is bootstrapped and `DEPLOY_ENABLED=true`, the same release updates the running app and waits for readiness; a failed rollout restores the previous image. Human approval is not required.

Deployment is off until the one-time setup is complete. Terraform provisioning, database migrations and catalog import remain explicit operator steps. See [the release setup instructions](infra/README.md#simple-main-to-cluster-release-pipeline) for the cluster ID, deployment token, initial public image, and activation switch.

## Local setup

Requires Docker, Python **3.12.12** through uv **0.12.5**, and Node **24.6.0**. Python and frontend dependencies are locked. All commands below start in the repository root.

```sh
uv sync --frozen
uv run aimo configure                 # creates ignored .env with random private credentials
# If .env already exists, preserve it and add missing settings from .env.example.
docker compose up -d --wait db
uv run aimo migrate                   # explicit, versioned schema setup
uv run aimo seed                      # inserts missing demo settings only; never overwrites
npm ci --prefix frontend
npm run build --prefix frontend
```

For the full supplied catalog, use your private local snapshot (not included in Git). The default count and SHA-256 identify the verified 17,546-product challenge snapshot:

```sh
uv run aimo ingest --file /absolute/path/valio_aimo_junction26_product_data.json
# Or obtain it from the sponsor with a server-side VALIO_AIMO_API_KEY:
mkdir -p data
uv run aimo ingest --download --file data/valio_aimo_junction26_product_data.json
uv run aimo serve
```

The first import downloads the pinned `intfloat/multilingual-e5-small` model and embeds the catalog on CPU. Subsequent imports reuse unchanged text embeddings. Publication is atomic: failures leave the old generation active. Updated snapshots require an explicitly verified `--expected-count` and `--expected-sha256`. There is no import on requests or startup. Imports retain withdrawal markers for explicit purchase denial while excluding withdrawn products from discovery. Publication retains the active and previous generation's product/vector rows by default (`CATALOG_GENERATIONS_TO_KEEP=2`). Generation metadata, reusable embedding cache and immutable purchase snapshots remain. Semantic retrieval ranks the filtered active generation exactly, avoiding filtered approximate-index recall loss at this MVP catalog size.

For a quick authored-fixture catalog, use `uv run aimo fixture-catalog` instead of `ingest`. Set `EMBEDDING_BACKEND=fixture` in `.env` only when you also want deterministic fake embeddings; ingestion and serving must use the same setting. The default uses the real model, including for a small fixture catalog. `UPSTREAM_MODE=fixture` is independent: commercial prices/stock remain invented unless explicitly switched to `live` with private credentials. There is no silent live-to-fixture fallback.

Open [the buyer inbox](http://localhost:8000/approvals). Username: **buyer**. Read the generated `DEMO_BUYER_PASSWORD` privately from `.env`; the agent uses the separate `DEMO_AGENT_TOKEN`. The browser never receives agent/API keys. `SECURE_COOKIES=false` is for localhost HTTP only. Hosted deployments require HTTPS and `SECURE_COOKIES=true`.

For frontend development, run `npm run dev --prefix frontend` and temporarily set `PUBLIC_BASE_URL=http://localhost:5173` for the backend. Vite proxies `/api`; production serves the built assets from FastAPI. The source of the browser's generated types is Python: `uv run python scripts/export_schema.py && npm run types --prefix frontend`.

## Demo

```sh
uv run python scripts/demo.py
```

This reference client demonstrates an autonomous purchase and identical receipt on retry; a denied hard budget; an unresolved shortage; and a mission waiting for approval. The buyer independently opens `/approvals`, logs in, and approves or rejects. Use the printed `--resume` command to let the agent retrieve the decision and commit. **Approval itself never places an order.** For a recorded successful retry, keep the same `--key` and payload; retrieve existing receipts through `get_order`.

The fixture shortage scenario is 600 L of `464306` plus 400 L of `464398`, marked as a substitution and requiring approval. These are invented stock levels, not current inventory. The real static snapshot verifies the quantities for these two products. A natural live shortage has **not** been independently verified in this implementation session; use the bounded probe when credentials are available:

```sh
uv run python scripts/probe_upstream.py --date 2026-11-16 --ids 463380 464306 464398
```

## Interfaces and authorization

| Agent tool | HTTP route |
| --- | --- |
| `search_products` | `POST /api/agent/search_products` |
| `get_product` | `GET /api/agent/products/{product_id}` |
| `get_purchase_policy` | `GET /api/agent/purchase-policy` |
| `check_price_and_availability` | `POST /api/agent/check_price_and_availability` |
| `prepare_order` | `POST /api/agent/prepare_order` |
| `get_proposal` | `GET /api/agent/proposals/{proposal_id}` |
| `commit_order` | `POST /api/agent/commit_order` |
| `get_order` | `GET /api/agent/orders/{order_id}` |

Use `Authorization: Bearer <private agent token>` for HTTP and stateless Streamable HTTP MCP at `/mcp/`. MCP tool arguments use a typed `request` object where applicable; product/proposal/order lookups take their identifier directly. All eight operations share Pydantic response contracts across HTTP and MCP. Commit returns a flat object discriminated by `status`: `accepted_mock` (receipt) or `revised` (fresh proposal); neither uses an extra result envelope. Every tool checks the credential and buyer scope. Proposals and orders are additionally scoped to their creating agent. The demo uses preconfigured bearer credentials, not OAuth discovery. Interactive OpenAPI documentation is at `/docs`; it loads Swagger assets from jsDelivr with a per-response script nonce and a documentation-only CSP. The buyer UI retains its strict same-origin CSP. [Examples](docs/examples/requests.json) contain no credentials. `uv run python scripts/mcp_smoke.py` runs all eight tools with the official SDK client against the server.

The browser uses `/login`, `/approvals`, `/approvals/{approval_id}`, and separate `/api/login`, `/api/session`, `/api/logout`, `/api/approvals` and decision routes. Historical approvals stay superseded after a newer revision is committed. They link to `/purchases/{proposal_id}` (buyer-authenticated `/api/purchases/{proposal_id}`), which displays current terms even when the newer revision needs no approval. `order_id` and accepted status belong only to the committed revision; `current_revision`, `committed_revision` and `current_proposal_url` identify the newer terms without attaching their receipt to an old snapshot. Direct approval/current-purchase links survive sign-in. Sessions are signed, persisted, HttpOnly, SameSite Strict and expiring. State changes require an exact configured Origin and session-bound CSRF header. Buyer passwords use Argon2; API tokens and session lookup tokens are hashed. Login attempts are rate-limited in PostgreSQL. The URL grants no authority. Inbox pagination is bounded; refresh pauses while hidden. There is no email/push notifier or claim of delivery.

Policy is seeded in PostgreSQL, versioned and read-only at runtime. The demo autonomous gross limit is €1,500; the buyer can approve up to €5,000 for spend, substitution and overbuy exceptions. Only `hotel-helsinki` is allowed. Mission budgets and permissions can tighten these rules. Whole discrete sales units are an **explicit buyer rule**, retaining the source lot step. Unknown conversions, variable weight, conflicting dietary evidence, missing costs, uncertain supplier stock and passed cutoffs cannot be fixed by approval.

The policy also contains a **buyer-approved product scope**, seeded as `approved_product_ids=["464306"]`. A product outside that scope counts as a substitution even if the agent omits `substitutes_for`; the policy then requires approval or denies it. This is standing product authority, not verification of an arbitrary natural-language mission. Products inside the approved set are selectable by the agent. Missing scope fails closed when substitution restrictions apply. Only privileged setup can change the scope by inserting a new policy version; agents cannot submit or edit it.

`prepare_order` requires a stable `idempotency_key` (8–120 characters), scoped to buyer and agent. Identical retries return the same proposal and its current status without another supplier lookup; changed payloads with the same key return `IDEMPOTENCY_CONFLICT`. `request_id` remains a display label. Use a new key for a new purchase or a fresh proposal after expiry. Commit uses its own existing buyer-scoped idempotency key.

**Upgrade from earlier PR #4 revisions:** run `uv run aimo migrate` to apply migration `002_review_hardening.sql`, update prepare clients, then explicitly configure the existing demo buyer with `uv run aimo set-product-scope --buyer demo-hotel --product-id 464306`. Repeat `--product-id` for additional buyer-authorized products. Seeding preserves existing policies; it does not silently grant new authority. Old proposal snapshots remain readable.

Login throttling separates failed passwords (10 per client/username in five minutes) from total requests (60 per client/minute); successful logins do not consume the failed-password budget. Expired counters and sessions are cleaned in bounded batches. Behind ingress, configure `FORWARDED_ALLOW_IPS` with the actual trusted proxy addresses/CIDRs and ensure ingress replaces untrusted forwarded headers; never use `*`. PostgreSQL connections are pooled with a default maximum of 10 per process and a bounded wait. The pending inbox batches page data/history into six SQL statements rather than querying each item's dependencies separately.

Commit re-fetches commercial evidence outside the transaction, then locks the buyer, current identities and proposal in a consistent order. Changed commercial terms, policy version or effective authorization decision create a new immutable revision and invalidate earlier approval. Lowering an agent's limit can therefore create a pending approval without changing the policy version or prices; losing the last eligible approver produces `needs_resolution`. Current approver and agent authority are checked again. Before revalidation, a stale proposal reports `authority_changed` and directs the caller to refresh, instead of advertising commitment. Unique database constraints enforce one order per proposal and one payload per buyer/idempotency key. A completed authenticated retry returns its saved receipt before querying upstream. Privileged authority/policy maintenance must take the same buyer lock before changing identity rows/current policy; insert a policy version instead of updating history. Ordinary HTTP/MCP provides no maintenance action. See the module docstrings and SQL migration for this protocol.

Receipts say **“Accepted by demo order service”** and explicitly report no supplier order and no reservation. Demo delivery charges are zero by adapter definition; real checkout charges need an upstream contract. The supplied API has no order endpoint.

## Verification

```sh
uv run ruff check src tests scripts
uv run pytest -q                         # real pgvector/PostgreSQL, isolated aimo_test DB
npm ci --prefix frontend
npm run build --prefix frontend
npm exec --prefix frontend -- playwright install chromium
npm run test --prefix frontend           # running server, .env credentials, full or fixture catalog
uv run python scripts/mcp_smoke.py        # running server; official SDK transport
# Optional actual process-restart check on a dedicated local test container:
uv run python scripts/restart_smoke.py --container aimo-mvp-verify --base-url http://localhost:8001
uv run python scripts/verify_catalog.py /absolute/path/valio_aimo_junction26_product_data.json
uv run python scripts/evaluate_search.py  # full catalog, real embeddings; writes compact results
```

Tests require a PostgreSQL role permitted to create `aimo_test`, or an existing database named with `_test` and `TEST_DATABASE_URL` configured. Tests refuse to clear a database without that suffix. Browser tests create mock purchases in the demo database and require fixture commerce. The historical-revision test uses `uv` and `tests/browser_revision_fixture.py` to seed its own repriced purchase; its `DATABASE_URL` must point to the same database as the running server. `/docs` testing needs access to jsDelivr. `BASE_URL` selects a browser-test origin; `DEMO_BASE_URL` selects the reference/MCP clients. [Validation](docs/validation.md) records actual outcomes and the limited 30-case retrieval evaluation.

## One production image, existing cluster

```sh
docker build -t aimo-mvp:local .
# Same image supports explicit setup/import commands; .env is never baked into it.
docker compose --profile app run --rm app migrate
docker compose --profile app run --rm app seed
docker compose --profile app run --rm app fixture-catalog
# For a full catalog, use the volume-mounted invocation in deploy/README.md instead.
docker compose --profile app up -d app
```

The Node stage builds assets; the Python runtime contains no Node server. Linux uses CPU-only PyTorch. Model weights are pinned and cached at image build; runtime uses offline model loading. Use `/health/live` for liveness and `/health/ready` for database/index/model readiness, without requiring the supplier to be online.

[Deployment instructions](deploy/README.md) and Kubernetes manifests target an **existing** database/cluster/TLS setup, with one application replica and a manual ingestion Job. They contain placeholders and have not been deployed to a cluster. No cluster, database operator, paid infrastructure or real supplier order was provisioned.

[Preparation and third-party provenance](docs/pre-existing-work.md) must accompany the event submission. Restricted raw data, credentials, downloaded weights and generated browser test artifacts are ignored.
