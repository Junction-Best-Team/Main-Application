# Aimo chat purchasing

Three independently deployed apps serve chat purchasing: a React/Nginx frontend, an authenticated FastAPI API, and a durable AI worker. They record **persistent mock orders**. Open `/`, sign in, and ask for ingredients for 200 portions of carbonara. PostgreSQL retains conversations, exact proposal revisions, customer confirmations, policies, approvals, orders and audit history. No supplier checkout or inventory reservation is implemented.

The current [product migration](docs/chat-purchasing.md) overrides the external-agent entry points in the [original brief](docs/brief.md). The underlying purchasing controls remain. [Infrastructure](infra/README.md) is optional and operator-managed; this migration does not apply Terraform, deploy or enable releases.

See the [architecture diagrams](docs/architecture.md) for the system overview, purchase confirmation flow and code map.

## Working in parallel

- Start a task from the latest `develop`: `git switch develop`, then `git pull --ff-only` with a clean working tree. For an existing clone without that branch, first run `git fetch origin` and `git switch --track origin/develop`.
- Use a short task branch, for example `git switch -c otto/map-view`. Do not commit or push directly to `develop` or `main`.
- Say which feature/files you are changing. Coordinate edits to shared APIs, schemas, dependency files, and deployment configuration.
- Check the affected feature works, then open a PR into `develop`: `gh pr create --base develop`. All feature, fix, documentation, and maintenance PRs must target `develop`. Wait for the latest CI run to pass, then self-merge. Human approval is optional; request teammate review for risky authentication, database schema, or shared-interface changes.
- Keep `main` ready to demonstrate. Promote a tested snapshot with a release PR from `develop` to `main` only when a release is explicitly requested. Avoid force pushes to shared branches and preserve teammates' uncommitted work.
- Use a separate checkout/worktree and branch for each concurrent agent on the same machine.

See [separate apps and the one-time cluster cutover](docs/separate-apps.md) for images, routing, queue recovery and deployment steps.

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

After a release PR reaches `main` and CI passes, GitHub builds the frontend, API and worker Docker images and pushes each to GHCR with a component/commit tag and immutable digest. Once the cluster is bootstrapped and `DEPLOY_ENABLED=true`, the same release updates all three apps and waits for readiness; a failed rollout restores every changed image. Human approval is not required.

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
uv run aimo serve                    # API terminal
# In separate terminals: uv run aimo worker, and npm run dev --prefix frontend
```

The first import downloads the pinned `intfloat/multilingual-e5-small` model and embeds the catalog on CPU. Subsequent imports reuse unchanged text embeddings. Publication is atomic: failures leave the old generation active. Updated snapshots require an explicitly verified `--expected-count` and `--expected-sha256`. There is no import on requests or startup. Imports retain withdrawal markers for explicit purchase denial while excluding withdrawn products from discovery. Publication retains the active and previous generation's product/vector rows by default (`CATALOG_GENERATIONS_TO_KEEP=2`). Generation metadata, reusable embedding cache and immutable purchase snapshots remain. Semantic retrieval ranks the filtered active generation exactly, avoiding filtered approximate-index recall loss at this MVP catalog size.

For a quick authored-fixture catalog, use `uv run aimo fixture-catalog` instead of `ingest`. Set `EMBEDDING_BACKEND=fixture` in `.env` only when you also want deterministic fake embeddings; ingestion and serving must use the same setting. The default uses the real model, including for a small fixture catalog. `UPSTREAM_MODE=fixture` is independent: commercial prices/stock remain invented unless explicitly switched to `live` with private credentials. There is no silent live-to-fixture fallback.

Run `docker compose --profile app up --build` after setup, then open [chat purchasing](http://localhost:8000/). Username: **buyer**. Read the generated `DEMO_BUYER_PASSWORD` privately from `.env`. Configure `LLM_API_KEY` privately for chat; `LLM_BASE_URL` and `LLM_MODEL` select the conversational provider independently of local embeddings. The browser never receives provider/API keys. `SECURE_COOKIES=false` is for localhost HTTP only. Hosted deployments require HTTPS and `SECURE_COOKIES=true`.

For frontend development, run `npm run dev --prefix frontend` and temporarily set `PUBLIC_BASE_URL=http://localhost:5173` for the backend. Vite proxies `/api`; production serves built assets from the separate frontend container, with Traefik routing API/SSE directly to FastAPI. The source of the browser's generated types is Python: `uv run python scripts/export_schema.py && npm run types --prefix frontend`.

