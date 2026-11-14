# Pre-existing work and reused material

Maintain this log for the final submission. It records provenance and timing; the official submission platform and challenge rules determine the disclosures required.

## Prepared before the event

| Material | Date | Source or author | Prepared beforehand | Built during the event |
| --- | --- | --- | --- | --- |
| Repository preparation files | 2026-11-10 to 2026-11-12 | Prepared locally with Codex for the team | README, shared agent instructions, brief template, environment example, and source-control defaults | To be completed |

Add any starter code or earlier prototypes separately. Describe which parts existed before the event and which parts were created during it.

## Planning during the event

| Material | Date | Source or author | Work performed |
| --- | --- | --- | --- |
| Valio Aimo implementation plan and diagrams | 2026-11-14 | Team-provided research brief and discussions with AI assistants; Codex checked challenge/API documentation, schema and catalog records, and reviewed [PR #1](https://github.com/Junction-Best-Team/Main-Application/pull/1) at `5a14b3fde3448ec2674d8711bbba676d6c6a1667` | Documentation and read-only catalog analysis only. Covers seeded customer rules, four-outcome policy/workflow modules, read-only policy discovery, shared schemas/evidence, a React/TypeScript/Vite approval inbox served by FastAPI, mission-driven approval without chat, concurrent commit enforcement, normal audit history, ingestion/search, and existing-cluster hosting. Both allergen-group overlaps were checked locally. PR #1 live-API findings are attributed reports, not independently repeated calls in this plan. Outbound notifications, policy editing, hash chaining and direct in-agent approval remain deferred. No application implementation or deployment. See [the plan](brief.md). |

## Reused code, data, models, and assets

During the event on 2026-11-14, Codex added the recipe illustration tool using
the portable Google helper from PR #129 and Cloudinary's documented signed
upload API. The tool, durable ledger, chat display and failure tests were written
during the event. Tests use authored tiny PNG/HTTP/browser fixtures; no provider
credentials or downloaded recipe photographs are bundled.
A single live smoke generated a synthetic tomato-pasta illustration and uploaded
it with the private event accounts; the resulting image is a local ignored QA asset.

During the event on 2026-11-14, Codex added a standalone native Google REST helper
using the existing HTTPX dependency and Google's documented request formats.
Tests use authored HTTP fixtures. Small synthetic live checks exercised Carbon,
Decision 1 and Embedding 2 through the private hackathon key; no image generation,
customer data or credentials were bundled. See [Google API usage](google-api.md).

On 2026-11-14, at the owner's request, Codex rebuilt Person 2's runner, provider
client and direct-tool adapter on `develop` `f13b75b`. The prior agent
implementation was replaced; existing shared models, product/purchasing code and
fixtures were retained as contracts. Agent tests were rewritten; the existing
purchasing integration scenario now exercises the HTTP provider protocol with
scripted responses. No new framework, dependency, model weights or visual asset.
Live-provider validation was skipped without configured credentials. See
[internal agent](internal-agent.md) and [validation](validation.md).

The owner then selected OpenRouter and supplied a private key. Codex configured
ignored local settings and GitHub secret/variables, verified two live completions
with an authored read-only policy result, and added future-release Secret wiring
with helper tests. No credentials, live customer data, supplier purchase or
deployment artifact was copied into source control.

During the event on 2026-11-14, Codex prepared Terraform infrastructure at the owner's request: a DigitalOcean adapter, portable Kubernetes/Helm deployment, explicit database/catalog setup Job, plan-only tests and a runbook. It builds on PR #2's design and targets PR #4's image/CLI contract; it does not copy the application implementation. No cloud infrastructure was applied. The ingress reuses the upstream Traefik Helm chart 42.4.0 (MIT); Terraform providers are locked in each stack. See [infra/README.md](../infra/README.md).

| Material/version | Source URL | Licence or usage restrictions | Role in the project | Attribution/disclosure needed |
| --- | --- | --- | --- | --- |
| Valio Aimo synthetic catalog, schema, companion data, and API documentation | [Challenge resource portal](https://junction26.valioaimo.fi/) | Sponsor states the synthetic data is for this challenge only; verify any additional submission/distribution requirements | Supplied inputs for design and planned implementation; raw datasets are not committed with the plan | Identify sponsor-provided data and distinguish live lookups, fixtures, and mock order acceptance |

Include frameworks, datasets, model weights, third-party assets, and earlier work as applicable. Record source/version information while building so submission preparation is straightforward.

The plan names intended frameworks and an embedding-model candidate; that is not a claim that their code or model weights have already been integrated. Add exact versions, licences, and actual usage to this log when implementation starts.

## Final review

- [ ] Check the current event and chosen challenge's rules.
- [ ] Complete the log and the official submission disclosure fields.
- [ ] Confirm the repository licence and required third-party attribution.
- [ ] Clearly describe any mocked or simulated functionality in the submission/demo.

Reference: [Junction general terms](https://www.hackjunction.com/terms-of-service).

## Application built during the event

| Material | Date | Source / actual usage |
| --- | --- | --- |
| Seller gateway, normalization, ingestion/search, policy/workflow, eight HTTP/MCP tools, buyer inbox, PostgreSQL migrations, mock adapter, tests and packaging | 2026-11-14 | Implemented with Codex during this task, starting from main `76296c1`; agreed behavior from PR #2 head `b0d1ee3`. No earlier application implementation was copied. PR #3's findings/draft are retained and attributed separately. |
| Tool sweep, CI script and `auto` upstream mode (labelled fixture fallback without an API key) | 2026-11-14 | `tests/sweep/run_sweep.py`, `tests/ci.sh`, `tests/test_upstream_mode.py`, `src/aimo/upstream.py`: written with Claude on top of PR #4. First real-key calls to the sponsor price/availability API were made this day (F-MVP-007). |
| Authored miniature fixture projections and invented commercial responses | 2026-11-14 | `src/aimo/fixtures.py` and `FixtureClient`; selected known product shapes exercise reported cases, but are not full catalog records or captured live responses. `demo-deposit` is a wholly fictional material. Real source records are verified privately by `scripts/verify_catalog.py`. |
| Buyer UI | 2026-11-14 | Original React/CSS interface; system fonts, no third-party photos or downloaded visual assets. Styled text marks this as the challenge demo; it is not an official supplier checkout. |
| PR #4 review fixes | 2026-11-14 | Codex changes to authority reevaluation, historical/current purchase views, documentation CSP and shared response contracts, with regression tests. Built on PR head `cd16b09`; no new services or dependencies. Swagger continues using FastAPI's jsDelivr assets, with nonced scripts on the documentation route. |
| PR #4 second review | 2026-11-14 | Codex fixes on `ea8e9aa`: trusted product scope, prepare idempotency, exact pack arithmetic, withdrawal retention, bounded login and supplier retries, worker-only MCP database work, connection pooling, batched inbox, exact filtered retrieval and bounded product generations. Added migration 002 and psycopg-pool 3.3.3 (LGPL-3.0-only, per installed package metadata); no new service. Regression and container/browser/retrieval results are in `docs/validation.md`. |
| Phase-0 product API stub | 2026-11-14 | `docs/api-stub-phase0.md`, written for [issue #66](https://github.com/Junction-Best-Team/Main-Application/issues/66). Documentation only, synthesized from the existing `src/aimo/api.py` routes and `schemas.py`/`chat_schemas.py` payload shapes; no new route, schema, or server was added. |
| Buyer session Playwright coverage (issue #67) | 2026-11-14 | `frontend/e2e/session.spec.ts`, authored on branch `fm/junction-baremin-session`. Sign-in, bad-credentials error, reload session-restore and sign-out are mocked at the browser/API edge with Playwright route fixtures, matching the existing `chat.spec.ts` mocked-prior-art style — the mocking is in the test harness only; `src/main.tsx`'s own code already called the real `/api/login`, `/api/session`, `/api/logout` endpoints and was not changed. The real session contract (cookie `aimo_session`, `csrf_token`, 401 on bad credentials, 204 + cookie clear on logout) was additionally exercised once by hand with `curl` against a locally run `aimo serve` instance and an isolated Postgres container, confirming the mocked fixtures match the live API shape; that manual run is not committed as an automated check. |

### Integrated dependencies and model

Exact resolved versions and hashes are in `uv.lock` and `frontend/package-lock.json`; runtime versions are in `.python-version`, `.node-version` and Dockerfile. Main integrated versions: FastAPI 0.162.7 (MIT), Pydantic 2.14.3 (MIT), Uvicorn 0.54.0 (BSD-3-Clause), psycopg 3.3.9 (LGPL-3.0), HTTPX 0.28.1 (BSD-3-Clause), Sentence Transformers 5.7.0 (Apache-2.0), Transformers 5.23.0 (Apache-2.0), PyTorch 2.15.0 / Linux CPU build (BSD-3-Clause), Argon2-cffi 25.1.0 (MIT), ItsDangerous 2.2.0 (BSD-3-Clause), React 19.3.1 (MIT), TypeScript 5.9.3 (Apache-2.0), Vite 7.3.8 (MIT), Playwright 1.65.1 (Apache-2.0), uv 0.12.5 (MIT/Apache-2.0), PostgreSQL/pgvector (PostgreSQL licence). Distribution must retain the respective packages' licence notices; lockfiles are not substitutes for those licences.

The [intfloat/multilingual-e5-small](https://huggingface.co/intfloat/multilingual-e5-small) model (MIT) is pinned to `614241f622f53c4eeff9890bdc4f31cfecc418b3`, used through Sentence Transformers with `passage:`/`query:` prefixes and normalized 384-dimensional embeddings. Model weights are downloaded during setup/image build, not committed to Git. Its [technical report](https://arxiv.org/abs/2402.05672) describes the model; our limited catalog evaluation is recorded separately.

The supplied synthetic catalog/schema are challenge-restricted inputs. The full 87 MB catalog stays private and is not committed. The derived live index remains local PostgreSQL data. Only aggregate evaluation results, query labels/identifiers and small authored fixtures are included here. No real payment, supplier order or inventory reservation was made. No email/push delivery was implemented or claimed.

The submission team still owns the final event disclosure and repository licence choice. The current challenge/terms pages were attempted during this session but not readable through the browsing tool; no new claim about submission deadlines or licensing permissions is made.

## Chat purchasing migration — 2026-11-14

Reused the existing application, purchasing/approval controls and frontend review components from latest develop `19bfda4`. Added internal typed LLM tools over existing HTTPX, persisted conversations and exact customer confirmation, converted the existing React entry point, and removed external HTTP/MCP adapters and the MCP dependency. No supplier checkout was added. Historical validation above refers to the prior gateway implementation; current verification is in `chat-purchasing.md`.


Person 2 review follow-up: preserved shared develop changes, added failure/HTTPS
regressions and server-authored recipe notices, and split the previously prepared
OpenRouter release code into PR #32 for runtime-owner review. The acceptance
handoff in `internal-agent.md` records unresolved shared work; it is not a claim
that recipe templates, deterministic scaling or trusted constraints were built.

## Automatic release migrations — 2026-11-14

Reused develop `b80a8bd`'s transaction-locked `aimo migrate`, SQL/ledger,
API image packaging, bootstrap grant policy, and release recovery/cluster cleanup.
Moved the existing grants into a shared helper; added a migration-only Job gate,
dedicated Secret provisioning, operator guide and focused tests. PR #34 was
inspected for concurrent schema changes; no numbered migration was added. Local
PostgreSQL tests are real; kubectl/Job behavior and Terraform plans use mocks.
No deployment, Terraform apply, production DB, seed/import or paid provider call
was performed by this task.

### Recipe planning — 2026-11-14

The owner selected the pre-existing UniTools World Recipes dataset (v2.0.0,
501 recipes, CC BY-SA 4.0, attribution UniTools — theunitools.com). Its source and
schema were inspected and its complete JSON imported locally with fixture embeddings;
no recipe data/photos are bundled. The importer preserves source/version/license,
original records and reviewed overrides. Agent, product search and purchasing reuse
existing application code; hosted recipe search targets PR #34's Qwen provider.
Tests use authored recipe/product/commerce evidence, not verified sponsor stock.
See `docs/recipes.md` for the snapshot checksum and remaining recipe/data limitations.

## Production frontend styling foundation — 2026-11-14

Reused PR #107's Tailwind v4 theme and Google Fonts declaration in the production
`frontend/` package. Restored the existing `ui/` design references from `develop`.
The existing stylesheet now occupies the components cascade layer, allowing
Tailwind utilities to override it during gradual screen migration. Existing API,
session, SSE and purchasing behavior is retained.

The subsequent frontend organization reuses those same production components
and behavior in feature folders (`auth`, `chat`, `purchases`), with shared API
transport/types, formatting and UI. Generated OpenAPI types were relocated
without changing their content. Added agent/architecture/development/testing
guides and ESLint/Prettier checks; no new customer screen or mock backend was
introduced by the structural refactor.

On 2026-11-14, at the owner's request, Codex simplified the existing CI for the
hackathon: reused the existing backend tests, API sweep, frontend build and
infrastructure checks, removed coverage gating/artifact jobs and shared the
backend setup. No new dependency, dataset, model or asset was introduced.

## Native Google provider cutover — 2026-11-14

At the owner's request, PR #132 reuses the portable HTTPX Google helper and the
existing typed agent, Decisions checks, ingestion caches and versioned catalog
cutover. New adapters select Google's Gemini 4 Carbon, Gemini Decision 1 and
Gemini Embedding 2; no model weights or datasets are committed. The existing
authored guardrail cases were rerun against Decision 1, with a compact result
artifact retained for review. Live transport checks used synthetic food text and
stub tool results only. Legacy local-model weights become an explicit worker
build option; no new dependency or customer asset is introduced by this cutover.

## Production screen styling port — 2026-11-14

Reused the visual language from designer PR #102 and `ui/DESIGN.md` in the
existing production feature components: colors, typography, message bubbles,
card surfaces, login layout and purchase controls. Reused the existing Tailwind
tokens and fonts; no prototype store, fixtures, handwritten API types, assets
or dependencies were imported. Routes, hooks and purchase authority stay with
the existing production implementation.

## Voice interface — 2026-11-14

At the owner's request, voice mode reuses PR #132's native HTTPX Google helper,
shared server-side Google credential, existing chat queue, typed tools and Nordic
UI tokens. The PCM microphone worklet, WebSocket bridge and browser fixtures were
authored for this feature against Google's documented Gemini 3.8 Live protocol.
No new dependency, voice recording, model weight or dataset is committed. Live
transport checks used synthetic text, locally synthesized test speech and stub
tool replies; they did not execute purchasing tools or use customer audio.

## Complete designer UI integration — 2026-11-14

Adapted PR #102 (5f550d2) presentational markup for the shell, Home, Request,
SKU cards, Overview, expandable Past Orders, login and Tailwind preflight into
production feature folders. Actual account and purchase data use existing API
modules/hooks and generated types. Static schedule/hub/account-manager examples
and disabled controls are labelled placeholders. No prototype store, fake login,
scenario switcher, dependencies or backend/schema changes were imported.

On 2026-11-14, the owner requested buyer policy settings. Reused the production
React feature structure, Nordic Wholesale Commerce tokens/fonts, browser session
and CSRF handling, immutable policy versions and purchasing revalidation. Added
policy-manager permissions and a browser Settings form; removed the product-scope
CLI. Browser tests use authored policy fixtures. No new dependencies, supplier
datasets, models or visual assets were introduced.

The policy settings branch was rebased onto the complete designer UI integration.
Settings now uses the real Account Settings entry in the shared sidebar/mobile menu
and retains the new Tailwind preflight instead of restoring the removed header or
legacy stylesheet. Reused the existing schema readiness probes for migration 014.

## Food-planning output review — 2026-11-14

Reused the existing guardrail classifier, bounded context builders and synthetic
evaluation harness. Added authored community-lasagna planning and unsupported-claim
cases; fixture tests do not measure classifier accuracy. No new dependency, model,
dataset or asset was introduced.

The owner clarified the product scope and refusal style: accept food, products and
nearby topics; decline clearly unrelated requests in simple language. Extended the
same synthetic evaluation with workout, food-before-exercise, storage, kitchen-supply
and community-serving cases. No new external material was used.
