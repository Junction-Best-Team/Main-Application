# Shared agent instructions

Four-person Junction hackathon repository. Preparation and design files only; the Valio Aimo implementation plan is in `docs/brief.md`, and the planned stack is in `README.md`. Application code is not implemented yet.

- Use `README.md` for the stack, run/build commands, and Git conventions; use `docs/brief.md` for the agreed product behavior and interfaces. TBD means undecided.
- Keep changes small and focused on the assigned feature. Coordinate shared API, schema, dependency, and deployment changes with teammates.
- Inspect the working tree and preserve other contributors' changes. Concurrent agents need separate checkouts/worktrees and branches.
- Check the changed behavior using available commands or the demo flow. Report what actually ran and any remaining blocker; do not invent successful checks.
- Keep credentials out of source control and browser-side code. Document variable names in `.env.example` and commit dependency lockfiles.
- Clearly identify mocks and record preparation/reused material in `docs/pre-existing-work.md`.
- Pull requests and the lightweight CI checks below are required for changes. Human reviews, issues, and skills are optional. Keep documentation short and follow the user's requested delivery scope.

## Branch and pull request workflow

- `develop` is the default branch and the shared integration branch. Start every task branch from the latest `origin/develop`.
- Work on a separate task branch; never commit or push changes directly to `develop` or `main`.
- Always open feature, fix, documentation, and maintenance PRs against `develop`. Specify the base explicitly: `gh pr create --base develop`. Verify the base before creating or merging a PR.
- Wait for the latest CI run to pass before merging. You may merge your own PR without a human approval. Request a teammate review for risky changes to authentication, database schemas, or shared interfaces; routine work does not need to wait for a reviewer.
- CI runs Python lint, backend tests with fixture data and PostgreSQL/pgvector, and the TypeScript/production frontend build. It skips application components only while their code has not been added. Keep model downloads, full catalog imports, Docker builds, and browser tests outside this quick pipeline. The optional `skip-review` label never skips CI.
- `main` holds stable demo/release snapshots. Only open a release PR from `develop` to `main` when the user explicitly requests a release; never target `main` with a task PR.
- Do not force-push either shared branch. Preserve other contributors' changes and checkouts.

## Post-MVP plan

The longer-term design (MVP and full product, two-part purchasing contract, normalisation layer, approval flow) is a draft in `Plan/post-mvp-plan.md`. Verified data and API facts and owner decisions are in `docs/findings.md`; record new ones there (format at the top of that file). Build the MVP on the plan's seams, and read its section 0 before changing a shared interface. Still unresolved:

- Whether an approval can make an unknown-quantity or passed-cut-off order executable (recommended: no, add a `needs_resolution` outcome).
- How the customer receives the approval request (mock inbox, or the approval URL returned through the agent).
- Whether the MVP needs a hash-chained audit log (recommended: no) and where the purchasing rules live (code, per D-003, or database rows).
- Repricing tolerance default, and the status vocabulary for derived values.
- The live-API probe is not committed or reproduced; `closingTime` behaviour and several variable meanings need a mentor.
- Reconciling this plan with PR #2 (stack, tool names, decision vocabulary) and confirming cluster access.

