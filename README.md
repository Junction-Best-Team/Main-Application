# Junction — Main Application

Four-person team repository for [Junction 2026](https://2026.hackjunction.com/), November 13–15 in Espoo, Finland.

Preparation and design files for Valio Aimo's [Trusted Trade Agents challenge](https://hackjunction.app/participate/45/challenges/327). The [implementation plan](docs/brief.md) defines one seller-side backend with HTTP/MCP access, catalog ingestion and hybrid search, a minimal buyer approval page served by that backend, and mock ordering. It supports conversational or mission-driven external agents. Kubernetes is the intended hosting target. Application code and deployment resources are not implemented yet.

## Get started

```sh
git clone https://github.com/Junction-Best-Team/Main-Application.git
cd Main-Application
```

All four teammates need write access. Before building, each person should confirm they can clone and push a task branch.

## Working in parallel

- Start a task from the latest `main`: `git switch main`, then `git pull --ff-only` with a clean working tree.
- Use a short task branch when working in parallel, for example `git switch -c otto/map-view`. A small coordinated change can go directly to `main`.
- Say which feature/files you are changing. Coordinate edits to shared APIs, schemas, dependency files, and deployment configuration.
- Check the affected feature works, then integrate small changes frequently. You can merge your own work; PRs and reviews are optional.
- Keep `main` ready to demonstrate. Avoid force pushes to shared branches and preserve teammates' uncommitted work.
- Use a separate checkout/worktree and branch for each concurrent agent on the same machine.

No required pipelines, approval gates, or special GitHub board. Use the team chat to coordinate.

## Planned stack and application setup

| Setting | Value |
| --- | --- |
| Backend | Python, FastAPI, Pydantic, Uvicorn; one application service shared by HTTP and MCP adapters |
| MCP | Official Python MCP SDK; HTTP transport compatible with the selected client |
| Dependencies and packaging | `uv` with committed lockfile; one Docker image with planned `serve` and `ingest` modes |
| Shared storage | PostgreSQL: separate tables for the derived product index and new proposals, approvals, orders, and receipts |
| Hybrid search | pgvector similarity plus PostgreSQL full-text search; reciprocal rank fusion and structured validation |
| Embeddings | Sentence Transformers; evaluate `intfloat/multilingual-e5-small` on Finnish/English catalog queries before pinning a model revision |
| Human interface | Minimal server-rendered approval page using FastAPI/Jinja2, served by the same backend; no standalone frontend service or React build |
| Demo client | Existing MCP-capable agent receives an approval URL and checks proposal status; direct in-agent approval is optional |
| Runtime and dependency versions | TBD and pinned with the application skeleton |
| Install command | TBD |
| Local development command | TBD |
| Build / quick validation command | TBD |
| Deployment target | Available Kubernetes cluster: one backend Deployment initially, an on-demand ingestion Job, Service/HTTPS routing, and shared PostgreSQL |
| Deployment procedure and resource values | TBD with actual cluster, registry, database, and domain access; no new cluster or database operator in application scope |
| Demo URL | TBD |

Commit the chosen runtime-version configuration and dependency lockfile with the application skeleton. Then verify that another teammate can get from a fresh clone to a running app using these instructions. Add automated checks only when they save time.

The product has **one running custom service**, not separate search, MCP, approval, and ordering microservices. The importer runs to completion when invoked. PostgreSQL/pgvector is the proposed shared-storage choice for the Kubernetes direction; the earlier SQLite/file-index idea is only a single-instance alternative, not another required implementation. See the plan's [element inventory](docs/brief.md#2-elements-ownership-and-service-count), [ingestion flow](docs/brief.md#4-ingestion-where-the-searchable-data-comes-from), and [deployment diagram](docs/brief.md#10-kubernetes-deployment).

## Environment

[.env.example](.env.example) records planned variable names only; no application reads them yet. Supply real values through local ignored files or deployment secrets when the implementation exists. Keep secrets out of commits and browser-side code. Set the public origin used for approval URLs and a private browser-session secret; buyer/agent credential settings will be documented with the chosen authentication implementation. Commit lockfiles; ignore dependencies and generated output.

## Shared context

- [AGENTS.md](AGENTS.md): short instructions shared by coding agents. [CLAUDE.md](CLAUDE.md) imports the same file for Claude Code.
- [Implementation plan](docs/brief.md): core scope, element count, stack, ingestion and updates, tool schemas, the approval page and asynchronous agent resume, data checks, Kubernetes diagrams, demo, milestones, and acceptance checks.
- [Pre-existing work](docs/pre-existing-work.md): preparation and reused material to disclose in the submission.

Check the current event and challenge rules before preparing application code. Junction's [general terms](https://www.hackjunction.com/terms-of-service) require projects to be built primarily during the event and pre-existing material to be identified in the submission. Confirm the required project licence before submitting.
