# Weekend infrastructure

Terraform configuration only. Creating a PR or passing CI never provisions resources.
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
cloud token or deployment permission in GitHub Actions.

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
seven managed resources: VPC, tag, Kubernetes cluster, PostgreSQL cluster,
database firewall, database and runtime user. It does not mutate the account's
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
     --image ghcr.io/OWNER/IMAGE:COMMIT \
     --hostname aimo.YOUR_DOMAIN \
     --acme-email YOUR_EMAIL
   ```

   The helper writes ignored `kubeconfig.generated.yaml` and
   `runtime.auto.tfvars.json`, both mode 0600. It generates private demo buyer,
   agent and session credentials once and refuses to overwrite existing inputs.
   It never applies Terraform. Add `runtime_secrets = { VALIO_AIMO_API_KEY = ... }`
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
   grants ordinary table/sequence access to the runtime role, then downloads and
   imports the catalog with its original SHA-256 and count checks. It uses the
   same pinned CPU embedding model as serving. The Job is never a pod-start hook.
   Bootstrap may take time; inspect its logs if it fails. It stops on any error,
   does not silently substitute fixtures, and preserves completed Job state so
   later Terraform runs do not unexpectedly repeat setup.
5. After successful import, set `bootstrap_generation=null`,
   `bootstrap_credentials=null`, and `app_replicas=1`. Plan/apply again. This
   removes the temporary admin/seed Kubernetes Secret and completed setup Job,
   then starts serving with the restricted database role. Keep the private demo
   login credentials in your password manager before removing their local copy.
   Saved old plans/state backups still contain secrets; protect them as above.
6. Check `/health/live` and `/health/ready`, then run PR #4's login, MCP and
   approval smoke flow. `upstream_mode="fixture"` is the explicit default for
   mocked supplier price/availability; enable `live` only with working API access.
   Orders/receipts remain mock acceptance as defined in the application plan.

Future migrations/imports require an intentional new setup generation with the
app stopped and temporary setup credentials re-supplied. Renew the kubeconfig
through the provider/CLI when its credentials expire. The helper does not rotate
demo credentials on reruns.

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
calls the Terraform workflow when `infra/` or either CI workflow changes (or on a
manual run). Its required, always-present `CI gate` rejects failed, cancelled or
unexpectedly skipped Terraform checks, while unrelated PRs can skip Terraform.
CI validates these checks without credentials, app builds, model downloads or
cloud changes. A green plan does not establish actual cluster capacity, ACME issuance, extension grants,
catalog throughput, or app readiness; those require the later operator rollout.
