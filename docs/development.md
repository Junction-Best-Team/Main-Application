# Local development

Start with the [README setup](../README.md#local-setup). It creates the environment,
database, schema, demo buyer and product catalog. Never reset an existing database
to upgrade it: run `uv run aimo migrate` with the setup role and follow
[release migrations](release-migrations.md) for runtime grants.

## Run with frontend hot reload

Stop the Compose app services if they are running, keeping the database available:

```sh
docker compose --profile app stop frontend api worker
npm ci --prefix frontend
```

Set `PUBLIC_BASE_URL=http://localhost:5173` in your private `.env`, then run each
command in a separate terminal:

```sh
uv run aimo serve
uv run aimo worker
npm run dev --prefix frontend
```

Open [localhost:5173](http://localhost:5173/). Vite proxies `/api` to the API;
the worker consumes persisted chat jobs. Restore `PUBLIC_BASE_URL` to
`http://localhost:8000` when switching back to Compose. Local HTTP uses
`SECURE_COOKIES=false`; hosted deployments require HTTPS and secure cookies.
See [.env.example](../.env.example) for configuration names and defaults.

## Import data explicitly

Instead of downloading with `sync-catalog`, import a private local snapshot:

```sh
uv run aimo ingest --file /absolute/path/valio_aimo_junction26_product_data.json
```

The default count and SHA-256 identify the approved 17,546-product snapshot.
Changed snapshots require explicitly verified `--expected-count` and
`--expected-sha256` values. Imports use the configured embedding provider and
reuse unchanged text embeddings; uncached Google embeddings consume quota/credits.
Publication is atomic, leaving the previous active catalog available on failure.
There is no import during startup or a customer request. See
[catalog sync](catalog-sync.md) for locking, retention and scheduled imports.

`uv run aimo fixture-catalog` loads a small authored catalog. For deterministic
fake embeddings, also set `EMBEDDING_BACKEND=fixture` for both import and serving.
This supplies neither prices nor stock: application entry points require the real
`VALIO_AIMO_API_KEY`. `UPSTREAM_MODE=live` is the default, legacy `auto` also means
live, and application entry points refuse `fixture`. Search first, then look up
only shortlisted products. Historical fixture evidence stays labelled.

The offline [test harness](../tests/README.md) supplies its own explicit supplier
fixtures. Use `tests/ci.sh` to check the app without paid provider calls or keys.

Recipe data is imported separately; see [recipes](recipes.md). Existing installations
must follow the [Google model/index cutover](google-models.md) when changing
embedding profiles; configuration changes cannot reuse incompatible vectors.
The [OpenRouter profile](hosted-search.md) is an explicit legacy option.

## Update the browser API contract

Python owns the schema. After changing an API shape, export it and regenerate
the browser types:

```sh
uv run python scripts/export_schema.py
npm run types --prefix frontend
npm run build --prefix frontend
```

For local interactive API documentation, set `API_DOCS_ENABLED=true` and open
`http://localhost:8000/docs`. Keep it disabled on hosted deployments. Credential-free
[request examples](examples/requests.json) illustrate purchasing payloads.
See [frontend development](../frontend/docs/development.md) for feature ownership,
typed requests and UI conventions.

## Verify a change

```sh
uv run ruff check src tests scripts
tests/ci.sh
npm run build --prefix frontend
```

The hermetic script owns its fixture database. Direct `uv run pytest -q` needs a
PostgreSQL role allowed to create `aimo_test`, or a configured `TEST_DATABASE_URL`
whose database name ends in `_test`. See [tests and CI](../tests/README.md) and
[frontend browser testing](../frontend/docs/testing.md) for isolated integration,
browser, restart and live-read checks. CI does not call paid models or the supplier.

For a manual chat demo, `uv run python scripts/demo.py` authenticates as the buyer
against the running app. Complete clarification in the same saved conversation:

```sh
uv run python scripts/demo.py --conversation <uuid> --message "Delivery 2026-11-16, hotel-helsinki, no dietary restrictions, budget EUR 1000"
```

Review and confirm the exact basket inside the product. Demo orders remain mocks.

## Containers and operations

`docker compose --profile app up --build` builds the `frontend`, `api` and `worker`
Docker targets. The frontend serves assets with Nginx; the API excludes model
weights. The worker uses Google by default; local E5 model weights are an explicit
build option. Each service exposes health checks. See [app operations](separate-apps.md),
[deployment](../deploy/README.md), [release setup](../infra/README.md#simple-main-to-cluster-release-pipeline)
and [safe operational logging](logging.md). Keep provider credentials server-side.
