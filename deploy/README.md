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
runtime grants and database/catalog contents. Ingestion uses the **worker image**
with an explicit `ingest` command and existing catalog volume; it is never a
pod-start hook. `ingest-job.yaml` remains a manual template and needs environment-
specific database CA/configuration mounts and a writable temporary volume.

The frontend runs as UID 101, API/worker as UID 10001, with non-root restricted
security contexts and read-only roots. Requests total 650m CPU and 1,248 MiB
memory for the three apps; limits are starting budgets, not measured capacity.
Each backend process has its own bounded database pool; budget connections when
scaling replicas. Worker shutdown allows 120 seconds for its bounded current turn.

Traefik routes API/SSE directly to the API Service. Keep buffering disabled and
retain `X-Accel-Buffering: no`. SSE sends stored snapshots/heartbeats every two
seconds and reconnects within 25 seconds. The frontend uses same-origin relative
API URLs, so authentication/CSRF semantics remain unchanged.
