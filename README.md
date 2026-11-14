# Junction — Main Application

Four-person team repository for [Junction 2026](https://2026.hackjunction.com/), November 13–15 in Espoo, Finland.

Design and infrastructure files for Valio Aimo's [Trusted Trade Agents challenge](https://hackjunction.app/participate/45/challenges/327). The [implementation plan](docs/brief.md) defines one seller-side backend with HTTP/MCP access, catalog ingestion and hybrid search, a React buyer approval inbox/review frontend served by that backend, and mock ordering. It supports conversational or mission-driven external agents. [Terraform infrastructure](infra/README.md) provides an optional DigitalOcean Kubernetes/managed PostgreSQL stack and a separate portable Kubernetes deployment. Nothing is automatically applied. Application implementation is tracked separately in [PR #4](https://github.com/Junction-Best-Team/Main-Application/pull/4).

## Get started

```sh
git clone https://github.com/Junction-Best-Team/Main-Application.git
cd Main-Application
```

All four teammates need write access. Before building, each person should confirm they can clone and push a task branch. New clones start on `develop`, the default integration branch.

## Working in parallel

- Start a task from the latest `develop`: `git switch develop`, then `git pull --ff-only` with a clean working tree. For an existing clone without that branch, first run `git fetch origin` and `git switch --track origin/develop`.
- Use a short task branch, for example `git switch -c otto/map-view`. Do not commit or push directly to `develop` or `main`.
- Say which feature/files you are changing. Coordinate edits to shared APIs, schemas, dependency files, and deployment configuration.
- Check the affected feature works, then open a PR into `develop`: `gh pr create --base develop`. All feature, fix, documentation, and maintenance PRs must target `develop`. Wait for the latest CI run to pass, then self-merge. Human approval is optional; request teammate review for risky authentication, database schema, or shared-interface changes.
- Keep `main` ready to demonstrate. Promote a tested snapshot with a release PR from `develop` to `main` only when a release is explicitly requested. Avoid force pushes to shared branches and preserve teammates' uncommitted work.
- Use a separate checkout/worktree and branch for each concurrent agent on the same machine.

## Lightweight CI

GitHub Actions runs on PRs into `develop` and `main`, and pushes to either branch:

- Python lint: `ruff check src tests scripts`.
- Backend regression tests: `pytest -q` against temporary PostgreSQL/pgvector, using fixture embeddings and supplier responses. Test dependencies come from `uv.lock`; the unused ML stack is pruned to keep installation small.
- Frontend TypeScript checks and production build: `npm ci` then `npm run build` in `frontend`.
- Terraform formatting, validation, mocked plan tests, helper tests and ingress chart rendering when `infra/` or either CI workflow changes.

Backend and frontend jobs run in parallel, dependency downloads are cached, and a new commit cancels outdated PR/develop runs. Main releases are serialized. Components are explicitly skipped only while their application code has not been added; incomplete manifests fail the workflow. No model weights, full catalog imports, Docker builds, browser tests, production credentials, or deployments are needed for PR validation. Run broader demo/browser checks locally when the change warrants them.

The always-present `CI gate` requires successful detection and every applicable application/Terraform check; it accepts a skipped job only when detection says that job is unnecessary. Branch protection requires this gate alongside the three existing application checks on both `develop` and `main`.

Our workflow is **task PR → green CI → self-merge**. Reviews are optional, and the optional `skip-review` label does not bypass CI. The repository is public, and GitHub protects both `develop` and `main`: pull requests and required checks apply even to administrators; force-pushes and branch deletion are blocked. Human approvals are not required. GitHub does not require updating a PR branch after every base-branch change. No special GitHub board is required. Use the team chat to coordinate.

## Build and deploy releases

After a release PR reaches `main` and CI passes, GitHub builds the application Docker image and pushes it to GHCR with a commit tag and immutable digest. Once the cluster is bootstrapped and `DEPLOY_ENABLED=true`, the same release updates the running app and waits for readiness; a failed rollout restores the previous image. Human approval is not required.

Deployment is off until the one-time setup is complete. The application in PR #4 must be merged before an image can be built. Terraform provisioning, database migrations and catalog import remain explicit operator steps. See [the release setup instructions](infra/README.md#simple-main-to-cluster-release-pipeline) for the cluster ID, deployment token, initial public image, and activation switch.

## Planned stack and application setup

| Setting | Value |
| --- | --- |
| Backend | Python, FastAPI, Pydantic, Uvicorn; one application service shared by HTTP and MCP adapters |
| MCP | Official Python MCP SDK; HTTP transport compatible with the selected client |
| Dependencies and packaging | `uv` for Python and a Vite/TypeScript frontend build with committed lockfiles; one Docker image with planned `serve` and `ingest` modes |
| Shared storage | PostgreSQL: separate tables for the derived product index and new proposals, approvals, orders, and receipts |
| Customer rules and approval logic | One seeded demo customer policy/authority configuration in PostgreSQL; read-only policy discovery plus `approval_policy` and `approval_workflow` modules with ready, approval-required, denied and needs-resolution outcomes |
| Hybrid search | pgvector similarity plus PostgreSQL full-text search; reciprocal rank fusion and structured validation |
| Embeddings | Sentence Transformers; evaluate `intfloat/multilingual-e5-small` on Finnish/English catalog queries before pinning a model revision |
| Buyer frontend | React + TypeScript + Vite: login, pending-approvals inbox and purchase review/decision. FastAPI serves built assets and authenticated JSON from the same origin; no separate production frontend server |
| MVP notification path | Buyer independently opens the inbox; bounded refresh while open. Email/SMS/push alerts when closed are deferred; no notifier service |
| Demo client | Existing MCP-capable agent reads effective policy, pauses and checks proposal status; the buyer can approve without an active chat or agent-delivered link |
| Runtime and dependency versions | TBD and pinned with the application skeleton |
| Install command | TBD |
| Local development command | TBD |
| Build / quick validation command | TBD |
| Deployment target | Available Kubernetes cluster: one backend Deployment initially, an on-demand ingestion Job, Service/HTTPS routing, and shared PostgreSQL |
| Deployment procedure and resource values | [Terraform runbook](infra/README.md): one worker, external managed PostgreSQL/pgvector, HTTPS ingress and explicit setup/import Job; alternatively supply an existing cluster/database |
| Demo URL | TBD |

Commit the chosen runtime-version configuration and dependency lockfile with the application skeleton. Then verify that another teammate can get from a fresh clone to a running app using these instructions. Add automated checks only when they save time.

The product has **one running custom service**, not separate search, MCP, approval, and ordering microservices. The importer runs to completion when invoked. PostgreSQL/pgvector is the proposed shared-storage choice for the Kubernetes direction; the earlier SQLite/file-index idea is only a single-instance alternative, not another required implementation. See the plan's [element inventory](docs/brief.md#2-elements-ownership-and-service-count), [ingestion flow](docs/brief.md#4-ingestion-where-the-searchable-data-comes-from), and [deployment diagram](docs/brief.md#10-kubernetes-deployment).

The buying company owns its approval rules. For the MVP, seed one demo customer's spending limit, permitted destinations, substitution/overbuy rules, and agent/approver authority during privileged setup; ordinary serving code has no policy-edit operation. The read-only `get_purchase_policy` tool is included among eight agent tools. Backend modules evaluate policy and enforce authorization again before commitment. Customer settings screens and policy-editing tools are optional later additions. See [customer rules and the approval gate](docs/brief.md#8-customer-rules-backend-approval-gate-and-approval-page).

The [buyer inbox](docs/brief.md#83-react-approval-inbox-and-agent-resume) lists persisted requests independently of the agent. React handles presentation; FastAPI authenticates users, authorizes list/detail/decision requests, and records decisions. Build the frontend in a Node build stage, copy its static output into the Python runtime image, and deploy that same image. Normal audit history stays in PostgreSQL; hash chaining and outbound notification infrastructure are deferred.

## Environment

[.env.example](.env.example) records planned variable names only; no application reads them yet. Supply real values through local ignored files or deployment secrets when the implementation exists. Keep secrets out of commits and browser-side code. Set the public origin used for approval URLs and a private browser-session secret; buyer/agent credential settings will be documented with the chosen authentication implementation. Commit lockfiles; ignore dependencies and generated output.

## Shared context

- [AGENTS.md](AGENTS.md): short instructions shared by coding agents. [CLAUDE.md](CLAUDE.md) imports the same file for Claude Code.
- [Implementation plan](docs/brief.md): core scope, element count, stack, ingestion and updates, shared schemas/evidence, eight tool definitions, customer rules and four policy outcomes, React approval inbox and asynchronous agent resume, concurrency/audit, API findings, Kubernetes diagrams, demo, milestones, and acceptance checks.
- [Pre-existing work](docs/pre-existing-work.md): preparation and reused material to disclose in the submission.

Check the current event and challenge rules before preparing application code. Junction's [general terms](https://www.hackjunction.com/terms-of-service) require projects to be built primarily during the event and pre-existing material to be identified in the submission. Confirm the required project licence before submitting.
