# Shared agent instructions

Four-person Junction hackathon repository. Preparation files only; challenge and stack are undecided.

- Use `README.md` for the stack, run/build commands, and Git conventions; use `docs/brief.md` for the agreed product behavior and interfaces. TBD means undecided.
- Keep changes small and focused on the assigned feature. Coordinate shared API, schema, dependency, and deployment changes with teammates.
- Inspect the working tree and preserve other contributors' changes. Concurrent agents need separate checkouts/worktrees and branches.
- Check the changed behavior using available commands or the demo flow. Report what actually ran and any remaining blocker; do not invent successful checks.
- Keep credentials out of source control and browser-side code. Document variable names in `.env.example` and commit dependency lockfiles.
- Clearly identify mocks and record preparation/reused material in `docs/pre-existing-work.md`.
- Reviews, PRs, issues, skills, and CI are optional. Keep documentation short and follow the user's requested delivery scope.

## Post-MVP plan

The longer-term design (MVP and full product, two-part purchasing contract, normalisation layer, approval flow) is a draft in `Plan/post-mvp-plan.md`. Verified data and API facts and owner decisions are in `docs/findings.md`; record new ones there (format at the top of that file). Build the MVP on the plan's seams, and read its section 0 before changing a shared interface. Still unresolved:

- Whether an approval can make an unknown-quantity or passed-cut-off order executable (recommended: no, add a `needs_resolution` outcome).
- How the customer receives the approval request (mock inbox, or the approval URL returned through the agent).
- Whether the MVP needs a hash-chained audit log (recommended: no) and where the purchasing rules live (code, per D-003, or database rows).
- Repricing tolerance default, and the status vocabulary for derived values.
- The live-API probe is not committed or reproduced; `closingTime` behaviour and several variable meanings need a mentor.
- Reconciling this plan with PR #2 (stack, tool names, decision vocabulary) and confirming cluster access.

