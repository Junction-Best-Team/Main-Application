# Release database migrations

Routine releases build/publish all three immutable images, run a fresh migration
Job from the **new API image digest**, wait for its schema/grant transaction to
commit, and only then change worker/API/frontend images and check readiness.
This also runs on same-image releases. API/worker startup never runs migrations.
The API Docker target already packages `aimo`, `migrations/`, psycopg and the shared
runtime-grant helper; it needs neither model weights nor catalog credentials.

## One-time credential provisioning

Before the first automated migration, an operator must review/apply the Kubernetes
infrastructure wiring in this change. This task does not perform that apply.

- New installations: `infra/scripts/prepare-runtime.py` reads the existing
  sensitive cloud outputs into mode-0600 private inputs. It now sets
  `migration_credentials.database_url` from `bootstrap_database_url`, and
  `.database_user` from `database_user` (the **restricted runtime role name**).
- Existing installations: add the same `migration_credentials` object to the
  existing private `runtime.auto.tfvars.json` using your secret manager/editor.
  Obtain values from the existing protected cloud outputs; do not print them,
  commit them, or supply them as literal shell arguments. Do not regenerate or
  overwrite the existing session/buyer/provider credentials.
- The URL must use `sslmode=verify-full&sslrootcert=/etc/aimo-db/ca.crt` and connect
  directly to the same database as the runtime URL. On the current DigitalOcean
  stack this is the existing `doadmin` setup/schema-owner credential: it owns the
  bootstrap-created objects and can grant their access. A replacement dedicated
  owner requires an operator-reviewed ownership/grant transfer first. Do not use
  the runtime role as owner or give the runtime role membership in the owner role.
- Terraform creates **`aimo-migration`**, containing `DATABASE_URL` and
  `RUNTIME_DATABASE_USER`. Only release migration Jobs reference it. Ordinary API
  and worker pods keep their existing restricted URLs; the frontend has none.
  No database password is added to GitHub Actions. Existing `aimo-database-ca`
  supplies the CA; registry pull Secrets are copied from the API pod template.
- Keep `migration_credentials` after initial bootstrap. Removing
  `bootstrap_generation`/`bootstrap_credentials` still removes the temporary
  seed/admin bootstrap Secret and Job; it does not remove the release Secret.
  The initial bootstrap remains an explicit operator action and still seeds and
  imports. Routine releases never invoke it.

Review the Terraform plan with protected state access, then apply it as a separate
operator action. State, saved plans, old backups and private inputs contain secret
values even when Terraform marks them sensitive; keep the existing protections.
Rotate the owner credential in the provider and protected inputs/Secret together.
Verify the Secret **exists by name**, app pods reference only their runtime Secrets,
and namespace/registry/CA wiring matches before enabling releases. CI's cluster
principal needs create/get/delete Jobs, get deployments/pods and pod-log access;
app service accounts have no mounted API token. A missing or invalid Secret fails
the migration gate and leaves application images unchanged.

## Normal release

Use the existing main release workflow and deployment switch. GitHub serializes
releases and always removes temporary cluster access/local kubeconfig afterward.
`deploy-app.sh` first verifies all three apps are enabled, then invokes
`migrate-release.py`, before its first image mutation or provider-driven restart.
The Job runs only `aimo migrate --runtime-role ...`: no demo seed, catalog or
recipe import, embeddings, or search-profile activation.

The existing PostgreSQL transaction advisory lock (`893018`) serializes all
runner callers, including bootstrap and manual `aimo migrate`. The full filename
is the `schema_migrations` key. SQL, ledger inserts and runtime grants commit
atomically; a failed grant also rolls back the pending SQL/ledger. Applied files
are logged and skipped; do not modify/rename an applied migration. The runner
fails if no migration files are packaged. All migration files must be transactional.

Grants cover new public tables (SELECT/INSERT/UPDATE/DELETE) and sequences
(USAGE/SELECT), then revoke ledger access and identity/policy provisioning writes
on `buyers`, `identities`, `policies`, and `internal_agents`. Existing identifier-only
lock grants and update guards are retained. This refresh occurs in the same
transaction, including when no SQL is pending; privileges are never committed in
a temporarily broadened state. Do not put non-application tables in `public` if
they should not receive these ordinary application grants.

## Failure and retry

The Job has no automatic retries, a 300-second server deadline, 240-second SQL
statement timeout (including advisory-lock waits), and a 360-second client wait.
Each kubectl request/process is bounded. Success logs are collected and the Job
is deleted. Failed Jobs/logs are retained for a 24-hour TTL; the run prints their
unique name. Inspect with `kubectl -n junction logs job/NAME` and
`kubectl -n junction get job NAME`. Do not dump Secrets during diagnosis.
These deadline and TTL fields use the standard [Kubernetes Job controls](https://kubernetes.io/docs/concepts/workloads/controllers/job/).

A client/API error or waiter timeout fails the release and attempts to delete the
active Job. If the runner disappears, the server deadline and finished-Job TTL
still bound execution/retention. A connection loss can make commit acknowledgement
ambiguous: inspect the ledger using approved operator access, then retry the
workflow; the lock/ledger safely skip committed files. Each retry gets a fresh Job,
including retries of the same image. Do not blindly delete ledger entries.

Fix the SQL/credentials/capacity issue and rerun the release. On SQL or grant
failure the transaction rolls back. Application images are untouched. Existing
cluster cleanup still runs. A later application rollout failure restores changed
component images using the existing recovery path and keeps the release failed.

## Compatibility and rollback

**Existing application pods keep running during migrations.** Every release
migration must work with the previous application version as well as the new one.
Use additive/expand-and-contract changes and account for database lock duration;
review destructive or long-running changes separately. Existing legacy migration
`004_worker_queue.sql` is part of the one-time separate-app cutover, whose own
runbook remains authoritative; routine automation does not make old incompatible
cutovers safe on arbitrary earlier app versions.

Application image rollback never reverses database migrations or ledger entries.
Use the previous compatible image digests and existing rollout checks. Database
restoration or compensating forward SQL is a separate reviewed operator operation;
never run the full bootstrap as a migration retry or rollback.

PR #34 was rechecked at `7e702bd`: it now uses `005_hosted_search.sql`, after
develop's `004_worker_queue.sql`. Hosted-search migration changes do not import
or activate a catalog. This task adds no numbered SQL, recipe tables, or
assumptions about a next migration number. Coordinate filenames/dependencies
before merge; the runner uses complete filenames rather than numeric prefixes.

## Verification boundary

Validation on 2026-11-14: 197 backend tests passed against a dedicated local
PostgreSQL/pgvector database. The built API image also ran migrations/grants twice
with a read-only filesystem against a disposable local test database: four files
applied once, rerun skipped all four, restricted grants remained in place, and
buyers/products stayed empty. No ML dependencies were installed in that image.

The 37 infrastructure tests passed with mocked kubectl/provider calls. The Job
controller, Secret/deadline/TTL wiring and rollout failure/recovery are checked
with mocked kubectl and Terraform **mock-provider plans**, plus static workflow
and shell checks, plus both Terraform validations, 14 mock-plan tests, Helm
chart rendering, Python lint/format, and the frontend TypeScript/production build.
These are not a Kubernetes execution, production migration,
Terraform apply, or deployment. First live execution remains an operator release.
