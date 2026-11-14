# Deployment into an existing environment

Build/push the application image to the team's existing registry. Replace `registry.example.invalid/aimo:REPLACE_WITH_COMMIT`, the hostname, TLS secret and catalog PVC in the manifests. Apply in an explicitly selected existing namespace. This repository does not create a cluster, database operator, registry or paid resource.

Create an existing Secret named `aimo-runtime` through your normal secret-management channel. It supplies `DATABASE_URL`, `PUBLIC_BASE_URL`, `APPROVAL_SESSION_SECRET`, `SECURE_COOKIES=true`, `UPSTREAM_MODE`, `VALIO_AIMO_API_KEY` if live, `EMBEDDING_BACKEND=sentence_transformers`, and `FORWARDED_ALLOW_IPS`. The model and revision default to the single pin in `src/aimo/model_spec.py`; overrides must match the imported catalog. Seed credentials `DEMO_AGENT_TOKEN` and `DEMO_BUYER_PASSWORD` are needed only for the setup invocation. Do not put secrets in these manifests or Vite environment variables.

Set `FORWARDED_ALLOW_IPS` to the actual ingress proxy addresses/CIDRs (never `*`). The ingress must replace untrusted client-supplied forwarded headers, and application ingress should be limited to that proxy. Uvicorn then exposes the verified client address to login throttling instead of grouping everyone under the ingress address. The template cannot guess the cluster's proxy network. Requests from an untrusted peer cannot choose their identity via `X-Forwarded-For`.

1. Run the image with `migrate` once, using the privileged schema-setup database role.
2. Run `seed` once with the private demo credentials. It only inserts missing rows. Reruns preserve policy versions, limits, authority and credentials. Rotation is a privileged operation, not a seed overwrite.
3. Mount the verified complete catalog and run `ingest --file /data/valio_aimo_junction26_product_data.json` as the manual Job. The default expected hash/count match the supplied snapshot. Do not alter those checks to accept an interrupted or partial download.
4. Apply `kubernetes.yaml` after the index is ready. Configure the existing ingress class and TLS controller for the team's environment. One replica is intentional; stateless MCP and PostgreSQL transactions support later scaling, but resource capacity/load is not established.
5. Confirm liveness, readiness, login, MCP transport, pending approval and mock receipt using the scripts in the repository. Readiness checks the database, active embedding model key and model load, never supplier availability.

For upgrades from earlier PR #4 revisions, migration `002_review_hardening.sql` adds preparation idempotency and lookup/cleanup indexes. Existing policies need explicit product-scope provisioning: run `set-product-scope --buyer demo-hotel --product-id 464306` using the setup role, repeating the product flag only for products the buyer has authorized. This inserts a new policy version under the buyer lock; existing policy history is preserved. Missing scope makes restricted purchases unresolved. New prepare requests must include `idempotency_key`; old stored proposals remain readable.

Local full-catalog container import, after `docker compose up -d --wait db` and image build:

```sh
docker compose --profile app run --rm -v /absolute/private/catalog-directory:/data:ro app ingest --file /data/valio_aimo_junction26_product_data.json
```

CPU/memory values are starting settings, not cluster measurements. The image runs as UID/GID 10001; the Deployment has a read-only root and a temporary `/tmp` volume. Model weights are baked into the image and loaded offline. PostgreSQL data must remain on existing durable storage. Apply migrations as a separate operation before serving; no startup seeding or ingestion is performed.

Keep database credentials private. The local demo role owns the schema for ease of setup; use appropriately restricted runtime credentials in a hosted environment. Policy revisions, proposal revisions and audit events reject UPDATE/DELETE through database triggers. Privileged policy/authority changes must lock `buyers` first, then affected `identities` in ID order; do not bypass the concurrency protocol described in `approval_workflow.py`.

Each process has a bounded PostgreSQL pool (`DB_POOL_MAX_SIZE=10`, `DB_POOL_TIMEOUT_SECONDS=5`, at most 50 waiting acquisitions). Budget database connections across replicas and one-off ingestion/setup jobs. This is connection reuse, not a measured load-capacity claim. `/health/live` is asynchronous and does not acquire a database connection; synchronous MCP authentication and business work run in workers.

Imports retain the active and previous generation's product/vector rows by default (`CATALOG_GENERATIONS_TO_KEEP=2`, configurable 1–10). Exact filtered ranking avoids HNSW scan-limit recall loss for the MVP; reassess the query plan and latency before a much larger catalog. Generation metadata, embedding cache and purchase/audit history remain; their long-term retention and PostgreSQL vacuuming remain operator concerns. Identity federation, real order acceptance/reconciliation, and real delivery charges remain future integration work.
