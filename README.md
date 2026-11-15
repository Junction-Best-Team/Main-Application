# Aimo chat purchasing

Three independently deployed apps serve chat purchasing: a React/Nginx frontend, an authenticated FastAPI API, and a durable AI worker. They record **persistent mock orders**. Open `/`, sign in, and ask for ingredients for 200 portions of carbonara. PostgreSQL retains conversations, exact proposal revisions, customer confirmations, policies, approvals, orders and audit history. No supplier checkout or inventory reservation is implemented.

Chat accepts small [documents, spreadsheets and images](docs/attachments.md) through drag/drop or paste, with previews and a limit of three files (2 MB each / 4 MB total). Apply migration `020_chat_attachments.sql` before running this version.

The request composer also offers [voice mode](docs/voice.md): while the composer has no draft or attachment, click the waveform button (typing or attaching swaps it for the send arrow), allow
the microphone and speak with Aimo using Gemini 3.8 Live. Voice uses the same saved
chat and purchasing controls; baskets still require confirmation on screen.

The [product brief](docs/brief.md) defines the current purchasing controls; [chat behavior](docs/chat-purchasing.md) describes conversations and confirmation. [Infrastructure](infra/README.md) is operator-managed.

See the [architecture diagrams](docs/architecture.md) for the system overview, purchase confirmation flow and code map. The assistant keeps explicitly saved buyer-shared and personal preferences across conversations; see [buyer and user memory](docs/memory.md) (`/api/memories`, migration 012). Memory never grants purchasing authority. [Agent guardrails](docs/guardrails.md) separates deterministic controls from the Gemini Decision 1 checks, which enforce by default using the server-side `GEMINI_API_KEY` (`GUARDRAIL_MODE=enforce|shadow|off`).

## Working in parallel

- Start a task from the latest `develop`: `git switch develop`, then `git pull --ff-only` with a clean working tree. For an existing clone without that branch, first run `git fetch origin` and `git switch --track origin/develop`.
- Use a short task branch, for example `git switch -c otto/map-view`. Do not commit or push directly to `develop` or `main`.
- Say which feature/files you are changing. Coordinate edits to shared APIs, schemas, dependency files, and deployment configuration.
- Check the affected feature works, then open a PR into `develop`: `gh pr create --base develop`. All feature, fix, documentation, and maintenance PRs must target `develop`. Wait for the latest CI run to pass, then self-merge. Human approval is optional; request teammate review for risky authentication, database schema, or shared-interface changes.
- Keep `main` ready to demonstrate. Promote a tested snapshot with a release PR from `develop` to `main` only when a release is explicitly requested. Avoid force pushes to shared branches and preserve teammates' uncommitted work.
- Use a separate checkout/worktree and branch for each concurrent agent on the same machine.

## CI

One workflow, `.github/workflows/ci.yml`, runs on PRs into `develop` and `main`, plus manual runs. Change detection starts the applicable backend and frontend jobs in parallel:

| Job (GitHub name) | What it does |
| --- | --- |
| Python lint and tests | `ruff check`, then core app regressions against temporary PostgreSQL/pgvector, then the strict buyer-facing API sweep; uses fixture embeddings and supplier responses |
| Frontend types and build | `npm ci`, TypeScript check and production build; formatting and browser tests stay local |
| Detect application components | Selects backend, frontend and infrastructure checks; retains its existing name for required status checks |
| Terraform | Format, validate, mocked-provider plan tests and Helm render for `infra/` (only when it or the workflows changed) |
| **CI gate** | Requires change detection and every selected application/infrastructure check to succeed |