## Demo and browser interfaces

```sh
uv run python scripts/demo.py
# Continue clarification in the same persisted conversation:
uv run python scripts/demo.py --conversation <uuid> --message "Delivery 2026-11-16, hotel-helsinki, no dietary restrictions, budget EUR 1000"
```

The CLI authenticates as the buyer and starts chat. Complete recipe clarification, inspect the actual product quantities and commercial evidence, then explicitly click **Confirm purchase** inside the product. Chat text never confirms anything. Prices/stock are invented when `UPSTREAM_MODE=fixture`; the optional live supplier connector still does not place orders.

`/` is chat, `/conversations/{id}` is addressable chat, `/purchases` preserves purchase history, and `/purchases/{proposal_id}` reviews current terms. Legacy `/approvals/{approval_id}` remains an authenticated exact historical snapshot; superseded terms link explicitly to the current revision. `/approvals` redirects to purchases.

Authenticated JSON routes are `/api/conversations`, `/api/conversations/{id}`, `/api/conversations/{id}/messages`, `/api/conversations/{id}/events`, `/api/purchases` and `/api/purchases/{id}/confirm`, plus existing session, approval-detail/decision and purchase-detail APIs. Writes require the buyer session, exact configured Origin and session-bound CSRF token. SSE replays persisted conversation state and sends heartbeats; it does not stream speculative model tokens. Interactive contracts are at `/docs`; generated browser types come from Python. [Credential-free examples](docs/examples/requests.json) show the request bodies.

`/mcp` and every `/api/agent/*` route are removed and return JSON 404. The internal typed agent calls `Service` directly with a server-controlled buyer identity. There is no external bearer-token provisioning or MCP client. A PostgreSQL-backed job queue connects the API to the independent worker.

Apply additive migration `003_chat_purchasing.sql` using the setup role before running the new image. It retains all historical purchasing records and creates zero-autonomous-limit internal agents for existing buyers without broadening their product scope. New demo provisioning needs only `DEMO_BUYER_PASSWORD`. Old private `DEMO_AGENT_TOKEN` settings can be removed from your secret store; historical identity rows must stay. See [upgrade and operational details](docs/chat-purchasing.md).

Policy is seeded in PostgreSQL, versioned and read-only at runtime. The demo autonomous gross limit is €1,500; the buyer can approve up to €5,000 for spend, substitution and overbuy exceptions. Only `hotel-helsinki` is allowed. Mission budgets and permissions can tighten these rules. Whole discrete sales units are an **explicit buyer rule**, retaining the source lot step. Unknown conversions, variable weight, conflicting dietary evidence, missing costs, uncertain supplier stock and passed cutoffs cannot be fixed by approval.

The policy also contains a **buyer-approved product scope**, seeded as `approved_product_ids=["464306"]`. A product outside that scope counts as a substitution even if the agent omits `substitutes_for`; the policy then requires approval or denies it. This is standing product authority, not verification of an arbitrary natural-language mission. Products inside the approved set are selectable by the agent. Missing scope fails closed when substitution restrictions apply. Only privileged setup can change the scope by inserting a new policy version; agents cannot submit or edit it.

`prepare_order` requires a stable `idempotency_key` (8–120 characters), scoped to buyer and agent. Identical retries return the same proposal and its current status without another supplier lookup; changed payloads with the same key return `IDEMPOTENCY_CONFLICT`. `request_id` remains a display label. Use a new key for a new purchase or a fresh proposal after expiry. Commit uses its own existing buyer-scoped idempotency key.

**Upgrade from earlier PR #4 revisions:** run `uv run aimo migrate` to apply migration `002_review_hardening.sql`, update prepare clients, then explicitly configure the existing demo buyer with `uv run aimo set-product-scope --buyer demo-hotel --product-id 464306`. Repeat `--product-id` for additional buyer-authorized products. Seeding preserves existing policies; it does not silently grant new authority. Old proposal snapshots remain readable.

