# Valio Aimo purchasing gateway

One seller-side FastAPI service exposes eight HTTP/MCP tools, serves a React buyer approval inbox, and commits **persistent mock orders**. PostgreSQL stores the catalog index, versioned buyer policy, identities, immutable proposal revisions, approvals, audit events and receipts. The buyer's purchasing agent is external.

The agreed scope is in [docs/brief.md](docs/brief.md). PR #2 was **closed without merging** before implementation; this branch starts from `main` at `76296c1`, preserves PR #3's reference documents, and implements the attached PR #2 brief. `Plan/post-mvp-plan.md` is a separate draft, not the implementation contract. See [actual validation and limitations](docs/validation.md).

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

The first import downloads the pinned `intfloat/multilingual-e5-small` model and embeds the catalog on CPU. Subsequent imports reuse unchanged text embeddings. Publication is atomic: failures leave the old generation active. Updated snapshots require an explicitly verified `--expected-count` and `--expected-sha256`. There is no import on requests or startup. Prior generations remain available for audit/debugging; storage retention is an operator task.

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

Use `Authorization: Bearer <private agent token>` for HTTP and stateless Streamable HTTP MCP at `/mcp/`. MCP tool arguments use a typed `request` object where applicable; product/proposal/order lookups take their identifier directly. Every tool checks the credential and buyer scope. Proposals and orders are additionally scoped to their creating agent. The demo uses preconfigured bearer credentials, not OAuth discovery. Interactive OpenAPI documentation is at `/docs`. [Examples](docs/examples/requests.json) contain no credentials. `uv run python scripts/mcp_smoke.py` runs the official SDK client against the server.

The browser uses `/login`, `/approvals`, `/approvals/{approval_id}`, and separate `/api/login`, `/api/session`, `/api/logout`, `/api/approvals` and decision routes. Sessions are signed, persisted, HttpOnly, SameSite Strict and expiring. State changes require an exact configured Origin and session-bound CSRF header. Buyer passwords use Argon2; API tokens and session lookup tokens are hashed. Login attempts are rate-limited in PostgreSQL. The URL grants no authority. Inbox pagination is bounded; refresh pauses while hidden. There is no email/push notifier or claim of delivery.

Policy is seeded in PostgreSQL, versioned and read-only at runtime. The demo autonomous gross limit is €1,500; the buyer can approve up to €5,000 for spend, substitution and overbuy exceptions. Only `hotel-helsinki` is allowed. Mission budgets and permissions can tighten these rules. Whole discrete sales units are an **explicit buyer rule**, retaining the source lot step. Unknown conversions, variable weight, conflicting dietary evidence, missing costs, uncertain supplier stock and passed cutoffs cannot be fixed by approval.

Commit re-fetches commercial evidence outside the transaction, then locks the buyer, current identities and proposal in a consistent order. Changed commercial terms or policy version create a new immutable revision and invalidate earlier approval. Current approver and agent authority are checked again. Unique database constraints enforce one order per proposal and one payload per buyer/idempotency key. A completed authenticated retry returns its saved receipt before querying upstream. Privileged authority/policy maintenance must take the same buyer lock before changing identity rows/current policy; insert a policy version instead of updating history. Ordinary HTTP/MCP provides no maintenance action. See the module docstrings and SQL migration for this protocol.

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

Tests require a PostgreSQL role permitted to create `aimo_test`, or an existing database named with `_test` and `TEST_DATABASE_URL` configured. Tests refuse to clear a database without that suffix. Browser tests create mock purchases in the demo database. `BASE_URL` selects a browser-test origin; `DEMO_BASE_URL` selects the reference/MCP clients. [Validation](docs/validation.md) records actual outcomes and the limited 30-case retrieval evaluation.

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
