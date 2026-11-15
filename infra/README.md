# Weekend infrastructure

**Separate-app update:** follow [the current cutover runbook](../docs/separate-apps.md).
The Kubernetes stack now creates frontend/API/worker apps. Supply `image` (API),
`worker_image`, and `frontend_image`; the helper requires all three image arguments.
The older monolith rollout narrative below is historical and must not be used for
the one-time cutover. The cloud/database stack remains unchanged.

Terraform provisioning and release helpers. Creating a PR or passing its CI never provisions resources.
Run plans for review; applying a plan is a separate operator action. This work was
prepared without applying either stack.

## Two independent Terraform stacks

| Directory | Responsibility | Portability |
| --- | --- | --- |
| `digitalocean/` | Private VPC, DOKS, managed PostgreSQL 17, restricted database user and firewall | DigitalOcean adapter; replace this stack for another cloud |
| `kubernetes/` | Namespace, app configuration/secrets, Deployment, optional setup Job, HTTPS ingress | Kubernetes + Helm only; accepts any cluster and PostgreSQL endpoint with pgvector |

DigitalOcean is the only cloud implemented for this hackathon. The application
deployment and database protocol are portable so another cloud can be added
later in its own provisioning folder. The two stacks have
separate state and apply lifecycles so Kubernetes providers never initialize
against a cluster that is still being created.

Defaults: Amsterdam, one 2-vCPU/4-GB worker, standard control plane, one managed
2-GB PostgreSQL node, no autoscaling, no NAT gateway, no extra database standby.
The portable stack adds one Traefik LoadBalancer and a 1-GiB certificate volume.
The app starts at **zero replicas** until the database/catalog are ready.

