# Junction — Main Application

Four-person team repository for [Junction 2026](https://2026.hackjunction.com/), November 13–15 in Espoo, Finland.

Challenge: **Trusted Trade Agents (Valio Aimo)** — the Aimo-side interface for external purchasing agents. The stack, application, and deployment target are still to be selected.

## Get started

```sh
git clone https://github.com/Junction-Best-Team/Main-Application.git
cd Main-Application
```

All four teammates need write access. Before building, each person should confirm they can clone and push a task branch. Publish the preparation files first so everyone starts from the same commit.

## Working in parallel

- Start a task from the latest `main`: `git switch main`, then `git pull --ff-only` with a clean working tree.
- Use a short task branch when working in parallel, for example `git switch -c otto/map-view`. A small coordinated change can go directly to `main`.
- Say which feature/files you are changing. Coordinate edits to shared APIs, schemas, dependency files, and deployment configuration.
- Check the affected feature works, then integrate small changes frequently. You can merge your own work; PRs and reviews are optional.
- Keep `main` ready to demonstrate. Avoid force pushes to shared branches and preserve teammates' uncommitted work.
- Use a separate checkout/worktree and branch for each concurrent agent on the same machine.

No required pipelines, approval gates, or special GitHub board. Use the team chat to coordinate.

## Application setup — fill in once the stack is chosen

| Setting | Value |
| --- | --- |
| Stack, runtime version, and package manager | TBD |
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
- [Project brief](docs/brief.md): the user, three essential features, demo, and agreed interfaces.
- [Architecture and tracks](docs/architecture.md): the four tracks, the contracts between them, and who raises issues against whom.
- [Findings](docs/findings.md): verified facts, traps and owner decisions, with evidence. Add to it as you learn.
- [Cross-track issues](docs/issues.md): what one track needs from another.
- [History](docs/history/): one dated log per track per day.
- [Pre-existing work](docs/pre-existing-work.md): preparation and reused material to disclose in the submission.

Challenge datasets are in `data/` and the raw brief in `local/`; both are gitignored (large files, credentials). See the Data and secrets section of [AGENTS.md](AGENTS.md).

Check the current event and challenge rules before preparing application code. Junction's [general terms](https://www.hackjunction.com/terms-of-service) require projects to be built primarily during the event and pre-existing material to be identified in the submission. Confirm the required project licence before submitting.