Login throttling separates failed passwords (10 per client/username in five minutes) from total requests (60 per client/minute); successful logins do not consume the failed-password budget. Expired counters and sessions are cleaned in bounded batches. Behind ingress, configure `FORWARDED_ALLOW_IPS` with the actual trusted proxy addresses/CIDRs and ensure ingress replaces untrusted forwarded headers; never use `*`. PostgreSQL connections are pooled with a default maximum of 10 per process and a bounded wait. The pending inbox batches page data/history into six SQL statements rather than querying each item's dependencies separately.

Commit re-fetches commercial evidence outside the transaction, then locks the buyer, current identities and proposal in a consistent order. Changed commercial terms, policy version or effective authorization decision create a new immutable revision and invalidate earlier approval. Lowering an agent's limit can therefore create a pending approval without changing the policy version or prices; losing the last eligible approver produces `needs_resolution`. Current approver and agent authority are checked again. Before revalidation, a stale proposal reports `authority_changed` and directs the caller to refresh, instead of advertising commitment. Unique database constraints enforce one order per proposal and one payload per buyer/idempotency key. A completed authenticated retry returns its saved receipt before querying upstream. Privileged authority/policy maintenance must take the same buyer lock before changing identity rows/current policy; insert a policy version instead of updating history. The browser/agent interfaces provide no maintenance action. See the module docstrings and SQL migration for this protocol.

Receipts say **“Accepted by demo order service”** and explicitly report no supplier order and no reservation. Demo delivery charges are zero by adapter definition; real checkout charges need an upstream contract. The supplied API has no order endpoint.

## Verification

```sh
uv run ruff check src tests scripts
uv run pytest -q                         # real pgvector/PostgreSQL, isolated aimo_test DB
npm ci --prefix frontend
npm run build --prefix frontend
npm exec --prefix frontend -- playwright install chromium
npm run test --prefix frontend           # running frontend/server; default UI route fixtures
# Explicit mock-confirmation/process-restart check in a dedicated verification container:
uv run python scripts/restart_smoke.py --container aimo-mvp-verify --base-url http://localhost:8001 --conversation <uuid> --proposal <uuid>
uv run python scripts/verify_catalog.py /absolute/path/valio_aimo_junction26_product_data.json
uv run python scripts/evaluate_search.py  # full catalog, real embeddings; writes compact results
```

Tests require a PostgreSQL role permitted to create `aimo_test`, or an existing database named with `_test` and `TEST_DATABASE_URL` configured. Tests refuse to clear a database without that suffix. Browser tests create mock purchases in the demo database and require fixture commerce. The historical-revision test uses `uv` and `tests/browser_revision_fixture.py` to seed its own repriced purchase; its `DATABASE_URL` must point to the same database as the running server. `/docs` testing needs access to jsDelivr. `BASE_URL` selects a browser-test origin; `DEMO_BASE_URL` selects the chat demo. `AIMO_INTEGRATION=1` enables real-server browser checks; default UI regressions mock route responses. [Current migration verification](docs/chat-purchasing.md#verification-record) records the chat cutover. [Historical gateway validation](docs/validation.md) retains the earlier outcomes and limited 30-case retrieval evaluation.

## Three production images, existing cluster

```sh
docker build --target frontend -t aimo:frontend .
docker build --target api -t aimo:api .
docker build --target worker -t aimo:worker .
# Run migrate/seed/import explicitly as shown in Local setup first.
docker compose --profile app up -d --build
```

The frontend image serves built React assets with Nginx. The API image contains
FastAPI without PyTorch/model weights. The worker image loads the pinned model
offline and consumes durable chat jobs. Each app has its own health endpoints.
API readiness checks schema/catalog compatibility; worker readiness also requires
model initialization and a recent successful database poll.

[Deployment instructions](deploy/README.md) and [the cutover runbook](docs/separate-apps.md)
cover independent Kubernetes Deployments, Services, path routing, migration 004,
and rollback while preserving the existing managed database and purchase history.
The separate-app rollout is not implied by a successful local build or PR check.
[Release migration operations](docs/release-migrations.md) covers the automatic
schema/grant Job, its one-time Secret provisioning, and image rollback limitations.

[Preparation and third-party provenance](docs/pre-existing-work.md) must accompany the event submission. Restricted raw data, credentials, downloaded weights and generated browser test artifacts are ignored.