Frontend-only PRs skip backend tests, except the shared OpenAPI contract; documentation-only PRs skip application checks. Python source changes run both application jobs; tests, migrations and Python dependencies run backend checks. Infrastructure changes run Terraform; workflow changes and unknown paths run conservative checks. The gate accepts a skip only when change detection explicitly marked that check unrelated. Manual CI runs every check and the full pytest suite. PRs use `tests/pr-tests.sh`: login/CSRF, buyer isolation, persistent chat/retries, worker recovery, scripted-agent checkout, exact-revision confirmation, purchase limits, migrations/runtime grants and a scheduling flow. Exhaustive edge-case tests stay available locally and on manual CI; they no longer block ordinary contributions.

The API sweep shares the backend job's Python environment and temporary, memory-backed PostgreSQL service. Coverage is an optional local diagnostic, with no percentage requirement or coverage artifact jobs in CI. Dependencies are locked and cached; new commits cancel outdated PR runs. CI uses fixtures, without supplier keys, model downloads or full catalog imports. The live check is local: `tests/ci.sh --live`. See [tests/README.md](tests/README.md).

Our workflow is **task PR → green CI → self-merge**. Repository rules require the CI gate plus the three existing application check names; reviews are optional and the `skip-review` label does not bypass CI. If adding a job, include its result in the gate.

## Build and deploy releases

After the release PR passes CI and reaches protected `main`, GitHub immediately builds the frontend, API and worker Docker images and pushes each to GHCR with a component/commit tag and immutable digest. Once the cluster is bootstrapped and `DEPLOY_ENABLED=true`, the same release migrates first, starts all three app rollouts together and waits for readiness; a failed rollout restores every changed image. Human approval is not required.

Same-repository `develop` → `main` release PRs reuse the protected integration branch checks and skip application/infrastructure tests; the source-branch rule and CI gate still run. Merged pushes do not repeat PR tests on `develop` or `main`. The release workflow relies on the required PR checks and PR-only branch rules; retain those protections.

