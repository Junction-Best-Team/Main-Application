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
| Tool sweep, CI script and `auto` upstream mode (labelled fixture fallback without an API key) | 2026-11-14 | `tests/sweep/run_sweep.py`, `tests/ci.sh`, `tests/test_upstream_mode.py`, `src/aimo/upstream.py`: written with Claude on top of PR #4. First real-key calls to the sponsor price/availability API were made this day (F-MVP-005). |
| Authored miniature fixture projections and invented commercial responses | 2026-11-14 | `src/aimo/fixtures.py` and `FixtureClient`; selected known product shapes exercise reported cases, but are not full catalog records or captured live responses. `demo-deposit` is a wholly fictional material. Real source records are verified privately by `scripts/verify_catalog.py`. |
| Buyer UI | 2026-11-14 | Original React/CSS interface; system fonts, no third-party photos or downloaded visual assets. Styled text marks this as the challenge demo; it is not an official supplier checkout. |

### Integrated dependencies and model

Exact resolved versions and hashes are in `uv.lock` and `frontend/package-lock.json`; runtime versions are in `.python-version`, `.node-version` and Dockerfile. Main integrated versions: FastAPI 0.162.7 (MIT), Pydantic 2.14.3 (MIT), Uvicorn 0.54.0 (BSD-3-Clause), MCP Python SDK 1.30.0 (MIT), psycopg 3.3.9 (LGPL-3.0), HTTPX 0.28.1 (BSD-3-Clause), Sentence Transformers 5.7.0 (Apache-2.0), Transformers 5.23.0 (Apache-2.0), PyTorch 2.15.0 / Linux CPU build (BSD-3-Clause), Argon2-cffi 25.1.0 (MIT), ItsDangerous 2.2.0 (BSD-3-Clause), React 19.3.1 (MIT), TypeScript 5.9.3 (Apache-2.0), Vite 7.3.8 (MIT), Playwright 1.65.1 (Apache-2.0), uv 0.12.5 (MIT/Apache-2.0), PostgreSQL/pgvector (PostgreSQL licence). Distribution must retain the respective packages' licence notices; lockfiles are not substitutes for those licences.

The [intfloat/multilingual-e5-small](https://huggingface.co/intfloat/multilingual-e5-small) model (MIT) is pinned to `614241f622f53c4eeff9890bdc4f31cfecc418b3`, used through Sentence Transformers with `passage:`/`query:` prefixes and normalized 384-dimensional embeddings. Model weights are downloaded during setup/image build, not committed to Git. Its [technical report](https://arxiv.org/abs/2402.05672) describes the model; our limited catalog evaluation is recorded separately.

The supplied synthetic catalog/schema are challenge-restricted inputs. The full 87 MB catalog stays private and is not committed. The derived live index remains local PostgreSQL data. Only aggregate evaluation results, query labels/identifiers and small authored fixtures are included here. No real payment, supplier order or inventory reservation was made. No email/push delivery was implemented or claimed.

The submission team still owns the final event disclosure and repository licence choice. The current challenge/terms pages were attempted during this session but not readable through the browsing tool; no new claim about submission deadlines or licensing permissions is made.
