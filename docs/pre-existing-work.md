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

## Editable architecture diagrams — 2026-11-14

Codex authored the system and harness diagrams in `docs/diagrams/` during the event,
checking current application code, SQL migrations and infrastructure configuration.
Native editable scenes and SVG/PNG exports were created with the free open-source
Excalidraw library (MIT); no third-party illustrations or infrastructure changes
were introduced. These document configured topology, not a verified live inventory.
