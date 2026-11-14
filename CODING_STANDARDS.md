# Coding standards

Read by the `code-review` skill's Standards axis. This file states what CI already
enforces (skip flagging it) and the judgement calls CI cannot catch. For product
behavior and ownership, see `docs/brief.md`, `docs/chat-purchasing.md`, and
`AGENTS.md`; this file does not restate them.

## Already enforced by CI — do not re-flag

Verified against `.github/workflows/*.yml` on 2026-11-14. If a finding is only
"a linter/CI would catch this," skip it; report only what the exact scope below
leaves out.

| Area | Job | Command | Scope and gaps |
| --- | --- | --- | --- |
| Python lint | `ci.yml` → `backend` | `ruff check src tests scripts` | **Excludes `infra/`** (its own `*.py` files are never ruff-checked in CI). Rule set is only `E4, E7, E9, F, I` (pyflakes, import-sort, a few pycodestyle categories) — no complexity, docstring, or bugbear rules. |
| Python tests | `ci.yml` → `backend` | `pytest -q` | `testpaths = ["tests"]` (see `pyproject.toml`): runs `tests/` only, against real PostgreSQL/pgvector with fixture data. **Does not run `infra/tests/`.** Runs only when `pyproject.toml`/`uv.lock`/`src`/`tests` exist (always true once the app is present). |
| Frontend types/build | `ci.yml` → `frontend` | `npm run build` (`tsc -b && vite build`) | Type-checks and builds. **No ESLint config exists in `frontend/`, so no style lint runs anywhere, in CI or locally.** `npm test` (Playwright, `frontend/playwright.config.ts`) is defined but **never invoked in CI** — browser tests stay a manual/local check by design (`AGENTS.md`). |
| Terraform format/validate/plan-test | `terraform.yml` (called by `ci.yml` only when infra/workflow files changed) | `terraform fmt -check -recursive infra`, `terraform validate`, `terraform test` (mocked plan, matrix over `infra/digitalocean` and `infra/kubernetes`) | Only runs when the change touches `infra/` or `.github/workflows/{ci,terraform,deploy}.yml`. No cloud credentials; both providers are mocked. |
| Helm render | `terraform.yml` (kubernetes leg only) | `helm template ... traefik --version 42.4.0 ...` | Confirms the rendered ingress chart from the Terraform test output, not a live cluster. |
| Infra helper tests | `terraform.yml` (kubernetes leg only) | `python3 -m unittest discover -s infra/tests` | Same conditional trigger as the Terraform job above — **does not run on a PR that only changes `src/`/`tests/`/`frontend/`.** |
| Infra script syntax | `terraform.yml` (kubernetes leg only) | `py_compile` on `infra/kubernetes/bootstrap.py` and `infra/scripts/ci-cluster-access.py`; `bash -n` on `infra/scripts/deploy-app.sh` | Syntax-only, not style and not every script (e.g. `infra/scripts/sync-llm-secret.py`, `infra/scripts/deploy-app.sh`'s logic itself, aren't syntax-checked here beyond that one `bash -n`). |
| Main-branch guard | `main-source.yml` | head-ref/head-repo check | Not a code check; blocks any PR into `main` whose head isn't `develop` in this repository. |

**Not run by CI at all, anywhere:** `actionlint`, `shellcheck`. PR descriptions in
this repo sometimes report running them manually before pushing; treat that as
the author's own extra diligence, not something CI re-verifies, so a review may
still usefully flag a workflow/shell issue those tools would catch.

## Judgement calls (not mechanically enforced)

- **Mock orders stay labeled.** Every mock/simulated purchase, provider response,
  or supplier fact must say so in its docstring, log, or doc entry (`AGENTS.md`).
  No tooling checks this; flag an unlabeled mock as a hard finding, not a smell.
- **Ownership boundaries.** `docs/chat-purchasing.md` and the plan referenced in
  the originating issue/PR assign each file area to one of the three tracked
  roles. A diff that edits another role's area without a stated reason is a
  judgement call worth a note, not an automatic violation.
- **No pretend responses.** A missing/invalid provider or supplier credential
  must produce an actionable error, never a fallback success. This is tested in
  places but not exhaustively; treat a new code path that swallows such a failure
  as a hard finding.
- Beyond these, apply the Fowler smell baseline from the `code-review` skill as
  the default judgement-call set.
