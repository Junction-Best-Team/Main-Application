# Shared agent instructions

Four-person Junction hackathon repository. The implemented Valio Aimo MVP is described in `README.md`; its authoritative agreed behavior is in `docs/brief.md`.

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
- CI is one workflow, `.github/workflows/ci.yml`: Python lint, the core-flow selection in `tests/pr-tests.sh` and the strict API sweep share one fixture-backed PostgreSQL/pgvector job (manual CI runs `tests/pr-tests.sh --full`); frontend type check/build runs in parallel; Terraform validation runs for infrastructure/workflow changes. The existing `Detect application components` status is retained for repository rules and detects applicable backend/frontend/infrastructure changes. `CI gate` requires every applicable check to pass. Coverage is optional locally, with no minimum percentage and no coverage job/artifacts in CI. Formatting and browser checks stay local. Model downloads, full catalog imports, Docker builds and live-API calls stay out of CI (CI never has the Valio key). Same-repository `develop` → `main` release PRs reuse protected-develop contribution checks without repeating the suites; source-branch validation and CI gate remain. The optional `skip-review` label never skips CI.
- `main` holds stable demo/release snapshots. Only open a release PR from `develop` to `main` when the user explicitly requests a release; never target `main` with a task PR.
- After required release-PR CI, the protected main push builds/pushes the image and deploys only when `DEPLOY_ENABLED=true`. Terraform provisioning, initial bootstrap/seeding, and catalog imports stay explicit operator steps; routine releases run a dedicated schema migration/grant Job before changing app images. Never enable deployment before bootstrap and migration-credential provisioning are complete. Follow `infra/README.md` for setup.
- Do not force-push either shared branch. Preserve other contributors' changes and checkouts.

## Data and secrets

- Challenge datasets live in `data/` (gitignored; the product JSON is about 84 MB). The raw brief, which contains personal details and credentials, lives in `local/` (gitignored). The Valio Aimo API key is in `.env` (`AIMO_API_KEY` in the original checkout, `VALIO_AIMO_API_KEY` for the app). Never print, log or commit these; copy a key between `.env` files without echoing it.
- **The API key exists and team members have it.** Without it the app falls back to labelled fixture price/stock (`UPSTREAM_MODE=auto`, see README), which must never be presented as live data.
- The live price and availability APIs are rate limited and the spec says not to poll them for all products. Narrow candidates with the static data first, then query only the shortlist.
- Everything provided is synthetic. The API has no order endpoint, so orders, policy and approvals are our own mocks and must be labelled as mocks.

## Checks

`tests/ci.sh` runs lint, the pytest suite and a black-box sweep of the buyer-facing API (`tests/README.md`; the assistant's tools are covered by `tests/test_agent*.py`); `--live` first validates a read-only Valio price/availability lookup, then runs the HTTP sweep. The sweep never submits an authenticated chat turn. `CI_COVERAGE=1 tests/ci.sh` then `uv run python tests/coverage_report.py` optionally measures Python coverage locally; no coverage percentage blocks CI. `tests/TEST-GUIDE.md` explains what each test checks.

## Scope and history

The explicit implementation handoff selects the PR #2 brief for this MVP. PR #2 was closed unmerged; implementation starts on current main and preserves the post-MVP draft as reference. For this implementation use database-seeded versioned policy, eight named tools, four outcomes, independent buyer inbox, ordinary persistent audit and no live deployment. The draft open issues above are resolved for this scope by `docs/brief.md`; do not reintroduce a notifier or hash chaining. The owner explicitly requested buyer policy settings on 2026-11-14; see `docs/policy-settings.md`. New verification is appended to `docs/findings.md`.

## Chat purchasing cutover (2026-11-14)

The explicit product migration in `docs/chat-purchasing.md` overrides the earlier external-agent/MCP and standalone inbox entry points above. The existing React app is the customer chat product; the authenticated FastAPI app runs typed internal tools directly against Service. Customer confirmation must be a persisted authenticated exact-revision action; retain purchasing controls, historical records and mock-order labels. Do not merge, deploy, apply Terraform or enable the release switch for this task.

The earlier four-track split, the C1 to C5 contract numbering and the Type1 draft were dropped on 2026-11-14 (decision D-006 in `docs/findings.md`).