Deployment is off until the one-time setup is complete. Terraform provisioning, database migrations, grants and secret provisioning remain explicit operator steps. Product-catalog ingestion then runs automatically as the scheduled `aimo-catalog-sync` Kubernetes Job, which skips unchanged snapshots ([catalog sync](docs/catalog-sync.md)). See [the release setup instructions](infra/README.md#simple-main-to-cluster-release-pipeline) for the cluster ID, deployment token, initial public image, and activation switch.

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
# Or the unattended command the Kubernetes CronJob runs: download (or --file), verify the
# approved hash, skip if the active catalog is current, otherwise import and activate.
uv run aimo sync-catalog
uv run aimo serve                    # API terminal
# In separate terminals: uv run aimo worker, and npm run dev --prefix frontend
```

Google is the default for embeddings and shortlist ranking. Existing installations need the [Google model and index cutover](docs/google-models.md); changing configuration cannot reuse old vectors. The [OpenRouter profile](docs/hosted-search.md) remains an explicit legacy option.

Imports use Gemini Embedding 2 through the private `GEMINI_API_KEY`; uncached documents consume Google quota/credits. Subsequent imports reuse unchanged text embeddings. Publication is atomic: failures leave the old generation active. Updated snapshots require an explicitly verified `--expected-count` and `--expected-sha256`. There is no import on requests or startup. `aimo ingest` always builds a new generation, while `aimo sync-catalog` skips a snapshot whose hash, embedding profile, import profile and complete row count already match the active catalog. Only one ingestion run (either command) can hold the database lock at a time. Imports retain withdrawal markers for explicit purchase denial while excluding withdrawn products from discovery. Publication retains the active and previous generation's product/vector rows by default (`CATALOG_GENERATIONS_TO_KEEP=2`). Generation metadata, reusable embedding cache and immutable purchase snapshots remain. Semantic retrieval ranks the filtered active generation exactly, avoiding filtered approximate-index recall loss at this MVP catalog size.

For a quick authored-fixture catalog, use `uv run aimo fixture-catalog` instead of `ingest`. Set `EMBEDDING_BACKEND=fixture` in `.env` only when you also want deterministic fake embeddings; ingestion and serving must use the same setting. The default uses the real model, including for a small fixture catalog. The application always obtains commercial prices/stock from Valio; the authored supplier responses live only in the test harness. A fixture catalog does not provide prices.

Run `docker compose --profile app up --build` after setup, then open [chat purchasing](http://localhost:8000/). Username: **buyer**. Read the generated `DEMO_BUYER_PASSWORD` privately from `.env`. Configure `GEMINI_API_KEY` privately for chat, semantic checks and search. The default chat model is `gemini-4-carbon`; `LLM_PROVIDER=google`, `GUARDRAIL_PROVIDER=google` and `EMBEDDING_BACKEND=google` select the native Google adapters. The browser never receives provider/API keys. `SECURE_COOKIES=false` is for localhost HTTP only. Hosted deployments require HTTPS and `SECURE_COOKIES=true`. See [operational logging](docs/logging.md) for request/turn correlation, safe error diagnostics, model settings and existing-deployment overrides.

For frontend development, run `npm run dev --prefix frontend` and temporarily set `PUBLIC_BASE_URL=http://localhost:5173` for the backend. Vite proxies `/api`; production serves built assets from the separate frontend container, with Traefik routing API/SSE directly to FastAPI. The source of the browser's generated types is Python: `uv run python scripts/export_schema.py && npm run types --prefix frontend`.

## Valio API key and upstream modes

The application uses the real supplier at `https://junction26.valioaimo.fi`:
`POST /api/price` and `POST /api/availability`, authenticated by the private
`VALIO_AIMO_API_KEY`. Search the catalog first, then query only shortlisted products.

`UPSTREAM_MODE=live` is the default. Legacy `auto` means live as well; neither falls
back to invented prices. API startup and worker readiness fail without the key or
with a different supplier URL. `fixture` is refused by application entry points.

**The key exists and team members have it.** Put it in your gitignored `.env` as
`VALIO_AIMO_API_KEY` (never commit or print it). `GET /health/ready` reports the
supplier mode. Historical fixture evidence remains labelled.

CI stays offline through `tests/supplier_fixture.py` and the explicit
`tests/fixture_app.py` API harness, which are excluded from application images.
For a dedicated fixture database, use `UPSTREAM_MODE=fixture uv run uvicorn
--app-dir tests fixture_app:app`; `tests/ci.sh` configures that harness automatically.

## Demo

```sh
uv run python scripts/demo.py
# Continue clarification in the same persisted conversation:
uv run python scripts/demo.py --conversation <uuid> --message "Delivery 2026-11-16, hotel-helsinki, no dietary restrictions, budget EUR 1000"
```

The CLI authenticates as the buyer and starts chat. Complete recipe clarification, inspect the actual product quantities and commercial evidence, then explicitly click **Confirm purchase** inside the product. Chat text never confirms anything. Supplier prices/stock are live; the supplier connector does not place orders.

`/` is chat, `/conversations/{id}` is addressable chat, `/purchases` preserves purchase history, and `/purchases/{proposal_id}` reviews current terms. Legacy `/approvals/{approval_id}` remains an authenticated exact historical snapshot; superseded terms link explicitly to the current revision. `/approvals` redirects to purchases.

Authenticated JSON routes are `/api/conversations`, `/api/conversations/{id}`, `/api/conversations/{id}/messages`, `/api/conversations/{id}/events`, `/api/purchases` and `/api/purchases/{id}/confirm`, plus existing session, approval-detail/decision and purchase-detail APIs. Writes require the buyer session, exact configured Origin and session-bound CSRF token. SSE replays persisted conversation state and sends heartbeats; it does not stream speculative model tokens. The optional `activity` field carries the latest turn’s sanitized tool starts/completions/failures at the existing two-second SSE cadence. The chat shows an animated current action and expandable step history, restored on reconnect/refresh. Apply additive migrations `022_chat_activity.sql` and `023_chat_draft_cart.sql` before starting this version. The optional `draft_cart` contains selected ingredients and checked unit prices while the basket is built; prepared proposals alone enable confirmation. Activity contains fixed display labels, never tool arguments/results or model reasoning, and cannot authorize a purchase. Interactive contracts are at `/docs`; generated browser types come from Python. [Credential-free examples](docs/examples/requests.json) show the request bodies.

`/mcp` and every `/api/agent/*` route are removed and return JSON 404. The internal typed agent calls `Service` directly with a server-controlled buyer identity. There is no external bearer-token provisioning or MCP client. A PostgreSQL-backed job queue connects the API to the independent worker.

Apply additive migration `003_chat_purchasing.sql` using the setup role before running the new image. It retains all historical purchasing records and creates internal agents (which since the spend-authority removal hold no authority at all) for existing buyers without broadening their product scope. New demo provisioning needs only `DEMO_BUYER_PASSWORD`. Old private `DEMO_AGENT_TOKEN` settings can be removed from your secret store; historical identity rows must stay. See [upgrade and operational details](docs/chat-purchasing.md).

Policy is seeded in PostgreSQL and versioned. Signed-in human buyers can edit the account spending cap and basket rules at `/settings`; agents retain read-only access. Agents hold no spending authority: there is no autonomous limit and no `spend` exception. Spending is bounded by the optional account-wide `max_order_gross` cap, each human approver's maximum gross amount (the demo buyer can approve up to €5,000, plus substitution and overbuy exceptions) and the request's hard budget. Above-cap baskets are denied; a total above every active approver's maximum, or no active approver, is `needs_resolution`. Every purchase still waits for the customer's confirmation. Stored policy versions and identities that still carry the old `autonomous_limit` / `spend` keys are tolerated and ignored. The seeded destination is `hotel-helsinki`. Mission budgets and permissions can tighten these rules. Whole discrete sales units are an **explicit buyer rule**, retaining the source lot step. Unknown conversions, variable weight, conflicting dietary evidence, missing costs, uncertain supplier stock and passed cutoffs cannot be fixed by approval.

The policy also contains a **buyer-approved product scope**, seeded as `approved_product_ids=["464306"]`. A product outside that scope counts as a substitution even if the agent omits `substitutes_for`; the policy then requires approval or denies it. This is standing product authority, not verification of an arbitrary natural-language mission. Products inside the approved set are selectable by the agent. Missing scope always blocks purchasing. Product scope remains operator-provisioned and is preserved when saving the simplified Settings form; agents cannot submit or edit it.

`prepare_order` requires a stable `idempotency_key` (8–120 characters), scoped to buyer and agent. Identical retries return the same proposal and its current status without another supplier lookup; changed payloads with the same key return `IDEMPOTENCY_CONFLICT`. `request_id` remains a display label. Use a new key for a new purchase or a fresh proposal after expiry. Commit uses its own existing buyer-scoped idempotency key.

**Policy settings upgrade:** apply migration `022_buyer_settings.sql` and reapply runtime grants before starting this version. Every signed-in active buyer can edit the account spending cap, alternatives/extra-quantity rules and whole-sales-unit setting. Blank means no account cap; individual approval permissions still apply. Product/delivery scopes and personal approval authority are preserved server-side. Saves require session/Origin/CSRF, retain policy history and record actor/time. Stale edits return a conflict; unchanged saves create no version. Pending baskets must be refreshed and explicitly confirmed again after a change. See [purchasing settings](docs/policy-settings.md).

Login throttling separates failed passwords (10 per client/username in five minutes) from total requests (60 per client/minute); successful logins do not consume the failed-password budget. Expired counters and sessions are cleaned in bounded batches. Behind ingress, configure `FORWARDED_ALLOW_IPS` with the actual trusted proxy addresses/CIDRs and ensure ingress replaces untrusted forwarded headers; never use `*`. PostgreSQL connections are pooled with a default maximum of 10 per process and a bounded wait. The pending inbox batches page data/history into six SQL statements rather than querying each item's dependencies separately.

Commit re-fetches commercial evidence outside the transaction, then locks the buyer, current identities and proposal in a consistent order. Changed commercial terms, policy version or effective authorization decision create a new immutable revision and invalidate earlier approval. Changing a human approver's authority can therefore change the outcome without changing the policy version or prices; losing the last eligible approver produces `needs_resolution`. Current approver and agent authority are checked again. Before revalidation, a stale proposal reports `authority_changed` and directs the caller to refresh, instead of advertising commitment. Unique database constraints enforce one order per proposal and one payload per buyer/idempotency key. A completed authenticated retry returns its saved receipt before querying upstream. Privileged authority/policy maintenance must take the same buyer lock before changing identity rows/current policy; insert a policy version instead of updating history. The browser exposes the restricted policy settings action; agent interfaces expose no policy maintenance action. See the module docstrings and SQL migration for this protocol.

Receipts say **“Accepted by demo order service”** and explicitly report no supplier order and no reservation. Demo delivery charges are zero by adapter definition; real checkout charges need an upstream contract. The supplied API has no order endpoint.

## Verification

One command runs lint, the pytest suite and a black-box sweep of the buyer-facing API (details in [tests/README.md](tests/README.md)):

```sh
tests/ci.sh          # hermetic: own database, fixture catalog and fixture price/stock, no key needed
tests/ci.sh --live   # your .env database and full catalog, real Valio price/stock
```

The individual checks:


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

Tests require a PostgreSQL role permitted to create `aimo_test`, or an existing database named with `_test` and `TEST_DATABASE_URL` configured. Tests refuse to clear a database without that suffix. Browser tests create mock purchases in the demo database and require fixture commerce. The historical-revision test uses `uv` and `tests/browser_revision_fixture.py` to seed its own repriced purchase; its `DATABASE_URL` must point to the same database as the running server. `/docs` testing needs access to jsDelivr. `BASE_URL` selects a browser-test origin; `DEMO_BASE_URL` selects the chat demo. `AIMO_INTEGRATION=1` enables real-server browser checks; default UI regressions mock route responses.

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

[Deployment instructions](deploy/README.md) and [app operations](docs/separate-apps.md)
cover independent Kubernetes Deployments, Services, path routing and durable jobs
while preserving the existing managed database and purchase history.
The separate-app rollout is not implied by a successful local build or PR check.
[Release migration operations](docs/release-migrations.md) covers the automatic
schema/grant Job, its one-time Secret provisioning, and image rollback limitations.

[Preparation and third-party provenance](docs/pre-existing-work.md) must accompany the event submission. Restricted raw data, credentials, downloaded weights and generated browser test artifacts are ignored.

### Recipe planning

The [shared Google API helper](docs/google-api.md) now powers chat (Gemini 4 Carbon),
guardrails and relevance ranking (Gemini Decision 1), product/recipe embeddings
(Gemini Embedding 2), and images. One server-side `GEMINI_API_KEY` authenticates
directly to Google. Existing installations need the coordinated
[model and index cutover](docs/google-models.md) before rollout.

The [recipe illustration tool](docs/recipe-images.md) generates an optional Google
image, hosts it on Cloudinary, and saves it beside the assistant's text in chat.

See [recipe planning](docs/recipes.md) for versioned UniTools ingestion, independent
recipe embeddings/search, server-scaled saved plans, reviewed product matching and
complete-basket checks. Recipe tools are always available to the chat agent; import
recipes explicitly after migrations (until then they report `RECIPES_NOT_READY`).
Purchasing through a recipe additionally needs reviewed forms and product evidence.
Recipe search uses the configured Google embedding profile. Dataset import is separate from
the release migration Job and from product-catalog ingestion.
