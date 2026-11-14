# Junction — Main Application

Four-person team repository for [Junction 2026](https://2026.hackjunction.com/), November 13–15 in Espoo, Finland.

Preparation files only. The challenge, stack, application, and deployment target are still to be selected.

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
- Check the affected feature works, then open a PR into `develop`: `gh pr create --base develop`. All feature, fix, documentation, and maintenance PRs must target `develop`. Request a teammate review; merging requires one approval of the latest commit from a teammate with write access and no outstanding requests for changes. A teammate can explicitly bypass reviews by adding the `skip-review` label: `gh pr edit <number> --add-label skip-review`.
- Keep `main` ready to demonstrate. Promote a tested snapshot with a release PR from `develop` to `main` only when a release is explicitly requested. Avoid force pushes to shared branches and preserve teammates' uncommitted work.
- Use a separate checkout/worktree and branch for each concurrent agent on the same machine.

The `Review policy` workflow publishes the `review-policy` commit status. It passes with the review requirement above or the `skip-review` label, and rechecks when commits, labels, or reviews change. It reads GitHub metadata only and never executes PR code. Agents must follow this policy before merging.

**Enforcement limitation:** GitHub currently rejects branch protection for this private repository on the organization's plan, so the check is advisory in GitHub's merge UI. Once branch protection is available, require PRs and the `review-policy` status on `develop` (including administrators). Leave GitHub's separate approving-review count at zero so the label can bypass the custom review check. No other pipelines or special GitHub board are required. Use the team chat to coordinate.

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
- [Pre-existing work](docs/pre-existing-work.md): preparation and reused material to disclose in the submission.

Check the current event and challenge rules before preparing application code. Junction's [general terms](https://www.hackjunction.com/terms-of-service) require projects to be built primarily during the event and pre-existing material to be identified in the submission. Confirm the required project licence before submitting.
