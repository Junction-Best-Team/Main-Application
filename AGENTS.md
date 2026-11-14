# Shared agent instructions

Four-person Junction hackathon repository. Preparation and design files only; the Valio Aimo implementation plan is in `docs/brief.md`, and the planned stack is in `README.md`. Application code is not implemented yet.

- Use `README.md` for the stack, run/build commands, and Git conventions; use `docs/brief.md` for the agreed product behavior and interfaces. TBD means undecided.
- Keep changes small and focused on the assigned feature. Coordinate shared API, schema, dependency, and deployment changes with teammates.
- Inspect the working tree and preserve other contributors' changes. Concurrent agents need separate checkouts/worktrees and branches.
- Check the changed behavior using available commands or the demo flow. Report what actually ran and any remaining blocker; do not invent successful checks.
- Keep credentials out of source control and browser-side code. Document variable names in `.env.example` and commit dependency lockfiles.
- Clearly identify mocks and record preparation/reused material in `docs/pre-existing-work.md`.
- Reviews, PRs, issues, skills, and CI are optional. Keep documentation short and follow the user's requested delivery scope.
