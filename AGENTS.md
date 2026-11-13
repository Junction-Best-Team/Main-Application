# Shared agent instructions

Four-person Junction hackathon repository. Challenge: **Trusted Trade Agents (Valio Aimo)**. We build the Valio Aimo side of the interface that lets an external purchasing agent look up products, request price and availability, place an order, and get human approval. We do **not** build the buyer's agent. Stack is still undecided.

- Use `README.md` for the stack, run/build commands, and Git conventions; use `docs/brief.md` for the agreed product behavior and interfaces. TBD means undecided.
- Use `docs/architecture.md` for the four tracks, the contracts between them, and who owns what. Stay inside your track; raise anything that crosses a boundary in `docs/issues.md`.
- Keep changes small and focused on the assigned feature. Coordinate shared API, schema, dependency, and deployment changes with teammates.
- Inspect the working tree and preserve other contributors' changes. Concurrent agents need separate checkouts/worktrees and branches.
- Check the changed behavior using available commands or the demo flow. Report what actually ran and any remaining blocker; do not invent successful checks.
- Keep credentials out of source control and browser-side code. Document variable names in `.env.example` and commit dependency lockfiles.
- Clearly identify mocks and record preparation/reused material in `docs/pre-existing-work.md`.
- Reviews, PRs, issues, skills, and CI are optional. Keep documentation short and follow the user's requested delivery scope.

## Data and secrets

- Challenge datasets live in `data/` (gitignored; the product JSON is about 84 MB). The raw brief, which contains personal details and credentials, lives in `local/` (gitignored). The real API key is in `.env` as `AIMO_API_KEY`. Never print, log or commit these.
- Datasets can be re-downloaded through the download endpoints in `docs/reference/aimo-api.openapi.json`.
- The live price and availability APIs are rate limited and the spec says not to poll them for all products. Narrow the candidates with the static data first, then query only the shortlist.
- Everything provided is synthetic. The API has no order endpoint, so ordering, mandates and approvals are our own mocks and must be labelled as mocks.

## Findings

When you learn something non-obvious (a data quirk, real API behavior, a decision, a bug, a trap), record it in `docs/findings.md` right away, in your track's section, in the format shown there. Record facts with evidence and mark anything you have not verified as `unverified`. Skip anything obvious from the code or `git log`. Owner decisions are quoted verbatim with the date. Never delete another track's finding; change its status and say why.

## History

Each track keeps its own dated log in `docs/history/YYYY-MM-DD-<track>.md` (one file per track per day, so teammates do not edit the same file). Write or update your entry when a task is finished, before your agent's context is compacted or the session ends, and at each integration point. Sections: **Summary**, **Changes** (paths, branch, commit SHAs), **Lessons** (link finding IDs instead of repeating them), **Carry forward** (open work, blockers, what waits on someone else). Facts and evidence only. Read the newest entries for your track and the issues file at the start of a session.
