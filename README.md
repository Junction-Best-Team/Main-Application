# Junction — Main Application

Four-person team repository for [Junction 2026](https://2026.hackjunction.com/), November 13–15 in Espoo, Finland.

Preparation and design files for Valio Aimo's [Trusted Trade Agents challenge](https://hackjunction.app/participate/45/challenges/327). The [implementation plan](docs/brief.md) describes a seller-side purchasing gateway that external agents use to discover products, prepare valid orders, and obtain the required approval. Application code is not implemented yet; deployment is undecided.

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
| Backend | Python / FastAPI; one application service shared by HTTP and MCP adapters |
| Storage and search | SQLite with full-text search; local multilingual embedding matrix |
| Human interface | React for proposal review, approval, and order receipts |
| Demo client | Existing MCP-capable external agent; no custom buyer-agent application required |
| Runtime versions, package managers, and embedding model | TBD during the application skeleton and retrieval evaluation |
| Install command | TBD |
| Local development command | TBD |
| Build / quick validation command | TBD |
| Deployment service and procedure | TBD |
| Demo URL | TBD |

Commit the chosen runtime-version configuration and dependency lockfile with the application skeleton. Then verify that another teammate can get from a fresh clone to a running app using these instructions. Add automated checks only when they save time.

## Environment

Document required variable names and safe placeholders in [.env.example](.env.example). Use real values only in the local environment file expected by the stack and the deployment service's environment settings. Keep secrets out of commits and browser-side code. Commit lockfiles; ignore dependencies and generated output.

## Shared context

- [AGENTS.md](AGENTS.md): short instructions shared by coding agents. [CLAUDE.md](CLAUDE.md) imports the same file for Claude Code.
- [Implementation plan](docs/brief.md): scope, data handling, proposed interfaces, controls, demo, milestones, and acceptance checks.
- [Pre-existing work](docs/pre-existing-work.md): preparation and reused material to disclose in the submission.

Check the current event and challenge rules before preparing application code. Junction's [general terms](https://www.hackjunction.com/terms-of-service) require projects to be built primarily during the event and pre-existing material to be identified in the submission. Confirm the required project licence before submitting.
