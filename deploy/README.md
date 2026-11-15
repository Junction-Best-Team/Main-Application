# Deploying the separate apps

See [app operations](../docs/separate-apps.md) for independent image builds,
durable queue behavior and release recovery. The portable
Terraform stack is authoritative for the existing Junction installation.

`kubernetes.yaml` is an alternative template for an existing environment: it
contains three Deployments and Services plus one path-routing Ingress. Replace
all image/hostname/class placeholders, and supply `aimo-config`, `aimo-runtime`
(API credentials), `aimo-worker-runtime` (worker credentials), and
`aimo-database-ca` first. API credentials include database URL, session key and
required supplier key and Google key for voice; worker credentials include
database URL, provider key and required supplier key. The frontend receives no secrets. Use the Terraform
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
scaling replicas. Worker shutdown allows 660 seconds for its bounded current turn.
For an existing cluster, update the worker image together with (or before enabling)
the longer-turn configuration: worker shutdown grace of 660 seconds and `aimo-config` values
`LLM_TURN_TIMEOUT_SECONDS=600` and `LLM_MAX_TOOL_ROUNDS=80`, as defined in Terraform.
Check for older overrides in worker environment variables/Secrets. Image-only
releases do not apply these settings; the release waits up to 15 minutes for the
worker rollout and rollback.

Traefik routes API/SSE directly to the API Service. Keep buffering disabled and
retain `X-Accel-Buffering: no`. SSE sends stored snapshots/heartbeats every two
seconds and reconnects within 25 seconds. The frontend uses same-origin relative
API URLs, so authentication/CSRF semantics remain unchanged.

For provider configuration, follow [Google model settings and index cutover](../docs/google-models.md)
and [operational logging](../docs/logging.md). API, worker and catalog-sync must use
matching embedding profiles. Provider keys remain server-side; Cloudinary credentials
are worker-only. Legacy OpenRouter search remains an explicit opt-in described in
[hosted search](../docs/hosted-search.md).

Routine releases run the [migration/grant Job](../docs/release-migrations.md) before
updating images. The [infrastructure release procedure](../infra/README.md#simple-main-to-cluster-release-pipeline)
covers repository secrets, deployment activation and rollback limits. Image rollback
does not restore provider configuration or undo schema migrations.