For 30 hours, allow roughly **$3–4 before tax**, and budget $5 at the starting
sizes. This is an estimate, not a spending cap. Registry charges, domain purchase,
AI API usage, excess traffic and longer runtime are separate. Full catalog import
and model inference have not been measured on this node. Increase capacity if
observed resource use requires it. Billing continues until resources are deleted.
Sources: [workers](https://www.digitalocean.com/pricing/droplets),
[database](https://www.digitalocean.com/pricing/managed-databases),
[load balancer](https://www.digitalocean.com/pricing/load-balancers),
[storage](https://docs.digitalocean.com/products/volumes/details/pricing/).

## Prerequisites

- Terraform 1.9+ (CI uses 1.9.8), Python 3, kubectl, and Helm 3 for local checks.
- A DigitalOcean account with billing enabled and an exported `DIGITALOCEAN_TOKEN`.
- An actual public operator/VPN CIDR for Kubernetes API access. The example
  `192.0.2.10/32` is documentation-only and must be replaced before deployment.
- An existing domain/subdomain whose DNS you can point at the load balancer.
  Terraform does not buy a domain or modify unrelated DNS zones.
- The application image from **PR #4**, tagged by commit or digest and built for
  `linux/amd64`. PR #2 supplies the design only; this branch does not duplicate
  PR #4's app code or claim that an image has been published. Merge/build that
  implementation before attempting the Kubernetes rollout. It includes the
  pinned embedding model and static React assets in the same image.
- A registry reachable by the cluster. A public GHCR image requires no pull
  credentials; for a private registry, create an image-pull Secret in the target
  namespace through your secret-management process and set
  `image_pull_secret_names`. No registry subscription is provisioned here.
- The challenge `VALIO_AIMO_API_KEY` for the verified full-catalog download.
  No sponsor API calls are made by validation or CI.

### Token permissions and local secrets

The setup token uses custom resource scopes: `account:read`, `actions:read`,
`regions:read`, `sizes:read`, all `kubernetes` and `database` scopes, all `vpc`
scopes, and tag create/read/delete. No global Full Access, billing, other-user
access, or unrelated Droplet write permissions are needed. Kubernetes manages
its own ingress load balancer through the cluster cloud integration.

Keep the token outside the repository, for example in a private shell env file
with mode 0600, then source it before Terraform commands. `.env.example` documents
the variable name. Revoke the token after teardown; expiry does not stop billing.

Terraform state and saved plans contain generated database credentials,
kubeconfig and Kubernetes Secrets. `sensitive` hides terminal output, not state
contents. This PR uses local state, ignored by Git; restrict its permissions and
use one operator. Before sharing operations across the team, configure an
access-controlled encrypted remote backend with locking for **each** stack and
migrate state. Never commit state, tfvars, kubeconfig or saved plans. There is no
cloud token in PR validation. Release deployment uses a separate GitHub secret
with Kubernetes read, access-cluster and update scopes only; no cloud creation
or deletion permissions are needed for the release workflow.

## Review the cloud plan — safe before provisioning

```sh
umask 077
# Source your private DIGITALOCEAN_TOKEN env file first.
cp infra/digitalocean/terraform.tfvars.example infra/digitalocean/demo.tfvars
# Edit demo.tfvars: replace operator_cidrs with your real operator/VPN CIDRs.
terraform -chdir=infra/digitalocean init
terraform -chdir=infra/digitalocean plan -var-file=demo.tfvars -out=demo.tfplan
```

Inspect the exact resources and prices before applying. The cloud plan contains
eight managed resources: VPC, tag, Kubernetes cluster, PostgreSQL cluster,
database firewall, database, runtime user and catalog-sync user. It does not mutate the account's
existing Droplets or default VPC. Its database firewall trusts only this cluster;
PostgreSQL uses its private endpoint and verified TLS.
Check that the resource names are unused and `vpc_cidr` does not overlap an
existing VPC; override the range in your private tfvars when necessary.

## Later rollout — requires an operator to apply reviewed plans

These steps document the future deployment; none were performed for this PR.

1. Apply the approved cloud plan: `terraform -chdir=infra/digitalocean apply demo.tfplan`.
2. Prepare private portable inputs from the completed cloud outputs:

   ```sh
   python3 infra/scripts/prepare-runtime.py \
     --cloud-directory infra/digitalocean \
     --image ghcr.io/OWNER/IMAGE:api-COMMIT \
     --worker-image ghcr.io/OWNER/IMAGE:worker-COMMIT \
     --frontend-image ghcr.io/OWNER/IMAGE:frontend-COMMIT \
     --hostname aimo.YOUR_DOMAIN \
     --acme-email YOUR_EMAIL
   ```

   The helper writes ignored `kubeconfig.generated.yaml` and
   `runtime.auto.tfvars.json`, both mode 0600. It generates private demo buyer,
   agent and session credentials once and refuses to overwrite existing inputs.
   It never applies Terraform. Add `runtime_secrets = { LLM_API_KEY = ..., VALIO_AIMO_API_KEY = ... }`
   to the private JSON inputs using your secret manager/editor. JSON requires
   the equivalent object syntax. Keep credentials out of command history.

3. Initialize `infra/kubernetes`, then plan and apply its reviewed initial plan:

   ```sh
   terraform -chdir=infra/kubernetes init
   terraform -chdir=infra/kubernetes plan -out=platform.tfplan
   # Operator only, after review:
   terraform -chdir=infra/kubernetes apply platform.tfplan
   ```

   This installs the ingress and app resources with the app stopped. Get the
   ingress address with `kubectl --kubeconfig infra/kubernetes/kubeconfig.generated.yaml
   -n junction-ingress get service junction-ingress-traefik`. Point the chosen
   hostname's A/AAAA record at that address. ACME needs public DNS and port 80.
   Traefik obtains a public certificate, redirects HTTP to HTTPS and preserves
   certificates on its PVC. No separate certificate-manager CRDs are needed.

4. Keep `app_replicas=0`, set `bootstrap_generation="v1"` in the private inputs,
   review the new Kubernetes plan, and apply it. One explicit Job migrates with
   the setup role (enabling pgvector), seeds missing demo identities/policies,
   grants ordinary table/sequence access to the runtime role and catalog-only
   access to the `aimo_catalog_sync` role. It no longer imports products and
   receives no app, provider or supplier Secrets. The Job is never a pod-start hook.
   It stops on any error, and its completed state is kept so later Terraform runs
   do not repeat setup unexpectedly.
   **Populate the catalog** with the scheduled ingestion Job's own template. Set
   `catalog_sync = { enabled = true }` (with `catalog_sync_database_url` and
   `runtime_secrets.VALIO_AIMO_API_KEY`), then apply. Run
   `kubectl -n junction create job aimo-catalog-sync-initial --from=cronjob/aimo-catalog-sync`
   and wait for its JSON result `"outcome": "updated"`. It downloads, checks the
   approved SHA-256 and count, embeds with the same pinned CPU model as serving,
   and activates atomically. See [catalog sync](../docs/catalog-sync.md).
5. Before enabling serving, add `FORWARDED_ALLOW_IPS` to `runtime_secrets` with
   the actual ingress proxy IPs/CIDRs. Never use `*` or a publicly routable
   catch-all network. Ensure ingress replaces untrusted forwarded headers and
   restrict direct application access to trusted proxies. This lets login
   throttling distinguish clients instead of locking every buyer behind one
   ingress address. The plan rejects enabling replicas without explicit proxy
   trust. The application image supplies its own shared model name/revision pin.
   For upgrades from earlier PR #4 revisions, also follow the migration 002,
   prepare-key and privileged product-scope steps in [README](../README.md).
   Migration with an admin role must grant the runtime role access to any new
   tables, including `prepare_requests`; bootstrap's grant step covers them.
   After successful import, set `bootstrap_generation=null`,
   `bootstrap_credentials=null`, and `app_replicas=1`. Plan/apply again. This
   removes the temporary admin/seed Kubernetes Secret and completed setup Job,
   then starts serving with the restricted database role. Keep the private demo
   login credentials in your password manager before removing their local copy.
   Saved old plans/state backups still contain secrets; protect them as above.
6. Check `/health/live` and `/health/ready`, then run PR #4's root/login, chat streaming, exact customer confirmation and
   mock-receipt smoke flow. `upstream_mode="live"` is the default: set
   `runtime_secrets.VALIO_AIMO_API_KEY` before serving (a hosted deployment with `live` or `auto` and no
   key fails at startup: the API lifespan and the worker readiness check refuse to start). Use `upstream_mode="fixture"` only
   as an explicit opt-in for an offline smoke run with mocked supplier price/availability.
   Orders/receipts remain mock acceptance as defined in the application plan.

Routine schema migrations use the [release migration gate](../docs/release-migrations.md).
Routine product-catalog ingestion is the `aimo-catalog-sync` CronJob. It runs
daily while the apps keep serving and skips unchanged snapshots. The earlier
"stop the app to import" rule was a capacity limit, not a correctness limit; see
[catalog sync](../docs/catalog-sync.md#resources-and-capacity) for the measured
cold-import limitation on the single demo node. Use a new setup generation only
when intentionally repeating bootstrap. Renew
the kubeconfig through the provider/CLI when its credentials expire. The helper does not rotate
demo credentials on reruns.

## Simple main-to-cluster release pipeline

`Build and deploy` runs immediately on a push to protected `main`, after the
release PR passes its required `CI gate`. Merged pushes do not repeat PR tests.
Keep the PR-only branch rules and required checks enabled. It builds the frontend,
API and worker Docker targets for
`linux/amd64`, pushes component SHA tags, and records each immutable digest in
the run summary. PRs and pushes to `develop` never publish or deploy.
Docker layers are cached. Main releases are serialized so a new commit cannot
cancel a deployment halfway through. After migrations succeed, all three app
rollouts start before waiting for readiness; a failed rollout still restores
every changed image.
The frontend image bundles production files with Vite; required PR CI still runs
frontend lint, type checks and the production build. Browser tests and documentation
do not invalidate the frontend packaging layer. Unused repository directories stay
out of the Docker build context.

### One-time setup

1. Merge the application and pipeline into `develop`, then release `develop` to
   `main`. Deployment is **off by default**: the first release only builds the
   image. There must be a Dockerfile on `main` before building. To rebuild manually,
   run **Build and deploy** in Actions, select `main`, and leave **deploy** off.
2. Open the new container package's settings and make it **public** so the demo
   cluster can pull it without registry credentials. New GHCR packages start
   private even when the source repository is public. Alternatively configure a
   persistent registry pull Secret through `image_pull_secret_names`. Do not use
   the short-lived Actions token as a cluster image-pull credential.
3. Use the image digest from the run summary in `prepare-runtime.py --image ...`.
   Complete the cloud provisioning and rollout steps above, including DNS,
   database migration/seeding, the first catalog-sync Job, and `app_replicas=1`.
   Verify the demo is healthy before enabling automatic deployment.
4. Create a deployment DigitalOcean token with `kubernetes:read`,
   `kubernetes:access_cluster`, and `kubernetes:update` scopes. Its account must
   have permission to administer the demo cluster. Add it as the repository
   secret **DIGITALOCEAN_TOKEN**. This token is for deployment, not an application
   pod. Set repository variables **DIGITALOCEAN_CLUSTER_ID** (the cloud stack's
   `cluster_id` output), **DEPLOY_NAMESPACE** if different from `junction`, and
   finally **DEPLOY_ENABLED=true**. For example:

   ```sh
   gh secret set DIGITALOCEAN_TOKEN --repo Junction-Best-Team/Main-Application
   gh variable set DIGITALOCEAN_CLUSTER_ID --repo Junction-Best-Team/Main-Application
   gh variable set DEPLOY_ENABLED --body true --repo Junction-Best-Team/Main-Application
   ```

5. Add the challenge key as the repository secret **VALIO_AIMO_API_KEY**:
   `gh secret set VALIO_AIMO_API_KEY --repo Junction-Best-Team/Main-Application`.
   Releases require it, synchronize it into both `aimo-runtime` and
   `aimo-worker-runtime`, set `aimo-config.UPSTREAM_MODE=live`, and disable the
   incompatible demo clock. Both consumers restart when supplier settings change,
   including same-image releases. Local tests can still explicitly use fixtures.
   Reconcile private Terraform inputs to `upstream_mode="live"` before any later
   infrastructure apply; Terraform preserves the release-managed supplier key.
6. Before the first automated migration, provision the dedicated `aimo-migration`
   Secret using `migration_credentials` as described in the
   [operator guide](../docs/release-migrations.md#one-time-credential-provisioning).
   Keep it after removing bootstrap credentials.
7. Run **Build and deploy** manually on `main` with **deploy** checked for the
   first end-to-end deployment. Subsequent checked releases into `main` build and
   deploy automatically. To pause automatic deployment, set `DEPLOY_ENABLED=false`.
   A manual run with **deploy** checked explicitly requests deployment regardless
   of that variable.

The deploy job temporarily adds only its runner's IPv4 `/32` to the existing
DOKS control-plane allowlist, gets a 30-minute kubeconfig, runs a bounded
schema/grant Job using the new API digest, then updates worker/API/frontend to
their published digests and waits for readiness. Cleanup removes that temporary
IP and local kubeconfig even after a rollout failure. If a runner is forcibly
terminated and cleanup cannot run, remove its `/32` through the cloud console
or reapply the cloud stack's operator allowlist. A failed rollout restores the
previous image and leaves the workflow failed. The job refuses to enable a
stopped or unbootstrapped app. After a successful rollout it points an existing
`aimo-catalog-sync` CronJob at the released worker digest; it never creates one.

Terraform owns initial infrastructure/configuration and the first image; it
ignores later Deployment image changes so an infrastructure apply cannot undo
the CI release. Pending schema migrations and restricted runtime grants now run
on every deployment before application image changes, including same-image
releases. They must remain compatible with the previous running app version.
CI never runs Terraform apply, seed, catalog import or profile activation. See
the [operator guide](../docs/release-migrations.md) for failure/retry and credentials.

Rollback can also restore each changed `deployment/aimo-{worker,api,frontend}`
container to its previous digest with `kubectl set image`, followed by its
`kubectl rollout status` check. Image rollback never reverses database migrations.
The deployment uses `Recreate`, so
brief downtime during releases is expected on the single demo worker.

## Another cloud or an existing cluster

Use `infra/kubernetes` unchanged with any cluster kubeconfig, a PostgreSQL URL,
the database CA, a matching image and DNS. The cluster needs dynamic storage and
a LoadBalancer implementation. If ingress already exists, set
`install_ingress=false`, `ingress_class`, `tls_secret_name` and any required
`ingress_annotations`; this avoids a second controller/load balancer. Existing
TLS and registry Secrets must be in the app namespace. An existing database can
be initialized through the same explicit Job, or externally with the application
commands before setting `app_replicas=1`.

To add a cloud later, create a sibling provisioning folder such as `infra/aws/`.
Keep its provider credentials, networking and managed-service resources there.
Expose these five Terraform outputs, each a nonempty string:

| Output | Shared deployment input |
| --- | --- |
| `kubeconfig` | Credentials for the new Kubernetes cluster |
| `database_url` | PostgreSQL URL for the restricted application role |
| `bootstrap_database_url` | Temporary PostgreSQL setup/admin URL |
| `database_user` | Runtime role receiving table/sequence grants |
| `database_ca` | PEM CA certificate for verified database TLS |

Optionally expose both `catalog_sync_database_url` and `catalog_sync_database_user`
(a dedicated role for scheduled catalog ingestion). The helper then writes them
into the private inputs. Without them the CronJob stays disabled.

Select that folder with `prepare-runtime.py --cloud-directory infra/aws ...`.
The helper validates the shared outputs and ignores provider-specific outputs;
`infra/kubernetes/` and the application image do not change. Cloud API keys stay
with the provisioning stack and are never passed to the app. No AWS resources or
placeholder AWS implementation are needed for the current demo.

Both database URLs must use `sslmode=verify-full` and
`sslrootcert=/etc/aimo-db/ca.crt`. For PostgreSQL providers that restrict extension
installation, enable `vector` using the provider's admin process before setup.

## Teardown after the event

Export a database backup first if you need to keep demo records. Plan/destroy
**the Kubernetes stack first**, while its API is reachable. Confirm the Traefik
load balancer and certificate PVC/volume were deleted, then plan/destroy the
DigitalOcean stack. Database deletion is destructive. Check the cloud console
for leftover load balancers, volumes, snapshots, registries or backups and their
charges, and revoke the temporary API token. Do not delete state before teardown.

## Checks

```sh
terraform fmt -check -recursive infra
terraform -chdir=infra/digitalocean init -backend=false
terraform -chdir=infra/digitalocean validate
terraform -chdir=infra/digitalocean test
terraform -chdir=infra/kubernetes init -backend=false
terraform -chdir=infra/kubernetes validate
terraform -chdir=infra/kubernetes test
```

All Terraform tests use mocked providers and `command=plan`. The main CI workflow
calls the Terraform workflow when `infra/` or `.github/` changes (or on a
manual run). Its required, always-present `CI gate` rejects failed, cancelled or
unexpectedly skipped Terraform checks, while unrelated PRs can skip Terraform.
CI validates these checks without credentials, app builds, model downloads or
cloud changes. A green plan does not establish actual cluster capacity, ACME issuance, extension grants,
catalog throughput, or app readiness; those require the later operator rollout.

### Chat purchasing upgrade (2026-11-14)

The existing Deployment, Service, database and ingress remain. Google is now the default for chat, decisions and embeddings: put `GEMINI_API_KEY` in private `runtime_secrets` for the worker and catalog importer, and keep `CLOUDINARY_URL` worker-only. The API selects only the Google key from the worker Secret to mint constrained [voice tokens](../docs/voice.md); each release re-applies that optional reference to `aimo-api`, because releases otherwise change only images; the frontend receives only those temporary tokens. Existing indexes and explicit backend overrides need the coordinated [Google cutover](../docs/google-models.md) before rollout. `llm_model` selects the native chat model; `llm_base_url` and `LLM_API_KEY` are used only with explicit legacy OpenRouter selection. Bootstrap credentials contain only `database_url`, `database_user` and `buyer_password`; historical identities remain for audit and proposal references.

Migration 003 adds persistent chat/turn leases and exact-revision customer confirmations without resetting data or extending product authority. Update the runtime grants for these tables/sequences with the privileged setup role. Runtime identity/policy writes are revoked by bootstrap. Keep trusted proxy CIDRs, secure cookies, probes, frontend-in-image build and existing resource allocations. SSE uses two-second heartbeats and bounded 25-second connections. Traefik's rendered chart has no response-buffering middleware; an existing other ingress must be verified for streaming per `deploy/README.md`. No Terraform apply, deployment or release activation is authorized by the migration.
