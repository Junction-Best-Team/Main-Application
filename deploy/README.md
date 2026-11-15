# Deploying the separate apps

Use [the separate-app runbook](../docs/separate-apps.md) for the one-time cutover,
rollback, independent image builds and durable queue behavior. The portable
Terraform stack is authoritative for the existing Junction installation.

`kubernetes.yaml` is an alternative template for an existing environment: it
contains three Deployments and Services plus one path-routing Ingress. Replace
all image/hostname/class placeholders, and supply `aimo-config`, `aimo-runtime`
(API credentials), `aimo-worker-runtime` (worker credentials), and
`aimo-database-ca` first. API credentials include database URL, session key and
supplier key if used; worker credentials include database URL, LLM key and
supplier key if used. The frontend receives no secrets. Use the Terraform
configuration as the reference for non-secret configuration fields and trusted
proxy addresses; never use `FORWARDED_ALLOW_IPS=*`.

Apply migrations with a setup role before enabling API/worker. Keep existing
runtime grants and database/catalog contents. Catalog ingestion runs in its own
temporary pod from the **worker image** with `sync-catalog`, scheduled by a CronJob;
it is never a pod-start hook and never runs inside the API or worker.
`catalog-sync-cronjob.yaml` is the template for this alternative path; it needs the
dedicated `aimo-catalog-sync` Secret described there and in
[catalog sync operations](../docs/catalog-sync.md).

The frontend runs as UID 101, API/worker as UID 10001, with non-root restricted
security contexts and read-only roots. Requests total 650m CPU and 1,248 MiB
memory for the three apps; limits are starting budgets, not measured capacity.
Each backend process has its own bounded database pool; budget connections when
scaling replicas. Worker shutdown allows 240 seconds for its bounded current turn.

Traefik routes API/SSE directly to the API Service. Keep buffering disabled and
retain `X-Accel-Buffering: no`. SSE sends stored snapshots/heartbeats every two
seconds and reconnects within 25 seconds. The frontend uses same-origin relative
API URLs, so authentication/CSRF semantics remain unchanged.

For releases, the optional repository secret `LLM_API_KEY` and variables
`LLM_BASE_URL`/`LLM_MODEL` synchronize only into `aimo-worker-runtime` through
kubectl stdin. The defaults remain OpenRouter (`https://openrouter.ai/api/v1`,
`openai/gpt-4.1-mini`). Missing repository credentials preserve existing settings.
Terraform ignores release-managed changes to those three worker Secret fields;
it continues to own database/supplier configuration. Same-image provider changes
restart only the worker. Builds/PR checks never use these credentials. Image
rollback does not restore provider configuration; restore that separately if needed.

For hosted search, apply `005_hosted_search.sql`, then follow the [staged import and coordinated API/worker cutover](../docs/hosted-search.md). Only the worker/importer receives `SEARCH_API_KEY`; both API and worker use the matching embedding profile.
