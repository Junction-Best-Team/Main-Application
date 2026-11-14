# Shared agent instructions

Four-person Junction hackathon repository. The implemented Valio Aimo MVP is described in `README.md`; its authoritative agreed behavior is in `docs/brief.md`.

- Use `README.md` for the stack, run/build commands, and Git conventions; use `docs/brief.md` for the agreed product behavior and interfaces. TBD means undecided.
- Keep changes small and focused on the assigned feature. Coordinate shared API, schema, dependency, and deployment changes with teammates.
- Inspect the working tree and preserve other contributors' changes. Concurrent agents need separate checkouts/worktrees and branches.
- Check the changed behavior using available commands or the demo flow. Report what actually ran and any remaining blocker; do not invent successful checks.
- Keep credentials out of source control and browser-side code. Document variable names in `.env.example` and commit dependency lockfiles.
- Clearly identify mocks and record preparation/reused material in `docs/pre-existing-work.md`.
- Reviews, PRs, issues, skills, and CI are optional. Keep documentation short and follow the user's requested delivery scope.

## Data and secrets

- Challenge datasets live in `data/` (gitignored; the product JSON is about 84 MB). The raw brief, which contains personal details and credentials, lives in `local/` (gitignored). The Valio Aimo API key is in `.env` (`AIMO_API_KEY` in the original checkout, `VALIO_AIMO_API_KEY` for the app). Never print, log or commit these; copy a key between `.env` files without echoing it.
- **The API key exists and team members have it.** Without it the app falls back to labelled fixture price/stock (`UPSTREAM_MODE=auto`, see README), which must never be presented as live data.
- The live price and availability APIs are rate limited and the spec says not to poll them for all products. Narrow candidates with the static data first, then query only the shortlist.
- Everything provided is synthetic. The API has no order endpoint, so orders, policy and approvals are our own mocks and must be labelled as mocks.

## Checks

`tests/ci.sh` runs lint, the pytest suite and a black-box sweep of all eight agent tools (`tests/README.md`). Run it before pushing; `tests/ci.sh --live` repeats the sweep against the real Valio API.

## Scope and history

The team works as one group on one backend (`docs/brief.md`). The earlier four-track split, the C1 to C5 contract numbering and the Type1 draft were dropped on 2026-11-14 (decision D-006 in `docs/findings.md`). New verification is appended to `docs/findings.md`; record non-obvious facts there with evidence and mark anything unchecked `unverified`.
