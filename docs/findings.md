# Findings

Non-obvious facts, traps, decisions and known issues, each with evidence. Append to the relevant section. Do not delete a finding; change its status and say why. The `Track:` field on older entries refers to the four-track split that was dropped (D-006); ignore it.

Entry format:

```
### F-<area>-<nnn>: <short title>
- Date: YYYY-MM-DD   Track: <1-4 or all>   Status: verified | unverified | superseded
- Finding: <the fact, stated plainly>
- Evidence: <command, file path, request, or source; how someone can re-check it>
- Impact: <what it means for the build>
```

Owner decisions use `D-<nnn>` and quote the owner's words verbatim.

## Internal agent

### F-AGENT-001: Person 2 rebuild uses persisted turns and canonical Service contracts
- Date: 2026-11-14   Track: 2   Status: verified
- Finding: The rebuilt runner requires the server's persisted turn ID, validates canonical tool inputs/outputs and retains the matching prepared plan/proposal after provider failures. Progress callbacks are optional metadata; browser SSE remains persisted snapshots. The model has no confirmation or commit operation.
- Evidence: `tests/test_agent.py` (66 passing cases) and `tests/test_agent_integration.py`, within the full 174-test PostgreSQL/pgvector suite. `scripts/smoke_agent_provider.py` reported skipped because `LLM_API_KEY` was not configured; no live-provider success is claimed.
- Impact: Person 1 can retain the existing three-argument runner call and optionally consume typed progress; Person 3 retains domain arithmetic and authorization. Backend retry recovery still uses the existing `chat-` plus turn-fingerprint preparation key. The runner needs no shared schema change. The later requested release wiring is separated into PR #32; this agent PR contains no deployment changes.

### F-AGENT-002: OpenRouter live function calling and release credential wiring
- Date: 2026-11-14   Track: 2   Status: verified (local/provider and GitHub storage); deployment pending
- Finding: The owner's OpenRouter credential was stored only in ignored local configuration and GitHub `LLM_API_KEY`; provider variables select `https://openrouter.ai/api/v1` and `openai/gpt-4.1-mini`. The live smoke passed two completions and a read-only fixture-policy tool round trip. The existing release workflow previously did not transfer LLM settings to runtime; PR #32 proposes passing the secret and merging only provider fields through kubectl stdin on a future authorized deployment, separately from the agent rebuild.
- Evidence: `scripts/smoke_agent_provider.py --require-config` returned `status=passed`, `provider=live`, `completions=2`; GitHub secret-name/variable readback confirmed storage. Backend 174 tests and infrastructure helper 23 tests passed; no credential value is recorded in tracked files or test evidence.
- Impact: Local LLM connectivity is proven. GitHub Secret storage alone does not change running Pods: release wiring must be integrated and an authorized deployment must load the settings. Orders remain mock; no cluster modification or release activation was performed here.

### F-AGENT-003: Review fixes and unresolved shared acceptance checks
- Date: 2026-11-14   Track: 2   Status: verified (agent fixes); shared acceptance gaps remain
- Finding: Remote provider URLs require HTTPS, with loopback-only HTTP development. Unexpected Service/provider failures emit safe error progress and preserve a previously verified basket; no automatic tool retry follows an unexpected failure. Final plan text labels estimates and lists unresolved product matches independently of model text. Model arithmetic, cross-turn recipe completeness and trusted constraint provenance remain incomplete; `docs/internal-agent.md` records the owning roles and required integration checks.
- Evidence: Ruff, 79 deterministic agent tests and the full 188-test PostgreSQL suite passed after review. Runtime wiring is separately reviewed in PR #32 (28 helper tests, actionlint, Kubernetes Terraform validation and seven mocked plans); no cluster mutation ran. The review decisions are in PR #19's owner comment.
- Impact: #19 is canonical, superseding #12/#16. Persons 1 and 3 must settle and implement the shared context, recipe template and quantity bounds before claiming the affected acceptance checks pass. No shared schema is invented by the agent PR.

### F-AGENT-004: Guardrails separate deterministic controls from Jev verdicts
- Date: 2026-11-14   Track: 2   Status: verified (deterministic and fake-provider tests); live Jev accuracy unmeasured
- Finding: OpenRouter's Decisions API (`POST /api/alpha/decisions`, `typesafe/jev-1.14` listed under `/api/v1/models?output_modalities=decisions`) returns typed `noul` probabilities or `refusal`, not text. `typesafe/jev-router` is a separate routing product. Guardrails screen the customer message, catalog text, new preparations and the final narrative, with `off`/`shadow`/`enforce` modes. Enforcement fails closed for new baskets only; confirmation and purchase reads stay independent. Tool results given to the model are minimised; per-buyer active-turn and hourly message limits were missing and are added.
- Evidence: Official Decisions OpenAPI schema and Jev guide read on 2026-11-14; `tests/test_guardrails.py` and `tests/test_guardrails_integration.py`; full backend suite. `scripts/evaluate_guardrails.py` reported `skipped` because no OpenRouter key was configured in this checkout.
- Impact: Thresholds (0.2/0.8) are provisional until a labelled live run. Shadow/enforce send chat text to TypeSafe, so the code default is `off`. See `docs/guardrails.md`.
- Update 2026-11-14 (PR #56 review): two bypasses fixed. (1) A reply batching `get_product`, `publish_meal_plan` and `prepare_order` reused a product's earlier clean search screening, so a new description was screened only after preparation; the prepare check now screens each selected product's current text first. (2) Output review saw only the narrative, while the UI also renders the model-authored meal plan; the review now covers the plan, rejected or unreviewed plans are withheld under enforcement, and the displayed basket label is checked before preparation (policy `guard-2026-11-14.2`). Regression tests fail on the earlier commit and pass after the fix. A second review found saved purchase history re-adding catalog line names that `get_proposal` had withheld; that history now omits product names (IDs, quantities, prices and status remain). After merging recipe planning (#38), output review covers only the meal-plan fields the UI displays (saved plans carry large conversion evidence), and recipe tool results are wrapped as data but not yet semantically screened.
- Update 2026-11-14 (owner decision): guardrails enforce by default; `GUARDRAIL_MODE` is the only setting. Jev reuses the OpenRouter `LLM_API_KEY` (never sent to another host); the endpoint, model, timeouts, call budget and chat limits are code constants. Enforcement uses the provisional thresholds until a live labelled run.

## Infrastructure

### F-INFRA-001: Optional Terraform hosting and portable deployment
- Date: 2026-11-14   Track: 4   Status: verified (preparation); cloud deployment subsequently verified in F-INFRA-002
- Finding: The owner requested a separate worktree and Terraform PR based on PR #2, selected the DigitalOcean weekend direction, required cloud portability, and explicitly prohibited applying Terraform. PR #2 is closed and unmerged; PR #4 separately implements the application image/CLI. Two Terraform stacks isolate DigitalOcean VPC/DOKS/managed PostgreSQL provisioning from portable Kubernetes/Helm application resources. PostgreSQL runs outside Kubernetes, using its private endpoint and verified TLS. Initial app replicas and setup Jobs remain off until explicitly enabled by the operator.
- Evidence: `infra/README.md`, `infra/digitalocean`, and `infra/kubernetes`; read-only authenticated DigitalOcean `/v2/account`, `/v2/regions`, `/v2/kubernetes/options`, and `/v2/databases/options` on this date confirmed account access, `ams3`, Kubernetes `1.35.10-do.0`, PostgreSQL 17 and the selected single-node database size. The token is stored privately outside the repository. No infrastructure was applied during preparation; see F-INFRA-002 for the later authorized rollout.
- Impact: Plans and CI can be reviewed without spending or mutating existing resources. Before rollout, supply the actual operator CIDRs, published application image, DNS name/email and challenge API key. Replacing the cloud requires a new provisioning adapter; the Kubernetes deployment accepts standard kubeconfig/PostgreSQL inputs. One worker and one database primary are demo defaults, not a high-availability or measured-capacity claim.

### F-INFRA-002: First cloud apply and provider settings normalization
- Date: 2026-11-14   Track: 4   Status: verified (cloud foundation); application rollout unverified
- Finding: After PR #9 merged and the owner explicitly authorized applying the plan, Terraform created all seven cloud resources in `ams3`. One 4-GB worker is Ready, PostgreSQL is online, and its sole firewall rule trusts the Kubernetes cluster. Private deployment inputs use the operator's current public IPv4 and `10.121.0.0/20`; the original range was already used by the account's default VPC. The provider records an empty runtime-user settings block at creation; omitting it produces a subsequent removal request rejected with HTTP 400. Declare `settings {}` to retain the returned default.
- Evidence: `terraform -chdir=infra/digitalocean apply -input=false weekend.tfplan` reported seven additions; DigitalOcean cluster/database/firewall reads and `kubectl get nodes` verified readiness and isolation. A subsequent Terraform plan and rejected settings-only update reproduced the provider issue; see [provider v2.107.0](https://github.com/digitalocean/terraform-provider-digitalocean/blob/v2.107.0/digitalocean/database/resource_database_user.go). Retaining the empty settings block applied successfully; a refreshed plan with the private deployment tfvars then reported no changes (exit 0).
- Impact: Cloud billing is active. Keep the private tfvars and local state for future plans and teardown; credentials, kubeconfig and a private state backup stay outside Git. The Kubernetes application/ingress stack, SQL bootstrap, catalog import and app readiness remain pending; no application image, DNS or challenge API key was invented.

### F-INFRA-003: Independent application containers and durable worker queue
- Date: 2026-11-14   Track: all   Status: verified locally; live cutover pending
- Finding: The owner requested “separete all into their apps, worker is a pod api fe etc” and “new pr new worktree”. The frontend, API and worker now have independent build targets, Kubernetes Deployments/Services, probes and credentials. PostgreSQL stores queued turns; workers claim with bounded leases and attempt fencing. Migration 005 preserves business history and makes historical interrupted turns explicitly retryable.
- Evidence: 144 PostgreSQL-backed backend tests; Python lint; three successful Docker target builds; 8 mocked portable Terraform plans; 28 infrastructure helper tests (including the merged OpenRouter sync); rendered Traefik chart. A three-container smoke with fixture embeddings/provider returned a queued message in 0.02 seconds with the worker stopped, retained it across API restart, processed it after worker startup, and delivered SSE through the frontend proxy. No live supplier calls or production changes were made by these checks.
- Impact: The API no longer loads ML weights or runs agent turns inline. The static frontend receives no secrets. Apply migration 004 and the reviewed separate-app Terraform cutover before enabling the new three-image release pipeline; see `docs/separate-apps.md`.

## Owner decisions

### D-001: Build the Valio Aimo side, not the buyer's agent
- Date: 2026-11-13   Track: all   Status: verified
- Decision: "Can you get rid of the buyer agent interface, and stick with what the brief wanted."
- Impact: Scope is the interface and operating model (lookup, quote and order, mandates and approvals, audit). A thin reference client exists only for demo and testing. The Type1 draft that elaborated this was removed (D-006).

### D-003: The agent contract is fixed in source code
- Date: 2026-11-14   Track: 3 (affects 2, 4)   Status: verified (decision); the draft design in `Plan/post-mvp-plan.md` was removed (D-006); the MVP instead uses database-seeded, versioned, read-only policy (F-MVP-001)
- Decision: "For the mandate, I would like this to behave as a contract, which is the behavior of how the MCP will behave with the agent. I want it to be fixed in the code, and be unchangable without source code changes."
- Impact: What the agent may do alone is a frozen constant in source, with no endpoint, tool or setting that changes it. Every policy decision and audit event records the contract hash. The human realm only approves or rejects held orders; it cannot edit limits. Production path: replace the constant with a buyer-signed mandate.

### D-004: Two-part contract; client-editable in the full product
- Date: 2026-11-14   Track: 3 (affects 2, 4)   Status: verified (decision) as a full-product idea; its draft design was removed (D-006) and is not in the MVP
- Decision: "In the full feature list, I would like for the contract to be editable by the client only, as part of some sort of settings, but only specific elements. there would be a distribution part of the contract, and a client part of the contract"
- Impact: The contract has a distribution part (Aimo-owned, changed by code release) and a client part (customer-owned). The client part may contain only fields the distribution part lists as client-editable, inside its bounds. The effective contract is the stricter of the two. In the MVP both parts are still frozen constants (D-003).

### D-005: MVP and full design as two parts; customer and agent are separate entities
- Date: 2026-11-14   Track: all   Status: verified (decision); the Type1 draft it refers to was removed (D-006), the customer/agent separation is kept in the MVP (separate buyer login and agent token)
- Decision: "They are technically one device, but two seperate entities. Also, in the architecture for type1, can you write out the elements/contracts as two seperate elements. Requiremnts for MVP, and requiremnets that would make a great product. So we aren't over commiting, but at the same time, we make sure we build a good first product."
- Impact: The Type1 draft has Part A (MVP) and Part B (full product), with seams so the MVP grows into the full design. The approval request goes to the customer through a channel that does not pass through the agent, and the agent's output contains no approval secret.

### D-006: Drop the four tracks, C1 to C5 and the Type1 draft
- Date: 2026-11-14   Track: all   Status: verified
- Decision: "For the conflicts, lets drop the four tracks, and the c1-5. lets also drop the type1 draft.  the plan/post-mvp findings should now be based on the main, maybe we rebase locally to the main, then adopt the pr to work locally on it."
- Impact: PR #4 (`codex/valio-aimo-mvp`) is the base. `docs/architecture.md`, the contract numbering and `docs/drafts/type1-architecture.md` (on the `Init` branch) are not carried forward, and `Plan/post-mvp-plan.md` is deleted on the working branch. PR #3 was already merged into main (`76296c1`), so the findings branch needed no rebase. Old entries keep their `Track:` field for history only.

### D-007: API key fallback and future key provisioning
- Date: 2026-11-14   Track: all   Status: verified
- Decision: "Add the no api key as a fall back, but add notes that it does exist and members of the team will have it. Also lets note in the future build that the api key method needs to be added, either via a UI that the distributor can add, or it is hard coded, but we need to resolve this."
- Impact: `UPSTREAM_MODE=auto` (default) uses the live API when `VALIO_AIMO_API_KEY` is set and labelled fixtures otherwise. The key's provisioning method for the full product is an open decision (admin UI versus deployment configuration), recorded in `docs/brief.md` section 12.

### D-008: Missing scope always blocks (POL-004 / POL-006)
- Date: 2026-11-14
- "Missing scope always blocks; 'allowed' counts as a permitted exception (Recommended)"

### D-009: Remove the agent's spend authority (Q-35)
- Date: 2026-11-14
- "Remove the agent's authority and the autonomous limit; keep each approver's maximum amount and the request's hard budget" and "Remove the spend authority".

### D-010: Guard inside evaluate_purchase (Q-30)
- Date: 2026-11-14
- "Add a guard inside evaluate_purchase"

### D-011: Approver check unconditional (Q-37)
- Date: 2026-11-14
- "Make the check unconditional"

### D-012: Empty approved list means configured (Q-16)
- Date: 2026-11-14
- An empty approved-product list means "configured: every product is outside scope" (relayed by the coordinator; the owner's exact words are in `Assistant/projects/junction/design/2026-11-14-person3-review-log.md`).

## Data (static files in `data/`)

### F-DATA-001: Catalog size
- Date: 2026-11-13   Track: 1   Status: verified
- Finding: The product JSON is a list of 17,546 products, none flagged `deleted`, with 349 distinct `category` values.
- Evidence: `python3 -I` script loading `data/valio_aimo_junction26_product_data.json` and counting.
- Impact: Small enough to load and index in memory (file is about 84 MB).

### F-DATA-002: Lactose-free is a structured field, not just text
- Date: 2026-11-13   Track: 1   Status: verified
- Finding: `synkkaData.classifications` has an entry named `nutritionalClaim` whose values include `{"id": "FREE_FROM_LACTOSE", "unit": "FREE_FROM"}` on 4,178 products. Only 746 products say lactose-free in their name (English or Finnish), so name matching misses most of them. The same claim list also holds `FREE_FROM_GLUTEN`, `VEGAN`, `VEGETARIAN` and others.
- Evidence: counted `values[].id` in classifications named `nutritionalClaim`, and a regex over `synkkaData.names`.
- Impact: Build the dietary filter on the structured claim. Use the name text only as a fallback.

### F-DATA-003: Allergens are structured too
- Date: 2026-11-13   Track: 1   Status: verified
- Finding: Classifications named `allergen` carry `unit` values `CONTAINS` or `MAY_CONTAIN`; `nonAllergen` carries `FREE_FROM`. Codes such as `AM`, `AW`, `AE`, `AN` are used; their meaning is not decoded yet.
- Evidence: value counts over `synkkaData.classifications`.
- Impact: Allergen-safe filtering is possible. Decode the codes (`unverified` until checked against the schema description) before exposing them to agents.

### F-DATA-004: Substitution data is sparse
- Date: 2026-11-13   Track: 1   Status: verified
- Finding: The `substitutions` field is real but sparse and not safe to trust blindly. 189 of 17,546 products (1.1%) have it, as 250 pairs shaped `[{"product": "460025", "substituteProduct": "460150"}]`, covering 83 of 349 categories. Every target exists in the catalog and `product` always equals the owning product. Quality problems: 1 pair substitutes a product for itself; only 63 pairs are reciprocal; 20 of 250 cross categories and 75 change the sales unit (so quantity must be recomputed); in 29 pairs the substitute lists an allergen as `CONTAINS` that the original does not; and of 85 pairs whose original is lactose-free, 12 substitutes lack the `FREE_FROM_LACTOSE` claim (a missing claim is not proof they contain lactose). Many examples are produce origin swaps (for example Dutch tomato to Finnish tomato). Only 3 of the roughly ten real lactose-free milks have a listed substitute.
- Evidence: script over `data/valio_aimo_junction26_product_data.json` counting pairs, categories, claims and `allergen` entries with `unit` = `CONTAINS` (allergen codes are not decoded, and `MAY_CONTAIN` was not checked).
- Impact: Treat the provided pairs as candidates, never as approved substitutions. Re-check claims, allergens, unit and category on every candidate, and send a substitution outside the buyer's stated preferences to a human. Most substitutes must come from our own logic (same category and compatible attributes).

### F-DATA-005: Units and volume need derivation
- Date: 2026-11-13   Track: 1   Status: verified (structure and milk coverage); wider derivation rules still to be tested
- Finding: The unit structure is consistent: for all 17,546 products `salesUnit` and `baseUnit` appear in `units[]`, and the base unit always has `sizeInBaseUnits` 1.0. What is incomplete is volume. `salesUnit` examples: `KI` 8,005; `ST` 5,607; `KG` 1,068. A structured base-level volume exists for about 962 products in litres, millilitres or centilitres; other products use `GRM`, `KGM` or `H87` (pieces) in the same field. A simple single volume can be read from the English name for 3,356 products (for example "1 l", "5 dl"), and 2,487 of those have no structured volume. Where both exist, 848 of 869 agree; 21 disagree and the six I inspected are unit or scale errors in the structured value (for example 20 l soy sauce stored as 20000 litres, 75 ml toothpaste stored as 0.000075). Litres per sales unit = litres per base unit x `sizeInBaseUnits` of the sales unit. For the plain lactose-free milks (about 9) this works for all of them, but four (`462626`, `464119`, `466288`, `469331`) only through the name text, and multipacks such as "100x2 cl" (`463203`) only through the structured value. The 28-product subset also contained non-milk items (fermented and sour milk, margarine, cake bases), so the product type needs a separate filter; category codes have no names.
- Evidence: script over `data/valio_aimo_junction26_product_data.json` (unit consistency counts, volume units, name regex versus structured volume, per-product milk table).
- Impact: Quote needs a two-source resolver (structured volume first when its unit is a volume and it agrees with the name, else name x sales-unit size, else "unknown" and ask a human). Never silently guess. Round up to a multiple of `allowedLotSize`. Counts here were taken with a narrower name pattern (869 compared, 21 disagree); the complete unit catalogue and the final counts (919 compared, 21 disagree, of which only 9 are clean power-of-ten errors) are in F-DATA-009.

### F-DATA-006: Reliability and carbon files are partial
- Date: 2026-11-13   Track: 1   Status: verified
- Finding: Delivery reliability has 4,425 rows and carbon footprint has 11,033 rows, against 17,546 products. Columns: `productId,deliveryReliability` and `productId,AVG kg CO2-eq/kg`.
- Evidence: `wc -l` on the CSV files in `data/` (minus the header).
- Impact: The interface must represent "unknown" explicitly, not zero.

### F-DATA-007: The "lactose-free milk" shortlist is small and the unit maths varies per product
- Date: 2026-11-13   Track: 1   Status: verified (rough filter; the exact shortlist is not yet curated)
- Finding: Filtering `FREE_FROM_LACTOSE` plus milk-like names and excluding yoghurt, cream, drinks and similar leaves 29 candidates, of which roughly ten are real plain milks (Valio and Arla, 0.5 L to 1 L cartons). The filter is crude: it also lets in a flour mix and wafer cones whose names say "milk free". Sales units differ: `464073` Valio whole milk 1 L is sold per `ST` (one carton, 1 L), while `464119` Valio skimmed milk 1 L is sold per `KI` (a case of 10 ST, so 10 L). `unitConversions.volume` is missing for some (for example `462626` 5 dl and `464119`), so litres per sales unit may have to be derived from `units[].sizeInBaseUnits` and the number in the name. Of the 29, 13 have a delivery reliability value, 27 have a carbon value and 3 have `substitutions`.
- Evidence: script over `data/valio_aimo_junction26_product_data.json` joined with the two CSVs.
- Impact: Quote must compute "litres per sales unit" per product and round up to a valid number of sales units. The price API's `comparisonPrice` per litre may avoid doing this just for price comparison.

### F-DATA-008: Order quantity granularity and missing fields
- Date: 2026-11-13   Track: 1, 2   Status: verified
- Finding: `allowedLotSize` is 0.01 for 16,872 of 17,546 products; the others are 1.5, 2, 3, 5, 10 and similar. Per the schema, an order quantity must be a multiple of it, in sales units. 632 products have `variableUnit` true (sold by variable weight). `countryOfOrigin` is absent on some products, and `units[]` sometimes contains odd codes (`ZML`, `KG` with size 1.0) that the schema does not explain. Unit codes, category names and `temperatureCondition` codes are not translated anywhere in the data set.
- Evidence: value counts and a `KeyError: 'countryOfOrigin'` while scanning the JSON.
- Impact: Validate quantities against `allowedLotSize` before quoting; treat origin as optional; do not show raw unit or category codes to users without our own mapping.

### F-DATA-009: Catalogue of unit variations and problems
- Date: 2026-11-14   Track: 1, 2   Status: verified (counts); handling rules are proposals; items marked "unverified" need the webshop, the live API or a mentor
- Finding: The unit *structure* is consistent (every sales and base unit is listed in `units[]`, base size is always 1.0). What varies, and what breaks a "1,000 litres" calculation, is below. All counts are over the 17,546 products in `data/valio_aimo_junction26_product_data.json`.
- Evidence: one analysis script over that file (unit code counts, `units[]` cross-checks, `synkkaData.unitConversions` by packaging level, English-name regex for volume and weight, structured-vs-name comparison, `allowedLotSize` by sales unit). Re-run it before relying on a number after a data refresh.

| # | Variation | What the data shows | Why it matters | Proposed handling |
| --- | --- | --- | --- | --- |
| 1 | Unit codes are untranslated and not uniform across fields | 17 distinct `salesUnit` codes (`KI` 8,005; `ST` 5,607; `KG` 1,068; `PAK` 880; `BAG` 697; `RAS` 328; `PRK` 320; `BOT` 310; then `SK`, `CS`, `KLE`, `KRT`, `KAN`, `PAL`, `NIP`, `DSP`, `DZ`), 16 `baseUnit` codes, 23 codes in `units[]`. `KRS` (5,288), `ZML` (37), `DOL`, `KOR`, `PNT`, `MDO` appear only in `units[]`. The schema says translations are not included. | Cannot tell piece, case or pallet from the code alone. Raw codes are meaningless to an external agent. | Build our own code-to-meaning table from evidence, mark each entry verified or unverified, never expose raw codes alone. Check against the webshop. |
| 2 | Sales unit differs from base unit | 6,622 products (38%) are sold in a different unit from their base unit. 6,602 are multiples (`KI` of `ST` 4,076; `KI` of `PAK` 863; `KI` of `BAG` 534; `KI` of `BOT` 523; `KI` of `PRK` 211; `KI` of `RAS` 187; `KLE` of `BOT` 60). 20 have size 1.0 (an alias unit). The other 10,924 are sold in their base unit. | Prices and availability are per sales unit, while names and volumes usually describe the base unit. | Litres per sales unit = amount per base unit x `sizeInBaseUnits` of the sales unit. |
| 3 | Non-integer pack sizes | 2 products have sales-unit sizes 2.5 and 18.5; the largest size is 400. | Code that assumes whole packs will mis-count. | Keep sizes as decimals. |
| 4 | Ambiguous `units[]` entries | 302 products have two different unit IDs with the same size. 63 list a `KG` unit though they are not sold by `KG`. 37 list `ZML`. No duplicate unit ID within a product. | The packaging level cannot be inferred from size or code. | Use only the entry whose `unitId` equals `salesUnit` or `baseUnit`; ignore the others until decoded. |
| 5 | Variable-weight products | 632 products have `variableUnit` true (628 sold per `KG`, 4 sold per `KI`). The flag exists only where `synkkaData` has it (14,478 products); unknown for the other 3,068. | The actual quantity in a unit varies, so "1,000 units" is not a fixed amount. | Quote variable-weight items in kilograms with a stated tolerance; treat unknown as unknown. |
| 6 | The `volume` field often is not a volume | At the base level, `volume.unit` is `GRM` 5,075, `H87` (pieces) 1,320, `KGM` 833, but only `LTR` 670, `MLT` 242 and `CLT` 50 are true volumes (962 of 8,215 base entries, 5.5% of all products). Stray units: `PTN` 9, `MTR` 7, and a malformed `KGM H87` 3. | Reading `volume.value` as litres gives wrong answers for most products. | Accept a structured volume only when its unit is `LTR`, `MLT` or `CLT`; convert to litres. |
| 7 | Structured volume is mostly missing | `unitConversions` is absent on 3,068 products and empty on 4. Of the rest, 6,259 have no `BASE_UNIT_OR_EACH` entry. Levels present: base 8,215, case 6,249, pallet 10. Case-level volume in `LTR` or `MLT` exists for 92 and 17 products. | Cannot depend on it for the milk request, or any other. | Fall back to the product name; use case-level volume only after confirming the case size. |
| 8 | Structured volume has wrong scale | Where a structured and a name volume both exist (919 products), 21 disagree: x1000 on 4, /1000 on 2, /10 on 3, and 12 that are not a clean power of ten (for example `467856` 4.0 vs 0.01, `468864` 3.0 vs 3.2). Without a name: `LTR` of 200 or more on 5 products (such as 20,000 L for 20 l soy sauce), `MLT` of 5 or less on 2, `MLT` of 20,000 or more on 1, zero or negative on 6. | A single wrong scale silently turns 20 litres into 20,000. | Cross-check structured against name; on disagreement or an implausible value return "unknown" and let a human or the webshop decide. |
| 9 | Name is the only source for many products | 3,370 English names contain a volume token (3,358 with exactly one, 12 with two). About 2,439 of the single-volume names have no structured volume. 2 products have no English name. | Name parsing is necessary but fragile. | Parse only a single, unambiguous token; otherwise unknown. Keep the original text as evidence in the audit trail. |
| 10 | Names describe different packaging levels | 2,102 names start with "N x" and 3,244 contain an NxM pattern. Some names describe the consumer unit (`464119` "Valio skimmed milk 1 l", sold in a case of 10), others the case (`469331` "5 x Arla ... 1 L", sold in a case of 5; `466963` "12 x Arla ... 200 g"). A multipack can also sit inside one base unit (`463203` "100x2 cl", structured 2 L). | Multiplying the multiplier in the name and the sales-unit size counts the pack twice. | Never use the multiplier in the name. Volume comes from the name's single size token, pack count from `units[]`. |
| 11 | Volume and weight both appear | 324 names contain both a volume and a weight (for example "HP Sauce 4,6kg/4L"), and 9,611 names contain a weight. | The price API compares only per L or per KG, so the right dimension must be chosen per product. | Choose the dimension from the request ("litres" means volume) and refuse to guess when both exist. |
| 12 | `allowedLotSize` looks like a placeholder for discrete units | 0.01 on 16,872 products, including every product sold per `ST`, `PAK`, `BAG`, `RAS`, `PRK` or `BOT` and 8,003 of 8,005 sold per `KI` (a literal 0.01 of a case). `KG`-sold products have more than 60 different steps from 0.15 to 25 kg (for example 3.0 kg on 85 products). | A quantity of 0.01 cases is not a real order, yet it passes the schema rule "multiple of lot size". | Unverified: treat 0.01 on a discrete unit as an effective minimum of 1 until the webshop or live API shows otherwise. Apply real lot sizes for `KG`-sold products. Evidence and interpretation in F-DATA-010. |
| 13 | Comparison price covers only L and KG | The price API spec says `comparisonUnit` is only `KG` or `L`. 1,320 base-level volumes are in pieces (`H87`). | Items counted in pieces have no per-unit comparison price. | Verified for litre products on 9 milks (F-API-003). Still unverified for pieces: do not rank piece-counted items by comparison price. |

- Impact: The Quote contract needs a litres-per-sales-unit resolver with three outcomes (resolved, resolved with a warning, unknown) and an explicit lot-size rule. It also needs the webshop or live API to confirm rows 1, 12 and 13. The milk request is not blocked by any of this (see F-DATA-005), but the generic "N litres of X" case is.

### F-DATA-010: What `allowedLotSize` 0.01 most likely means
- Date: 2026-11-14   Track: 1, 2   Status: verified (counts); interpretation unverified (no order endpoint, no mentor)
- Finding: 674 products have a lot size other than 0.01. 672 of them are sold per `KG` (the other two are sold per `KI`, with lot sizes 1.0 and 2.0). 535 of the 672 `KG` products are variable-weight. For 267 of the 674 (40%) the lot size equals one of the pack sizes in the product's own `units[]` (for example a lot of 3.0 kg equal to a 3 kg pack), so the lot reflects a real packaging step. In contrast every product sold per `ST`, `PAK`, `BAG`, `RAS`, `PRK` or `BOT` has 0.01, as do 396 `KG`-sold products. In the live sample, all 130 Stock availability amounts were whole numbers, including all 15 `KG`-sold ones (F-API-010).
- Evidence: offline script over the product JSON; availability sample of 299 products for 2026-11-16.
- Impact: 0.01 reads as a default meaning "no packaging step recorded", not a real 0.01 of a carton. Real steps exist mainly for weight-sold goods. Working rule in F-OPEN-001: whole sales units for discrete units, the stated lot size for `KG` goods.

### F-DATA-011: `temperatureCondition` codes can be decoded from storage temperatures
- Date: 2026-11-14   Track: 1   Status: derived from data (the dataset gives no code meanings)
- Finding: Median `minTemperature` / `maxTemperature` per code, with the number of products in the whole catalogue (and, in brackets, those that have temperature data):

| Code | Products | Median storage range | Reading |
| --- | --- | --- | --- |
| 8 | 10,053 (5,137) | 10 to 22 C | ambient (room temperature) |
| 7 | 3,152 (2,341) | -25 to -18 C | frozen |
| 4 | 1,803 (825) | 4 to 8 C | chilled |
| 3 | 1,673 (1,348) | 2 to 6 C | chilled |
| 2 | 324 (252) | 2 to 4 C | chilled |
| 1 | 240 (158) | 0 to 3 C | chilled, coldest class |
| 5 | 221 (13) | 2 to 7 C | chilled (little data) |
| 6 | 10 (4) | 4 to 20 C | unclear (little data) |
| 9 | 9 (5) | 0 to 2 C | chilled (little data) |
| none | 61 | n/a | the field is absent |

- Evidence: median of the two temperature fields per `temperatureCondition` over `data/valio_aimo_junction26_product_data.json`.
- Impact: Safe to label 7 as frozen and 8 as ambient; treat the rest as "chilled, range varies". Useful for a delivery or cold-chain constraint. In the live sample, all 7 products in class 1 had no delivery on any date (F-API-010), too few to conclude anything.

### F-DATA-012: Two products list the same allergen as both present and free-from
- Date: 2026-11-14   Track: 1   Status: verified
- Finding: Product `468044` lists allergen code `AM` as `CONTAINS` in the `allergen` group and `FREE_FROM` in the `nonAllergen` group. Product `469429` does the same for `AM` and `AN` (`MAY_CONTAIN` against `FREE_FROM`). These are the only 2 of 17,546 products with a code in both groups. The conflict was first reported in PR #2's plan; the check was repeated here.
- Evidence: script over `data/valio_aimo_junction26_product_data.json` intersecting the code sets of the `allergen` and `nonAllergen` classification groups.
- Impact: A positive free-from flag alone is not enough to claim a product is safe. Mark the allergen evidence `conflicting`, never `free from`, and send such an item to a human or exclude it.

## Live API (from the OpenAPI spec, then probed)

### F-API-001: What the spec says
- Date: 2026-11-13   Track: 2   Status: partly verified on 2026-11-14 (see F-API-002 to F-API-006); the missing order endpoint, rate limits and Terminal behaviour beyond the probe are still from the spec only
- Finding: Endpoints are `/api/ping`, `/api/availability`, `/api/price` and three download endpoints; there is **no order endpoint**. Each price or availability request takes 1 to 1,000 product codes. The customer number does not affect responses. Rate limits exist but are undisclosed. For Terminal products `availableAmount` is always 999999 because the real stock is unknown. `scheduleLines` is empty when a product cannot be delivered on any date. Auth is an `X-API-Key` header.
- Evidence: the `description` fields in the OpenAPI file.
- Impact: Ordering is our mock. Treat Terminal availability as "unknown but orderable" and check `closingTime`, `salesBlock` and `availableDate` against the requested date.

### F-API-002: First live probe works
- Date: 2026-11-14   Track: 2   Status: verified
- Finding: `GET /api/ping` returned 200 `{"status":"ok"}`. One `POST /api/availability` and one `POST /api/price` for 9 plain lactose-free milk products (customer `123`, requested date 2026-11-16) both returned 200 and matched the response shapes in the spec. No rate-limit headers were returned in these 4 requests. Server time in the response was `2026-11-14T02:16:44+0200`; currency EUR; every product had tax rate 13.5%.
- Evidence: `probe.py` in the session scratchpad (not in the repo); product IDs 464073, 464119, 464201, 464237, 463380, 464440, 462626, 466288, 463203.
- Impact: Quote can be built against the real mock API now. Rate limits are still unknown (undisclosed), so keep requests to the shortlist and cache.

### F-API-003: Per-litre comparison price confirms the unit derivation
- Date: 2026-11-14   Track: 1, 2   Status: verified for these 9 products
- Finding: `catalogPrice` is per sales unit and `comparisonPrice` per litre. Dividing one by the other gave litres per sales unit within 0.2% of what F-DATA-009 derives from the data (rounding of the 2-decimal prices explains the gap) for all 9, including the four that depended on the product name (`462626` 5 L, `464119` 10 L, `466288` 3.75 L) or on a multipack structured value (`463203` 2 L).
- Evidence: `catalogPrice.value / comparisonPrice.value` against the derived litres, from the saved probe responses.
- Impact: The resolver rule in F-DATA-009 is validated for milk. The same ratio is a cheap cross-check for any litre product after a live call (the rounding error grows for cheap items, so use it as a check, not as the source).

### F-API-004: The API does not enforce the order cut-off
- Date: 2026-11-14   Track: 2   Status: verified (observation); interpretation of `closingTime` unverified
- Finding: For delivery on 2026-11-16, Stock products showed `closingTime` 2026-11-15T17:00 (the day before). The three Terminal products (`464119`, `462626`, `466288`) showed `closingTime` 2026-11-12T15:00, which was already about two days in the past at the server time of 2026-11-14T02:16, yet they still returned `availableDate` 2026-11-16, amount 999999 and a price.
- Evidence: availability responses in the probe.
- Impact: If `closingTime` is the order cut-off for the requested date (as the spec says), the API alone would let us offer something that can no longer be ordered. Our Quote layer must compare `closingTime` with the current time and mark the offer "cut-off passed". The demo result depends on the clock, so decide how the mock treats time (real clock, fixed demo clock, or a later requested date). Confirm with a mentor. Update 2026-11-14: F-API-008 shows what the cut-off and `availableDate` appear to be, and F-OPEN-001 gives the working rule.

### F-API-005: Availability has placeholders, partial stock and "not deliverable" in real data
- Date: 2026-11-14   Track: 2   Status: verified
- Finding: Three Stock products (`464073`, `464201`, `464237`) report `availableAmount` 9,999,999,999, so "Stock means a real quantity" does not always hold. Others report real, limited stock: `463380` 698 cartons (698 L, short of 1,000 L by 302 L) and `463203` 192 cases of 2 L (384 L). `464440` returned an empty `scheduleLines` with no `closingTime` or `logisticModel`, yet its price was returned normally. Terminal products show 999999 as documented.
- Evidence: availability responses in the probe.
- Impact: The partial-availability and "cannot be delivered" cases occur naturally in the milk request, so they can be demonstrated with real mock data rather than invented. Treat very large Stock amounts as "not limited", not as inventory.

### F-API-006: Price fields beyond the spec summary
- Date: 2026-11-14   Track: 2   Status: verified (values); meaning of `netPriceFound` unverified
- Finding: `listPrice` was higher than `catalogPrice` for all 9 (for example 1.95 vs 1.64 for `464073`, 1.83 vs 1.56 for `464201`). `netPriceFound` was true for 4 of 9 and false for the others, even though the spec says the customer number is ignored, and the list/catalog gap exists in both groups. Validity windows differ: `464073`'s price is valid 2026-09-01 to 2026-12-31, while `464201`'s runs to 9999-12-31.
- Evidence: price responses in the probe.
- Impact: An offer's expiry must not exceed the price's `validTo`. Do not use `netPriceFound` for logic until a mentor explains it. Update 2026-11-14: F-API-009 explains it with good evidence (it matched a time-limited price in 5 of 5 cases in a 299-product sample).

### F-API-007: Use the right host; the webshop blocks scripted clients
- Date: 2026-11-14   Track: all   Status: verified
- Finding: The API host is `https://junction26.valioaimo.fi` (the address in the team's own `curl` test). `AIMO_API_BASE_URL` had been set to the webshop address (the value kept in `AIMO_WEBSHOP_URL`). A request to that host from a Python client was refused with HTTP 403 and a Cloudflare "Error 1010: Access denied" page. The API host accepted the same kind of request with a plain descriptive `User-Agent`.
- Evidence: the first probe run against the webshop host (403) and the second against the API host (200).
- Impact: Keep the API key off the webshop host. Scripted webshop checks are likely to be blocked by bot protection, so webshop comparisons should be done by hand in a browser, and we do not try to bypass the protection.

### F-API-008: `closingTime` and `availableDate` do not depend on the requested date
- Date: 2026-11-14   Track: 2   Status: verified (observations); meaning inferred
- Finding: At server time Saturday 2026-11-14 02:34 (Helsinki) I sent the same 69-product availability request (the 9 milks plus 60 random products) for 13 different `requestedDate` values: every day from Fri 2026-11-13 to Mon 2026-11-23, then 2026-12-24 and 2027-01-15. For every date: (a) each product's `closingTime` was identical. Stock products closed Sun 2026-11-15 17:00 (30 of 34) or Fri 2026-11-13 13:00 (4 of 34); Terminal products closed Thu 2026-11-12 between 14:00 and 16:00 (15:00 for 9 of 19). (b) `availableDate` was Mon 2026-11-16 for every Stock and Terminal product, even when asking for 2027-01-15, so it is the earliest possible delivery date, not an answer for the requested date. (c) 16 of the 69 had empty `scheduleLines` and no `closingTime` on every date. (d) The cut-off had already passed for 4 Stock products and all 19 Terminal products, yet they were still offered for Monday.
- Evidence: availability responses from the second probe script (session scratchpad, not in the repo; it can be added under `scripts/` if wanted). Product sample is seeded, so it is reproducible.
- Impact: Two readings fit. H1: the API is clock-driven and the cut-offs roll forward as time passes. H2: it is a fixed timetable that does not use the current time (so the passed cut-offs are never updated). A test separates them: repeat the same call after Sun 2026-11-15 17:00 and again on Monday, and see whether `closingTime` and `availableDate` change. Until then treat `closingTime` as advisory; our Quote layer compares it with the current time and marks `cutoff_passed`.

### F-API-009: `netPriceFound` marks a time-limited agreement price; price validity is not enforced
- Date: 2026-11-14   Track: 2   Status: verified (counts); meaning is the best fit, not confirmed
- Finding: In a sample of 299 real products plus 2 invented codes (customer `123`, requestedDate 2026-11-16), `netPriceFound` was true for 5 products (1.7%), and all 5 had a `catalogPrice.validTo` of 2026-12-31. The other 294 had `validTo` 9999-12-31. Repeating with customer `999` changed nothing (0 of 301 prices, 0 flags). Repeating with requestedDate 2027-01-15, after those five prices expire, also changed nothing and returned no errors. `catalogPrice` was below `listPrice` for all 299 (net: 15.9% to 33.3% lower, median 26.4%; others: 0% to 20.2% lower, median 18.0%). Invented codes returned HTTP 200 with `error` true, a null `catalogPrice` and `netPriceFound` false; none of the 299 real products had `error` true, including the 63 with no delivery. `comparisonUnit` was `KG` for 200, `L` for 40 and absent for 59 (20%). Tax was 13.5% for 236 products and 25.5% for 63.
- Evidence: three price calls on the same 301 codes (second probe script, session scratchpad). The earlier "4 of 9" in F-API-006 came from a hand-picked milk set, which is why it looked high.
- Impact: Most likely meaning: a customer-agreement (net) price with an end date exists for this product. Because the customer is ignored in the mock, it is the same for everyone. The API never rejects an expired price, so our offer expiry must be the earlier of our own validity window and the price's `validTo`, and we check it ourselves. `error` means "unknown product code" and is the only reliable not-found signal.

### F-API-010: Stock, Terminal and "no schedule" in a 299-product sample
- Date: 2026-11-14   Track: 2   Status: verified
- Finding: For 2026-11-16: Stock 130 (43%), Terminal 106 (35%), no schedule line 63 (21%; those also have no `logisticModel` or `closingTime`, but still have prices). The split is not explained by vendor (33 of 164 vendors have both Stock and Terminal products, for example Valio Oy Tuore with 5 and 9), by category (45 of 158 categories have both) or by temperature class (most classes have both). Stock amounts: 100 real numbers and 30 (23%) placeholders of 9,999,999,999 (26 non-`KG`, 4 `KG`). All Stock amounts were whole numbers, including all 15 `KG`-sold ones. Two schedule lines carry a different `salesUnit` from the product file: `461893` (file: `KI`, a case of 10 `ST`; API: `ST`) and `476230` (file: `ST`; API: `PAK`, a pack of 12 `ST`).
- Evidence: one availability call for 299 products (second probe script, session scratchpad).
- Impact: Stock versus Terminal is a per-product property, so it cannot be inferred from vendor or category; read it from each response. About 1 in 5 catalogue products are currently undeliverable, and offers must say so instead of silently dropping them. Read the unit from the schedule line, not the file. Which of the two is right for the 2 mismatches is unverified.

## Interpretations of unexplained variables (no mentor access)

### F-OPEN-001: What the open variables most likely mean, and the rule we use meanwhile
- Date: 2026-11-14   Track: all   Status: interpretations; confidence stated per row; replace with the mentor's answer when available
- Finding: Best readings from the data and live API. Evidence is in the findings named in the last column.

| Variable | Most likely meaning | Confidence | How to confirm | Working rule | Evidence |
| --- | --- | --- | --- | --- | --- |
| `closingTime` | The order cut-off for the product's earliest delivery. Stock: the evening before delivery (Sun 17:00 for Monday). Terminal: about four days earlier (Thu ~15:00), consistent with extra time to pass the order to a supplier. | Medium on meaning, low on clock behaviour | Repeat the probe after Sun 17:00 and on Monday (H1 clock-driven vs H2 fixed timetable) | Advisory. If now is after `closingTime`, mark the offer `cutoff_passed` and send it to a human instead of auto-approving. | F-API-004, F-API-008 |
| `availableDate` | The earliest possible delivery date. It ignores the requested date (same Monday for requests up to 2027-01-15). | High | Already shown across 13 dates | Compare it with the requested date: later means late delivery. Never treat the requested date as confirmed. | F-API-008 |
| `requestedDate` (availability and price) | No observable effect on availability or price in these probes. | Medium | Probe after midnight and with fresh dates | Pass it, but do not depend on the API to validate it. | F-API-008, F-API-009 |
| `netPriceFound` | A customer-agreement (net) price with an end date (here 2026-12-31) exists. Only 1.7% of products. | Medium-high (5 of 5 matched) | A larger sample (up to 1,000 codes in one call) | Show as an "agreement price" label. Do not branch logic on it. | F-API-009 |
| `catalogPrice.validTo` | The end of the price's validity. Not enforced by the API (a price expiring 2026-12-31 was returned unchanged for 2027-01-15). | High on behaviour | Already shown | Offer expiry = the earlier of our window and `validTo`; check it ourselves. | F-API-009 |
| `error` (price) | The product code is unknown. | High | Already shown with invented codes | Use as the not-found signal. A product with no delivery is not an error. | F-API-009 |
| `logisticModel` Terminal | The supplier ships directly from their warehouse; Aimo cannot see stock (amount fixed at 999999). An order is a request that depends on the supplier. | Medium (matches the API description and the earlier cut-offs) | Webshop behaviour or a mentor | Order state `pending_supplier_confirmation`, and an `availabilityBasis` field of `unknown_terminal` so an agent knows the claim is unverified. | F-API-001, F-API-008, F-API-010 |
| `availableAmount` 9,999,999,999 | Stock that is not tracked, effectively unlimited (23% of Stock lines). | Medium | Webshop or mentor | Present as "not limited"; do not compute a fill ratio. | F-API-005, F-API-010 |
| Empty `scheduleLines` | Not deliverable on any date right now (21% of the sample); price still exists. | High | Already shown | Return `unavailable` with a reason; never drop the product silently. | F-API-005, F-API-010 |
| `allowedLotSize` 0.01 | A default meaning "no packaging step recorded", not a literal 0.01 carton. Real steps exist for 674 mostly weight-sold products. | Medium | Webshop quantity field or a mentor | Whole sales units for discrete units; the stated lot size for `KG` goods. | F-DATA-010 |
| `salesUnit` in availability | Usually equals the file. Two of 236 lines differ. | Low on which is correct | Webshop | Read the unit from the schedule line; if it differs from the file, flag and convert via `units[]`. | F-API-010 |
| `comparisonUnit` absent | The product has no per-litre or per-kg price (about 20%, mostly counted goods). | Medium | Already shown in count | Do not rank those items by comparison price. | F-API-009, F-DATA-009 row 13 |
| `temperatureCondition` | 8 ambient, 7 frozen, the rest chilled in graduated ranges. | Medium (derived from medians) | Mentor or webshop labels | Label 7 and 8 only; treat the others as "chilled". | F-DATA-011 |

- Evidence: see the Evidence line in each referenced finding.
- Impact: These rules are defaults for the build, not facts. Each one that matters in the demo should be named as an assumption in the submission (the brief asks for visible assumptions), and replaced as soon as a mentor answers.

## Brief

### F-BRIEF-001: Deadline is unclear
- Date: 2026-11-13   Track: all   Status: unverified
- Finding: The challenge page showed "Status: Closed" and a countdown of about 12 hours 47 minutes when the brief was saved. It is not clear whether that is the submission deadline.
- Evidence: `local/project-brief.raw.txt` (gitignored).
- Impact: Confirm the official deadline on the event platform before planning scope.

## Track sections

Add new findings below, under your track heading.

### Track 1: Catalog and Discovery

#### F-SEARCH-001: Hosted Qwen search verified on the complete catalog
- Date: 2026-11-14   Track: 1   Status: verified (local PostgreSQL and live OpenRouter); deployed cutover unverified
- Finding: The supplied SHA-256-verified snapshot imported all 17,546 products into a separate local evaluation database with 4,096-dimensional Qwen3 Embedding 8B vectors. An interrupted run resumed with 192 cached embeddings and generated the remaining 17,354. All normalized products validated against the product schema; the evaluation database including its embedding cache occupies approximately 698 MB. No production database or Kubernetes configuration changed.
- Evidence: `docs/search-evaluation-openrouter.json`, `docs/search-reranker-comparison.json`, and `scripts/evaluate_search.py`. Hybrid search with Qwen3 Reranker 8B found a labeled top-five result in 20/21 descriptive cases, versus 17/21 in the saved E5 baseline and 19/21 with Reranker 0.6B. Two 8B reranker runs had 12–14/21 labeled top-one results (baseline 12/21) and 2.1–2.9 second descriptive median latency. Both passed all six identifier and three exclusion cases, with zero supported dietary-filter violations or reranker outages. The remaining top-five miss was `Snellman naudan kuve`. These are curated, incompletely labeled regression cases, not a held-out benchmark; the baseline also used different document text, and hosted rankings/timings varied between runs.
- Impact: Select the 8B embedding/reranker profile as an opt-in candidate-retrieval upgrade, without claiming first-result correctness or a universally best model. Migration 005, resumable batch caching, staged imports, exact filtered ranking and explicit profile-matched cutover/rollback preserve existing catalogs and purchasing history. Readiness does not spend API tokens. `165` backend tests, Python lint and the frontend production build passed locally. Cloud latency/capacity and operator rollout remain separate from this PR.

### Track 2: Quote and Order

### Track 3: Mandates, Policy and Approvals

### Track 4: Interface, Audit and Demo

## MVP implementation verification

### F-MVP-001: Explicit implementation handoff resolves the draft seams
- Date: 2026-11-14   Track: all   Status: verified
- Finding: The implementation request explicitly selected PR #2's final brief: PostgreSQL-seeded versioned buyer policy, eight tools, four outcomes, independent React inbox, ordinary audit history, persistent mock orders, and no live deployment. PR #2 was closed without merge; PR #3 is on main. The implementation branch starts at main `76296c1` and preserves the alternate draft and prior findings as reference.
- Evidence: User-provided implementation handoff; `gh pr view 2 --json state,mergedAt`, `gh pr view 3 --json mergeCommit`; `docs/brief.md` restored from `b0d1ee3` with its implementation-status note updated.
- Impact: For this implementation, the handoff supersedes conflicting draft recommendations about policy storage, notifier, hash chaining, tool names and whether approval repairs unresolved facts. It does not rewrite or misattribute the historical owner quotes above.

### F-MVP-002: Seven golden cases reverified; lettuce also has variable weight
- Date: 2026-11-14   Track: 1, 2   Status: verified
- Finding: The identified 17,546-product snapshot supports 1,000 L → 1,000 ST for `464306`; `465039` has five ST per KI but no structured base volume; ten KI of `460123` entails 120 bottles/deposit units; `460675` rounds 12 KG to 20 KG. `460035` rounds 4 KG to 6 KG **and also has `variableUnit=true`**, so it cannot be committed by the fixed-quantity MVP. The two reported allergen conflicts retain their distinct CONTAINS and MAY_CONTAIN relationships.
- Evidence: `uv run python scripts/verify_catalog.py /absolute/private/valio_aimo_junction26_product_data.json`, SHA-256 `50651aae31ca842112afdc16fcce92f9858d7f5d05e9928a3748aef16b22ea02`. No raw records exported. Unit/deposit meaning checked against the local supplied schema.
- Impact: Names are corroboration only, not a missing physical-volume source. Quantity rounding can be explained for variable-weight products, but commercial settlement remains unresolved. Deposit pricing also requires a known conversion from the declared deposit unit to the material's priced sales unit; missing deposit material facts are not assumed.

### F-MVP-003: Full indexing and limited retrieval evaluation completed
- Date: 2026-11-14   Track: 1   Status: verified
- Finding: Full ingestion published 17,546 products and pinned multilingual E5 embeddings. An unchanged rerun generated zero new embeddings and reused 17,546. The 30-case curated evaluation found a labeled top-five result (or correct exact-ID exclusion) in 21/30 keyword, 26/30 semantic and 26/30 hybrid cases, with zero supported dietary-filter violations. Hybrid top-one was 21/30. Warm median latency on this machine was about 77 ms; first model load was about 4.5 s.
- Evidence: `scripts/evaluate_search.py`, `docs/search-evaluation.json`, explicit full-snapshot ingestion/rerun. Six identifier cases, 21 descriptive cases, three exact-ID dietary exclusion cases; this is not a held-out benchmark. HNSW iterative scanning is enabled to preserve recall with generation/dietary filters.
- Impact: Keep the multilingual model pinned as the MVP candidate, not a proven best model. Broad English milk queries still rank adjacent flavored/sweet categories too highly. Agents must inspect candidates, choose explicit requirements and obtain commercial evidence. Retrieval similarity never proves suitability.

### F-MVP-004: Application checks use fixture commerce, not freshly verified live stock
- Date: 2026-11-14   Track: all   Status: verified
- Finding: Autonomous purchase, independent buyer inbox/approval/resume, rejection, denied versus unresolved requests, concurrent decisions/commits, changes, expiry, revocation and retries were exercised against real PostgreSQL and explicitly invented commercial fixtures. The official MCP SDK was exercised over stateless HTTP. Browser tests include two-tab conflict and paused polling. Raw source data and credentials are excluded from Git and images.
- Evidence: `tests/`, `frontend/e2e/`, `scripts/mcp_smoke.py`, `scripts/demo.py`, and `docs/validation.md`.
- Impact: There was no configured live Valio API key in the available project environment, so this session does not independently reproduce F-API-002 through F-API-010. `scripts/probe_upstream.py` is the bounded read-only probe for when access is supplied. Upstream lookups are read-only; every receipt is explicitly mock acceptance with no reservation or supplier order.

### F-MVP-005: Authority, revision history and output contracts verified after PR #4 review
- Date: 2026-11-14   Track: all   Status: verified
- Finding: Commercial fingerprints alone do not capture changes in agent authority. Commit now compares the effective authorization decision under the buyer/identity locks and persists a new revision plus any required approval. Historical approval pages attach accepted status only to the order's exact revision and link to authenticated current terms. All eight HTTP/MCP operations now export shared typed responses, including both commit outcomes. Swagger renders with a documentation-specific nonce/CSP; the buyer UI's CSP remains strict.
- Evidence: 53 backend tests, six Chromium browser flows, all eight official-SDK tool calls, TypeScript/Vite build and Ruff passed. The new product response model also validated all 17,546 existing normalized products. See `docs/validation.md` for the scope, isolated databases and current limitations.
- Impact: An agent-limit reduction produces actionable approval or resolution state without editing the buyer policy version. Superseded terms cannot be mislabeled as accepted, including after later autonomous commitment. Generated OpenAPI/browser contracts describe the actual wire responses. These checks use fixture commerce; no new claim about live integration or cluster deployment is made.

### F-MVP-006: Second review verifies policy, retry and runtime boundaries
- Date: 2026-11-14   Track: all   Status: verified
- Finding: On `ea8e9aa`, omitting a substitution flag avoided substitution policy because no trusted product scope existed; Decimal pack division could round an exact six packs up to seven; repeated preparation created duplicate proposals; file ingestion discarded withdrawal markers; successful logins consumed the failure budget; MCP repeated synchronous authentication; a 20-item inbox used 164 queries. Permanent supplier errors were retried, although transient responses already had backoff. Old catalog generations remained indexed; actual filtered-HNSW recall loss was not reproduced in the existing query plan.
- Evidence: New regression coverage and `docs/validation.md`: 97 backend tests, six browser flows in the rebuilt read-only container, eight official MCP tools, HTTP demo and process restart passed. Inbox now uses six statements excluding outer authentication/pool checks. A read-only rerun on 17,546 existing products retained 26/30 hybrid top-five hits/correct exclusions with zero supported constraint violations; median 90.6 ms on this machine.
- Impact: Trusted versioned product scope closes the undeclared outside-scope selection path, with privileged setup and fail-closed missing configuration. It is standing product authority, not an arbitrary mission-intent verifier. Preparation has atomic buyer/agent-scoped deduplication; quantities use rational ceilings; withdrawn products receive explicit denial. Login/proxy handling, bounded pooling/cleanup/retries and batched reads stay in the same backend. Exact active-catalog ranking removes approximate scan-limit dependence; imports retain active/previous product generations while preserving evidence history. New migration/client/setup requirements are explicit; live supplier and cluster claims remain unverified. F-MVP-003's iterative-HNSW statement describes the initial implementation, superseded by this exact-ranking change.

## Chat purchasing cutover

### F-CHAT-001: Internal chat preserves the purchasing control boundary
- Date: 2026-11-14   Track: all   Status: verified (fixture/provider and local runtime); live provider/cluster ingress unverified
- Finding: The existing React/FastAPI image now owns customer chat, typed direct Service tools, persisted conversation recovery and exact-revision browser confirmation. Migration 003 is additive and starts internal agents at zero autonomous authority without changing the buyer product scope. MCP/external-agent routes and dependency are removed; historical identity/proposal/approval/order references remain.
- Evidence: `tests/test_agent_integration.py`, `tests/test_conversations.py`, `frontend/e2e`, generated browser contracts, and `docs/chat-purchasing.md` contain the current checks and limits. The carbonara fixture exercises five catalog matches and the actual quantity/policy/order modules; a local production-image restart retains session/messages/decision/receipt. Local Traefik streams the snapshot/heartbeat and observes logout revocation.
- Impact: The backend, frontend and agent workstreams are integrated for review. Recipe agreement/model text cannot authorize purchasing. Changed terms require a new customer click. Apply neither Terraform nor release/deployment steps as part of this task. Live LLM and selected-cluster ingress still need operator acceptance after configuration/deployment.
### F-MVP-007: Live Valio API check with the real key
- Date: 2026-11-14   Track: all   Status: verified
- Finding: With the real key the connector returns valid price and availability for the shortlist (HTTP 200 from `/api/price` and `/api/availability`). Live stock for `463380` is 698 sales units and the full purchase flow works on it: `ready_to_commit`, mock commit, identical receipt on retry. Live stock for `464306` (the fixture demo milk) is the unknown-quantity sentinel `9999999999`, so the app correctly returns `needs_resolution` / `UNVERIFIED_STOCK` and nothing can be committed. The substitute `464398` is also `UNVERIFIED_STOCK`, so the split-purchase approval path cannot be shown live with these two products.
- Evidence (the sweep behind these numbers drove the agent API removed by PR #15; the live-stock facts stand, the sweep has since been rewritten): `tests/ci.sh --live` (12 passed / 3 skipped / 0 failed with the default product) and `SWEEP_ARGS="--product 463380" tests/ci.sh --live` (14 passed / 1 skipped / 0 failed), 2026-11-14, pytest 51 passed. Earlier bounded call for `463380` and `464306`, delivery date 2026-11-16, customer `123`. The sweep prints the mode used; no key or raw responses are stored.
- Impact: The live demo needs a product with finite stock (`463380` works). The approval-path demo needs a finite-stock substitute pair or the labelled fixtures; do not present fixture stock as live. Updates F-MVP-004: the commercial connector is now exercised live; F-API-002 to F-API-010 are still individually unrepeated.

### F-MVP-008: Python coverage measured and gated; frontend coverage not implemented
- Date: 2026-11-14   Track: all   Status: verified (local run, fixtures); the GitHub workflow has not been run
- Finding: Line plus branch coverage of `src/aimo` with 57 pytest tests alone is 84.5%. The sweep-driven server (uvicorn under `coverage run`, plus the migrate/seed/fixture-catalog CLI steps) alone is about 73%, and the two combined are about 87% (87.5% and 87.1% in two runs). The sweep reaches 43 lines pytest does not, mostly `cli.py` (26) and `api.py` (11). Weakest files: `ingest.py` 51% (file download/ingest), `cli.py` 69%, `upstream.py` 81% (live HTTP branches), `purchases.py` 83%, `catalog.py` 86%. Gate is `fail_under = 84` on the combined total (about 3 points of slack). Traps: pytest-cov enforces `fail_under` on pytest-only data (84.5%, borderline), so `tests/ci.sh` passes `--cov-fail-under=0`; `uv run` in CI would sync torch unless `UV_NO_SYNC=1`; the server's coverage data is written only when uvicorn exits, so `tests/ci.sh` waits for it. `pytest-cov` and `coverage` were added to the dev group; the locked, pruned, hash-pinned install in `ci.yml` still resolves them (checked with `uv export --locked --prune torch --prune sentence-transformers` and `uv pip sync --require-hashes`). Frontend: no coverage, because the browser specs read a `.env` for credentials and are being reworked for `tests/ci.sh --browser`, and any approach needs a coverage fixture wrapping `test` in the specs. Options: (a) `vite-plugin-istanbul` (supports vite >=7) in a coverage-only build, collecting `window.__coverage__` in a Playwright fixture, then `nyc report`; (b) Playwright `page.coverage` V8 JS coverage plus a sourcemap and `v8-to-istanbul`. Both measure only `frontend/src/main.tsx` (704 lines; `api-types.ts` is generated).
- Evidence: `CI_COVERAGE=1 tests/ci.sh` (ruff passed, pytest 57 passed, sweep 15 passed, 0 failed) and `tests/coverage_report.py`, own databases `aimo_cov_test` and `aimo_cov_ci`; gate failure path checked by temporarily setting `fail_under = 99` (exit 1). `tests/ci.sh` without `CI_COVERAGE` run again: pytest 57 passed, sweep 15 passed, no leftover server, no `.coverage/`.
- Impact: Re-measure and adjust `fail_under` when tests or code change substantially. Treat the sweep-only number as the sweep plus CLI setup.
- Update 2026-11-14 (night): frontend coverage is not measured and no UI tests run in CI. Vitest component tests were tried (82.6% of `main.tsx` lines) and then dropped on the owner's decision because the UI is an old mockup. Options (a) and (b) above remain unimplemented.

### F-MVP-009: Combined Python coverage 96.5%, gated at 95% in CI
- Date: 2026-11-14   Track: all   Status: verified
- Finding: After 173 new tests, line and branch coverage of `src/aimo` was 99.8% on the PR #4 head `ea8e9aa`. Re-measured after merging `develop` (Otto's hardening `dfb8871`: 99.4%, 282 tests; then the chat cutover PR #15 `f13b75b`: 96.5%, 317 tests (327 after the frontend-fixture tests), because `agent.py` and the streaming part of `api.py` are only 84% covered); 41 of the new tests had to be updated to the hardened behavior (typed `PrepareRequest` with a required `idempotency_key`, approved-product scope, jittered backoff and specific upstream error codes, withdrawn products retained, `forwarded_allow_ips`). `fail_under = 95` in `pyproject.toml` is enforced by the CI job "Coverage (95% minimum)", which the `CI gate` waits for. Not reached: the unreachable final `raise` in `ValioClient.post` and one impossible `main()` branch. Mutation spot-check: breaking the 429 retry, the spending-limit comparison (`>` to `>=`) and the idempotency payload check each made the suite fail. The earlier oddity that `ValioClient.post` retried 401/403 is gone: `develop` now rejects permanent 4xx at once (`UPSTREAM_REJECTED`).
- Evidence: `CI_COVERAGE=1 SWEEP_ARGS=--strict tests/ci.sh --browser` (the browser option has since been removed; first run on `ea8e9aa`: 230 pytest passed, sweep 17/17, browser 6/6; gate PASS at 95, FAIL at 100). Again on the merge with PR #15: 317 pytest passed and sweep 10/10 locally (327 while the frontend fixture test existed), combined 96.47%, gate PASS with only 1.5 points of margin. The GitHub workflow itself has not run.
- Impact: 95% measures Python only; `frontend/src/main.tsx` is not measured (F-MVP-008). Coverage is not correctness: weak assertions listed in `tests/TEST-GUIDE.md` section 8 still exist.

### F-MVP-010: Sweep checks distinguish configured mode from live evidence
- Date: 2026-11-14   Track: all   Status: verified (fixture and mocked supplier transport)
- Finding: The HTTP sweep does not query the supplier and now labels only the configured mode. `tests/ci.sh --live` first queries both Valio price and availability through the live connector and existing evidence validator; missing keys, upstream errors and unresolved evidence fail before the HTTP server starts. The standalone sweep tests message CSRF rejection without sending an authenticated chat turn.
- Evidence: `tests/test_sweep.py` (8 regression cases); full local run: 325 pytest tests, strict sweep 10/10, combined coverage 96.47%. Supplier success/error responses were mocked; no real supplier or paid LLM was called during this verification.
- Impact: A live pass requires validated supplier evidence. Running the standalone sweep against an LLM-configured app does not trigger a valid chat request or store an assistant response.

### F-SEARCH-002: Hosted search follows the separate worker deployment
- Date: 2026-11-14   Track: 1   Status: verified (local integration); deployed cutover unverified
- Finding: After integration with the frontend/API/worker split, only the worker/importer receives `SEARCH_API_KEY`. Both API and worker check the active embedding profile/dimension, while the worker also checks credential presence without provider calls. The hosted migration is `005_hosted_search.sql`, after `004_worker_queue.sql`.
- Evidence: All 217 backend tests passed against a fresh isolated PostgreSQL/pgvector database; frontend build and Python lint passed. All three architecture diagrams rendered. Terraform validation, eight mocked plans and 28 infrastructure helper tests passed, including profile/credential separation.
- Impact: The staged import and coordinated API/worker cutover remain explicit operator steps. No production configuration, database or deployment was changed.


## Recipe planning

### F-RECIPE-001: Recipe completeness and pack conversion use saved server plans
- Date: 2026-11-14   Track: all   Status: verified locally; activation pending
- Finding: Opt-in recipe tools persist immutable recipe versions and buyer/agent plan revisions. All original ingredients survive scaling and product matching. Unknown quantity/form/conversion and non-linear scaling remain unresolved and block preparation. Product suitability requires reviewed evidence tied to exact catalog facts; preparation and confirmation re-read evidence. The importer is explicit and resumable, with atomic corpus activation; schema migration does not import data.
- Evidence: `tests/test_recipes.py` covers authored 200-portion pasta (20 kg -> seven 3 kg packs) and egg (100 eggs -> four verified 30-egg trays) quantities, excess approval, completeness, stale/revoked evidence, provider fallback, restart and authenticated mock confirmation. Full backend: 231 passed; two focused browser flows, lint/build, 28 infra helper tests and eight mocked Terraform plans passed. UniTools v2.0.0 snapshot SHA and attribution are recorded in `docs/recipes.md`; 501 recipes / 5,404 ingredients imported into an isolated `_test` database using fixture embeddings and an unchanged rerun reused all vectors.
- Impact: Merge/apply the migration pipeline and additive recipe schema, run the explicit import with reviewed forms/quantities/product evidence, then enable the worker flag through an authorized rollout. The Qwen provider from merged PR #34 is reused; no new worker service is needed. Customer recipe editing, AI recipe generation, pantry exemptions and staged operator activation remain outside this initial core. Public recipe data alone cannot yet produce a complete executable catalog basket. No live rollout/import or paid provider verification was performed here.


### F-RECIPE-002: Review fixes make preparation atomic and recipe tools additive
- Date: 2026-11-14   Track: all   Status: verified locally; activation pending
- Finding: Recipe validation runs in short workflow transactions before and after supplier I/O. Proposal, retry key and plan lock commit together. One plan cannot create two proposals under concurrent/different-turn requests; an identical key returns the existing proposal. Direct product purchases work with recipe tools enabled. Prepared plans remain readable without replacing the prepared result. Named prompt sections replace text slicing, embedding dimensions use the shared provider helper, and matching no longer scans proposal JSONB.
- Evidence: `tests/test_recipes.py` exercises pools of one/two connections, NOWAIT plan-lock availability while both callers are at supplier I/O, same-plan races, retries, concurrent edits, transaction rollback and additive direct purchases. `tests/test_agent.py` covers ordinary requests with the flag on/off and reworded prompt sections. The focused browser test checks missing quantities without units and zero excess suppression. On merged develop with PR #36: 245 backend tests, Ruff, frontend build, two browser flows, 37 infrastructure helper tests, Terraform validation and 11 mocked Kubernetes plans passed.
- Impact: Resolves all nine PR #38 review points without enabling the flag, importing production data, merging or deploying. The merged migration runner/grant workflow is preserved; recipe ingestion and activation remain explicit operator steps.


### F-RECIPE-003: Closed recipe baskets refresh in place; free-form coverage is explicit
- Date: 2026-11-14   Track: all   Status: rejection/denial refresh superseded by F-RECIPE-004; other behavior verified locally; activation pending
- Finding: A plan now has one linked proposal. An expired, rejected, denied or unresolved unordered basket can refresh into a new revision of that proposal without repeating recipe scaling or matching; active/completed baskets remain locked. Retry keys remain scoped/idempotent, concurrent refreshes fence the previous proposal revision, and old approvals/confirmations cannot authorize the new revision. Migration 006 backfills the unique link and fails on ambiguous legacy history; 007 permits multiple preparation keys for one proposal while preserving the buyer/agent/key primary key.
- Evidence: Tests exercise all four closed states, immutable revisions, new pending approval, restart/retry, same-plan refresh races (including still-denied results), stale commits, completed-order protection and migration rollback/backfill. After current develop's expanded test/CI merge: 462 backend tests, 10 strict API sweep checks, four focused browser checks, Ruff and frontend build passed; combined Python line/branch coverage is 95.21% against the 95% gate.
- Impact: Server-derived `recipe_basis` labels proposals as `saved_recipe` or `free_form`; chat and purchase review show the distinction. A new-turn free-form plan can still name the same dish as an earlier unresolved recipe: the server does not infer that identity, so saved-recipe completeness/conversion guarantees do not apply. Catalog/pack/policy/commercial checks and exact customer confirmation still apply. This limitation is documented and covered by a regression test; it is not claimed to be prevented. Feature activation, production imports and deployment remain pending.


### F-RECIPE-004: Rejection is final, feature labels are gated, and revised terms sort first
- Date: 2026-11-14   Track: all   Status: denial finality superseded by F-RECIPE-006; other behavior verified locally; activation pending
- Finding: Rejected approvals and denied recipe proposals cannot be refreshed under their existing plan, even after expiry or policy changes. A new purchase requires a new saved plan. Recoverable expiry/resolution/policy/authority states retain in-place refresh. Session responses expose the current recipe flag; chat and purchase labels appear only when enabled. Migration 008 backfills an indexed latest-revision timestamp from audit events; refreshed terms move up Purchases without changing original creation time.
- Evidence: Regression tests exercise final rejection/denial before and after TTL, no supplier calls or extra revisions, new plan creation, refresh sorting/pagination, migration timestamp backfill/rerun and API/browser flag states. All 467 backend tests, 10 strict API sweep checks, six focused browser checks, Ruff and frontend types/build passed; combined coverage is 95.21% (95% gate).
- Impact: Supersedes the rejected/denied recovery policy in F-RECIPE-003. The owner cannot confirm whether 005 has run on a shared database; preserve 005 and additive 006 to avoid leaving an already-migrated database without its proposal link. No shared database was inspected or changed; flag activation, merge, imports and rollout remain pending.


### F-RECIPE-005: Migration allocations preserve applied filenames
- Date: 2026-11-14   Track: all   Status: verified locally; activation pending
- Finding: All fetched remote branch tips and all five open PR heads were checked: the highest migration was PR #38's 008, and no other branch used 009–011. Reserve 008–010 for Person 3 and move recipe revision ordering to 011. Its compatibility guard preserves timestamps/indexes if the earlier 008 already ran; existing ledger entries remain intact. Keep both 005 filenames because shared application is unknown; full filenames are distinct ledger keys.
- Evidence: `tests/test_migrations.py` covers actual packaged-schema upgrades from populated hosted-search and recipe-005 checkpoints, immutable purchase/order/approval history, repeat runs, the old 008 transition, later-arriving lower-numbered files and duplicate numeric prefixes. All 470 backend tests and 10 API sweep checks pass with 95.21% combined coverage; 35 migration/CLI checks also pass from a fresh isolated database. Allocation and operator guidance are in `migrations/README.md`.
- Impact: Supersedes the ordering migration number in F-RECIPE-004. Person 3 can use 008–010 with distinct descriptive filenames; no shared database changes or ledger edits are required by this renumbering. Future allocations must check open work as well as develop.


### F-RECIPE-006: Correctable denials retain matched recipe ingredients
- Date: 2026-11-14   Track: all   Status: verified locally; activation pending
- Finding: Only an approver rejection is final for a saved recipe plan. Denied requests can refresh in place with corrected dates, destinations, budget or buyer policy; each new revision runs all recipe, product/evidence and purchasing checks again. An unchanged denial remains uncommittable. Current denied saved-recipe proposals return `revise_request`; ordinary current denials retain `stop`. Shared rendering again recommends fresh preparation for expired/policy-changed denied ordinary proposals, while rejection remains final even after expiry.
- Evidence: Recipe regressions cover all four corrections, preserved plan/matches/proposal ID, new approvals, stale confirmations and repeated denials with blocked commits. Ordinary-order regressions cover expiry and policy-change guidance and a fresh eligible purchase. Existing rejection and concurrency regressions remain; a direct rejected proposal still renders `rejected` and `stop` after expiry. All 475 backend tests, 10 strict API sweep checks and Ruff pass; combined coverage is 95.22% against the 95% gate.
- Impact: Supersedes F-RECIPE-004's overly broad denial finality. Migration allocation is unchanged: 008–010 remain reserved for Person 3; ordering remains 011. Shared-interface teammate review remains requested on PR #38. No shared database, deployment or feature activation is changed.


### F-RECIPE-007: Demo cluster recipe corpus imported with the hosted Qwen profile
- Date: 2026-11-14   Track: all   Status: verified on the demo cluster
- Finding: The release from `main` at `e90b2d8` applied 005_recipe_planning, 006, 007 and 011 with runtime grants; earlier ledger rows were skipped, and no 008 ledger row existed. The UniTools World Recipes v2.0.0 snapshot (`unitools-recipes-v1.json`, SHA-256 `41fdc0572b7272ca557d2df22a0fac1cc1f18146e97ebd2c8258c395daf87d8a`) was imported by a one-off Job cloned from the `aimo-worker` pod spec (same image, secrets and runtime role) with `aimo ingest-recipes`. Active corpus `09a412b6-bbcc-4299-9e8e-7b347d5c005e` uses `openrouter:qwen/qwen3-embedding-8b:4096:catalog-v2-query-v1:recipes-v1`.
- Evidence: 501 recipes/versions, 5,404 ingredients, 501 corpus entries with 501 vectors of 4,096 dimensions; attribution `UniTools — theunitools.com`, license CC BY-SA 4.0, source version 2.0.0 on every version. A repeat unchanged import embedded 0 and reused 501 with the same corpus. Hybrid search with reranking applied ranked Spaghetti carbonara first for "carbonara"; `get_recipe` returned its ingredients and attribution. Worker and API runtime credentials read the corpus and resolve the same model key. Temporary control-plane access was closed afterwards.
- Impact: Recipe discovery is ready. Recipe-to-catalog purchasing is not: no review file was supplied, so all 5,404 ingredient forms remain `unspecified`, and there are no product-evidence rows.


### F-RECIPE-008: Recipe tools are always on
- Date: 2026-11-14   Track: all   Status: verified locally
- Finding: Recipes are a standard app feature, so `RECIPE_PLANNING_ENABLED` (settings, Compose, `.env.example`, Terraform variable/ConfigMap and the session response field) is removed. The agent always registers the recipe tools and uses the recipe prompt; chat and purchase review always show saved-recipe versus free-form labels. Without an import or with a different embedding profile, the tools still report `RECIPES_NOT_READY` or `RECIPE_MODEL_MISMATCH`.
- Evidence: Ruff, 548 backend tests, all 10 API sweep checks, frontend types/build, Terraform validate/fmt and the three recipe browser checks pass. One backend test (`test_another_authorized_customer_can_resume_after_original_authority_revoked`) and one browser test (unfinished server turns) fail identically on unmodified develop locally; CI on develop passes the backend test.
- Impact: Supersedes the feature-flag gating in F-RECIPE-002 and F-RECIPE-004. Purchasing through a recipe still requires reviewed forms/quantities and product evidence.


### F-CATALOG-SYNC-001: Product-catalog ingestion runs as an independent scheduled Job
- Date: 2026-11-14   Track: all   Status: verified locally; not applied or deployed
- Finding: `aimo sync-catalog` downloads (bounded timeouts, size, deadline and retries; key never forwarded to redirects; HTTPS only) or reads the approved snapshot. It verifies the pinned SHA-256/count and skips when the active generation's hash, embedding model/dimensions, recorded import profile (migration 012) and stored row count all match. Otherwise it imports through the existing strict path and activates atomically. A PostgreSQL session advisory lock (893019, no open transaction while downloading or embedding) coordinates scheduled runs, manual Jobs and `aimo ingest`. Publication re-verifies the lock. A Terraform `aimo-catalog-sync` CronJob (daily 03:30 Europe/Helsinki, Forbid, bounded retries/deadline/history, explicit CPU/memory/ephemeral-storage, non-root, read-only root) runs it from the worker image with its own Secret and a dedicated `aimo_catalog_sync` database role limited to the four catalog tables. Bootstrap no longer imports; the first population is a manual run of the same Job template. The "stop the apps to import" rule was a capacity limit, not a correctness limit.
- Evidence: `tests/ci.sh` with coverage, against isolated local databases: Ruff, 591 backend tests (including 41 in `tests/test_catalog_sync.py`), 10/10 strict API sweep checks, 95.82% combined coverage (gate 95%). Terraform fmt/validate on both stacks, 20 Kubernetes and 3 DigitalOcean mock-plan tests, and 42 infra unit tests pass. A local measurement used the pinned E5 model on a synthetic 111 MB, 17,546-record snapshot from a local file (Apple-silicon Mac): unchanged run 0.6 s / 130 MiB peak RSS; cached rebuild 4.6 s / 757 MiB; cold import 105 s / 1.79 GiB. No Kubernetes execution, live download, Terraform apply or deployment was performed.
- Impact: Requires teammate review (schema column, shared cloud/Kubernetes interfaces, new database role). Operator steps remain: DigitalOcean user/outputs, private inputs, release migration grants, `catalog_sync.enabled`, and the first Job. The first run after migration 012 rebuilds once (legacy generations have no recorded profile), reusing cached embeddings. Cold full imports on the single 4 GB node alongside serving are unverified; see `docs/catalog-sync.md`. Changed supplier snapshots still require explicit approval.

### F-CATALOG-SYNC-002: The download deadline cancels header and body reads
- Date: 2026-11-14   Track: all   Status: verified locally
- Finding: HTTPX idle read timeouts reset on each network read, so checking elapsed time only after headers or body chunks arrive cannot bound an attempt. The downloader now uses an async HTTP client under one cancellable timeout per attempt, including redirects and response headers. Cancellation closes the connection and removes partial files before a retry.
- Evidence: Loopback header trickling exceeded a 0.2-second deadline at commit `487b1e6` (1.05 seconds); the corrected attempt finished in 0.202 seconds with no residual files. Real-transport regressions cover headers, redirected headers and body trickles; mocked cancellation regressions verify cleanup before successful retry. After integrating PR #105 from develop, `tests/ci.sh` with coverage passed Ruff, 622 backend tests and all 11 fixture API sweep checks against isolated local databases.
- Impact: A supplier that continuously trickles headers cannot keep a download attempt holding the ingestion lock beyond its deadline. No live supplier request, cluster change or deployment was performed.
### F-MEMORY-001: Explicit buyer and personal memory without purchasing authority
- Date: 2026-11-14   Track: all   Status: verified locally with fixtures; not deployed
- Finding: The assistant now keeps explicitly saved buyer-shared and personal (per identity) defaults, preferences and instructions across conversations (`docs/memory.md`). Additive migration 012 adds `memories` (typed keys, composite same-buyer foreign keys, one key per owner) and `memory_mutations` (durable idempotency; content hashes are cleared on forget). The worker now passes the persisted turn's `requested_by` human, attempt and conversation as trusted server context; purchasing tools keep the internal agent identity. Two tools, `search_memory` and `manage_memory`, and `/api/memories` share one service. Writes recheck the active approver under the buyer lock, share-lock the turn so superseded attempts cannot write, and need expected revisions. Up to 20 items / 6,000 characters load automatically below the system rules. Under `GUARDRAIL_MODE=enforce` each write passes a new Jev `memory_write` check (policy `guard-2026-11-14.3`); with guardrails off, intent rests on the binding plus model instructions, which is not complete enforcement.
- Evidence: 20 new tests in `tests/test_memory.py`, `tests/test_memory_http.py` and the restricted-role grant test, plus a populated-database upgrade test for 012 and a new sweep check. After merging develop at `837dfdf` (recipes always on), on private local databases on 2026-11-14: `tests/ci.sh` with `CI_COVERAGE=1` passed Ruff, 569 pytest cases and 11 API sweep checks; the combined coverage gate reported 95.96% (fail_under 95%). Generated OpenAPI/TypeScript and the frontend production build passed. Provider and classifier were scripted fakes; no live model, supplier or deployment was used.
- Impact: Conversations are shared within a buyer, so personal memory is private from other users' loading and APIs but not from conversation history; the server notice names the key only. Saved defaults do not satisfy the preparation guardrail's "customer stated" checks, so the assistant must confirm a saved destination in chat under enforcement. No frontend settings page or undo UI is included. Migration 012 needs the usual operator migration step; no Terraform, release switch or deployment was changed.

### F-MEMORY-002: Retried turns preserve authorship and replay forgotten items
- Date: 2026-11-14   Track: all   Status: verified locally with fixtures; not deployed
- Finding: Migration 012 records an immutable `submitted_by` author separately from the latest `requested_by` executor. A colleague can still retry purchasing, but that attempt cannot load or manage memory. Legacy turns keep an unknown author and also run without memory. Chat tools resolve durable mutation replays before requiring a live memory row or repeating the semantic write check; deleted items stay deleted, with a distinct "Already forgotten" notice for earlier saves/updates. Active-user, author and worker-attempt checks still apply to replays.
- Evidence: Completed the interrupted review fixes and added regressions for colleague retries before/after a durable write, original-author retries, legacy turns, replayed delete/save/update after forgetting, superseded attempts and populated-database migration. On private local databases: Ruff passed; all 573 pytest cases passed; the API sweep passed 11/11 checks; combined coverage was 96.00% against the 95% gate. Providers and classifiers remained scripted fakes.
- Impact: Fixes both PR #105 review findings. No shared database, live model, supplier, merge or deployment was used.

## Frontend styling

### F-FE-001: Production app supports gradual Tailwind migration
- Date: 2026-11-14   Track: all   Status: verified (local UI fixtures)
- Finding: The production `frontend/` package now loads PR #107's theme and fonts. Its existing stylesheet is in the components layer, below Tailwind utilities, without enabling preflight. The prototype stays separate.
- Evidence: `npm run build --prefix frontend` and all seven `e2e/chat.spec.ts` regressions passed against local Vite. Chromium inspection of Login at 1440px and 390px showed no horizontal overflow; an injected utility-layer rule overrode the legacy button background and padding. Browser regressions use intercepted API fixtures, not a live backend.
- Impact: Screen migration can reuse the existing authenticated API behavior. `frontend/README.md` records the implementation order and the outstanding need to reconcile integration ownership with #59 before landing. No backend, merge or deployment was performed.

### F-FE-002: Production frontend is organized by feature
- Date: 2026-11-14   Track: all   Status: verified (local UI fixtures)
- Finding: `frontend/src/main.tsx` now only mounts React. App composition, auth/chat/purchases pages, props-driven components, behavior hooks and typed endpoint modules are separated; shared transport/schema/formatting and layered styles have explicit homes. Frontend agent, architecture, development and testing guides describe the boundaries. The task branch was rebased onto current develop, retaining its recipe evidence and interrupted-turn recovery UI in the extracted components.
- Evidence: Fresh `npm ci`, `npm run check` (lint, formatting, strict TypeScript and build), schema regeneration, and `npm test` pass locally. Eleven browser regressions pass; two live backend/database specs skip by default. The recovered-request regression now asserts the existing Retry request action, and a new SSE regression checks persisted-key recovery after an interrupted snapshot. Playwright starts/stops Vite automatically. The relocated generated schema matches current develop byte for byte. `npm audit` reports no vulnerabilities after a scoped lint-tool glob dependency override.
- Impact: Agents can work within feature folders without editing a monolithic entry point. CI's existing frontend step runs lint, TypeScript and build; formatting and browser checks remain local per repository policy. No authentication/purchasing authority, backend behavior, deployed infrastructure or release switch was changed by the refactor.

### F-CI-001: Hackathon CI keeps functional checks without a coverage gate
- Date: 2026-11-14   Track: maintenance   Status: verified locally; hosted checks pending
- Finding: At the owner's request, remove the 95% coverage threshold, coverage collection/artifact jobs and application-existence scaffolding. Backend lint, pytest and the strict API sweep share one Python environment and PostgreSQL service; frontend types/build runs independently. Keep scoped Terraform checks and the release gate. Preserve required status names, including `Detect application components`, which now only detects infrastructure changes.
- Evidence: `actionlint`, `git diff --check` and `uv lock --check` pass. The gate script was executed against all 1,024 combinations of required-job results, Terraform result and valid/missing/invalid change flags; only all-success required checks with the expected Terraform result pass. Workflow structure checks confirm independent backend/frontend jobs, a required API sweep and the release dependency on the gate. Full functional checks will run on the task PR.
- Impact: Coverage remains an optional local report, without a minimum percentage. No tests were deleted, and no branch rules, shared database, deployment or release switch were changed. Work is isolated from the original checkout's pending edits/conflicts.

## Catalog and supplier evidence (person 3)

### F-CAT-001: A product missing from a newer snapshot used to vanish
- Date: 2026-11-14   Track: 3   Status: verified (fixed by DIS-008)
- Finding: `ingest_file` published only the products of the new snapshot, so a product the supplier dropped disappeared: `get_product` returned `NOT_FOUND` and `prepare_order` reported `PRODUCT_UNKNOWN`, not a withdrawal. Only products the source flagged `deleted: true` were kept as withdrawn. The real snapshot (17,546 products) has none flagged. Now `ingest_file` carries absent products into the new generation with `deleted: true` and the first withdrawal date (`products.withdrawn_since`, migration `009_product_withdrawn_since.sql`).
- Evidence: `tests/test_withdrawn_absent.py` (7 passed; red first, all failed with NOT_FOUND / PRODUCT_UNKNOWN), `src/aimo/ingest.py` `_absent_as_withdrawn`.
- Impact: Exact lookup of a dropped product returns it as withdrawn; purchases are denied with `PRODUCT_DELETED`. `ingest_file(..., carry_withdrawn=False)` opts out (also turns off the DIS-012 trim); existing exact-count ingest tests use it.

### F-CAT-002: Rerunning an unchanged ingest could discard the only different rollback catalog
- Date: 2026-11-14   Track: 3   Status: verified (fixed by Option B)
- Finding: With `CATALOG_GENERATIONS_TO_KEEP=2`, each ingest keeps the new generation and the previous one. Rerunning an unchanged snapshot made the previous (identical) generation the retained rollback target and pruned the last different catalog; `aimo activate-catalog` on it then failed with "has been pruned". `_activate` now skips older generations with the same `source_hash` and `model_key`.
- Evidence: `tests/test_ingest_rerun.py::test_rerunning_the_same_snapshot_keeps_the_last_different_catalog_for_rollback` (was a strict xfail failing with the ValueError at `ingest.py`, now passes).
- Impact: An operator can rerun an ingest without losing the rollback. If no different generation exists, nothing is kept for rollback (an identical copy is no rollback).

### F-CAT-003: A supplier product name can block a quantity (status of SUP-003)
- Date: 2026-11-14   Track: 3   Status: verified (read); owner pinned it, not changed
- Finding: `catalog.normalize` extracts a volume hint from the product name and can set `measures.L.status` to `conflicting`, which makes `quantity()` return no sales quantity and the line `QUANTITY_UNRESOLVED`. The hint can only block, never permit, a purchase. Owner Q-29 keeps SUP-003 pinned: do not touch the name hint.
- Evidence: `src/aimo/catalog.py` `normalize` (name hint) and `quantity`; `tests/test_catalog.py::test_name_with_a_different_size_marks_volume_conflicting_but_never_creates_it`.
- Impact: Supplier text reaches policy only as a blocking status; supplier descriptions and marketing text are embedded for discovery only.

### F-CAT-004: Supplier mode default is `auto`; deployment must be live and fail without a key (owner Q-01)
- Date: 2026-11-14   Track: 3   Status: verified; open for person 1
- Finding: On develop `config.py` defaults `upstream_mode` to `auto` (live when `VALIO_AIMO_API_KEY` is set, else a labelled fixture client with a warning). Owner answer: auto locally; a deployment must have a key and fail without one; infra defaults live. Still true on this branch: `infra/kubernetes/variables.tf` defaults to an explicit `fixture`, and a hosted deployment (marker `SECURE_COOKIES=true`, an assumption) without a key does not fail at startup. `mode` is recorded on every lookup result, in the stored proposal snapshot and line evidence and in the receipt `evidence_mode`.
- Evidence: `tests/test_upstream_default.py` (strict xfails for the infra default and hosted startup), `tests/test_supplier_mode.py` (5 passed).
- Impact: Person 1 changes the infra default and adds a startup check; remove the two xfail markers in the same PR.

### F-CAT-005: Catalog records are validated one by one
- Date: 2026-11-14   Track: 3   Status: verified
- Finding: `ingest_file` now rejects a malformed record with a `ValueError` naming its index and id (missing field, wrong type, non-numeric value, `allowedLotSize` not a finite number of at least 0, non-finite unit size) before anything is published; before, a bad record raised `KeyError` or stored an unusable number. The real snapshot (SHA matches the pinned hash) has 0 rejected records of 17,546.
- Evidence: `tests/test_ingest_malformed.py` (19 passed; red first 18 failed); counts-only script over the private snapshot.
- Impact: A stricter check cannot silently reject the real data; a new snapshot with defects is refused with a precise message.

### F-CAT-006: Removing a product breaks no stored history, except one crash in recipes
- Date: 2026-11-14   Track: 3   Status: verified
- Finding: Nothing references `products` by foreign key; proposals, orders, receipts and recipe plans hold self-contained jsonb. After a product is removed from the active catalog `get_order`, `get_proposal` and replaying a commit key still work. A pending saved-recipe proposal whose product is absent crashes at commit with an unhandled `KeyError` (`src/aimo/recipes.py:384`, `products[pid]`, ISS-JCT-002, person 2's file); a product flagged withdrawn gives a clean `RECIPE_PRODUCT_EVIDENCE_CHANGED`.
- Evidence: throwaway runs `evidence/ws-a/scratch-product-removal-check.py` and `scratch-recipe-removal-check.py`; `evidence/ws-a/04-withdrawn-removal-impact.md`.
- Impact: DIS-011 and DIS-012 protect products named by a pending or refreshable proposal; keeping absent products as withdrawn (F-CAT-001) avoids the crash for those ids.

### F-CAT-007: Supplier lookups are batched within 1,000 ids; the batch size is not yet a setting
- Date: 2026-11-14   Track: 3   Status: verified; setting open for person 1
- Finding: The supplier accepts 1 to 1,000 product ids per price or availability request; rate limits are undisclosed. `ValioClient.lookup` sends batches of at most min(batch size, 1000) ids, sequentially, price first then availability, and refuses to merge batches that disagree on customer, currency or date. The size is read from `supplier_lookup_batch_size` if `Settings` has it, else a module default of 100 (matches `build_snapshot`'s separate 100-material cap).
- Evidence: `tests/test_lookup_batching.py`, `tests/test_lookup_units.py` (23 passed, 6 strict xfails waiting for the setting); request `evidence/ws-a/05-request-to-person-1-sup-007-batch-setting.md`.
- Impact: Person 1 adds `supplier_lookup_batch_size: int = Field(default=100, ge=1, le=1000)`.

### F-CAT-008: A lookup delivery date of 0001-01-01 crashed the supplier path
- Date: 2026-11-14   Track: 3   Status: verified (engineering guard, not an owner rule)
- Finding: `0001-01-01` is valid ISO but was reported to the agent as `TOOL_RESULT_INVALID` "Retry later". `LookupRequest.delivery_date` now must be between 2000-01-01 and 2100-12-31 (fixed window, not today-relative, because fixtures use fixed dates), and the error names the field and the limit.
- Evidence: `tests/test_lookup_delivery_date.py` (8 tests), `tests/test_tool_surface.py::test_tct003_out_of_range_delivery_date_is_not_reported_as_retry_later` (strict xfail removed).
- Impact: The tool layer still shows one fixed `INVALID_TOOL_ARGUMENTS` text; naming the field there is person 2's gap (issue #96).

### F-CAT-009: Real-data shape for the new search filters and substitutions
- Date: 2026-11-14   Track: 3   Status: verified
- Finding: In the 17,546-product snapshot 17,537 products have a two-letter lowercase `countryOfOrigin` and 9 have none; 40 distinct `free_from` codes exist, one containing a digit (`X99`), so allergen codes are validated as 1 to 4 letters or digits; 189 products carry `substitutions` (as F-DATA-004); no product is flagged `deleted`.
- Evidence: counts-only script over the private snapshot (`python -I`, output counts only), 2026-11-14.
- Impact: `Requirements.free_from` accepts `^[A-Za-z][A-Za-z0-9]{0,3}$`; `country_of_origin` accepts two-letter codes; products with no country are excluded when a country is requested.

### F-CAT-010: Shared test database contention (suspected)
- Date: 2026-11-14   Track: 3   Status: unverified
- Finding: One of three agents saw 62 failures, mostly in `tests/test_tool_surface.py`, in a first full run that could not be reproduced in two reruns. Suspected cause: two pytest processes sharing one test database name (the conftest truncates tables); the coordinator also found the shared Postgres on port 55432 saturated by checkpoint waits when databases are created or dropped.
- Evidence: not reproduced; suite runs with a private database name were clean (955 and 964 passed).
- Impact: Give each parallel run its own database name, never run two full suites on one name, use the tuned container on port 55433 for person 3.

## Meal and basket arithmetic (person 3, WS-B)

### F-BASKET-001: Deposit pricing divided Decimals and mispriced non-terminating ratios
- Date: 2026-11-14   Track: 3   Status: verified (fixed on p3/ws-b, commit 52f4435)
- Finding: build_snapshot priced a deposit as units * source_factor / sales_factor in Decimal (28 digits). One third of a unit at 0.165 EUR came out 0.05 instead of the exact half-up 0.06. The shipped fixtures use ratio 1 (12 per box), so the demo was unaffected; real data with such ratios is unverified (data/ not read). Pricing now uses Fraction with one half-up rounding to cents; the stored text of priced_sales_quantity is unchanged for exact quantities, so fingerprints of earlier proposals stay valid.
- Evidence: tests/test_basket_contract.py::test_deposit_charge_for_a_third_of_a_unit_equals_the_exact_rational_result (failed before the fix), ::test_exact_deposit_lines_are_identical_to_the_legacy_decimal_calculation, ::test_same_prepare_key_returns_the_stored_proposal_without_pricing_again; BAS-005-final.txt.
- Impact: Money for exact ratios is byte-identical; only previously inexact ratios change. A retry with the same prepare key is resolved from the saved revision and never reprices.

### F-BASKET-002: An unpriced deposit left the line showing the price without it
- Date: 2026-11-14   Track: 3   Status: verified (fixed, commit ef0422d)
- Finding: With a deposit that had no price the proposal total was withheld, but the line still showed gross 17.00 and deposits_gross 0.00 (the price without the deposit, and a deposit of zero). Now the line net, gross, tax and deposits_gross are None, the totals stay withheld and DEPOSIT_UNRESOLVED still blocks. The frontend already renders a null amount as "Unresolved" (frontend/src/main.tsx:59-65).
- Evidence: tests/test_draft_contract.py::test_line_gross_and_deposits_are_unknown_when_the_deposit_has_no_price; PRP-006-final.txt.
- Impact: Only blocked (needs_resolution) proposals change; no order or confirmation is affected.

### F-BASKET-003: Recipe scaling refuses anything that needs more than four decimals
- Date: 2026-11-14   Track: 3   Status: verified (probe and test); round-up patch pending
- Finding: recipes.scaled_plan scales exactly with Fraction but returns amount None when the exact result has more than four decimals (Amount is a 4-decimal string). At base 6 servings and 200 portions, 200 g, 100 g and 500 g become unresolved while 150 g gives 5 KG; roughly two thirds of gram quantities are lost whenever the portion count does not divide evenly. Owner decision MEA-012: round scaled quantities UP to four decimals. The patch is in person 2's recipes.py (MEA-012-013-requests.md), verified on a scratch copy.
- Evidence: tests/test_draft_contract.py::test_scaled_quantity_is_rounded_up_to_four_decimals (strict xfail), tests/test_recipe_arithmetic.py (nonterminating cases); a throwaway probe of scaled_plan (outputs in the audit file section "Merged develop 17579d8").
- Impact: Until the patch lands a carbonara for a non-dividing portion count has unresolved ingredients that cannot be matched.
- Update 2026-11-14 (branch `p3/otto-fixes`, not merged): fixed. `scaled_plan` rounds up to four decimals (MEA-012); verified by `tests/test_draft_contract.py::test_scaled_quantity_is_rounded_up_to_four_decimals`.

### F-BASKET-004: No upper bound on scaled quantity per portion
- Date: 2026-11-14   Track: 3   Status: verified
- Finding: scaled_plan accepts 9,999,999 kg per serving at 10,000 portions (99,999,990,000 KG). Only Amount (14 digits) and portions (1..10000) limit it. MEA-011 (maximum per portion) is deferred and belongs to person 2 (owner decision); the guardrails added in #56 are an optional model-judged check, off by default, not a numeric bound.
- Evidence: tests/test_draft_contract.py::test_absurd_quantity_per_portion_is_rejected (strict xfail).
- Impact: A wrong recipe quantity reaches the product match unchecked; the budget limit catches price, not quantity.
- Update 2026-11-14 (branch `p3/otto-fixes`, not merged): fixed with sanity bounds of 5 KG, 5 L and 50 pieces per portion (`recipes.MAX_QUANTITY_PER_PORTION`, `QUANTITY_PER_PORTION_EXCEEDED`); these numbers are my proposal for the owner to retune, and they apply to recipe-scaled plans only. Verified by `tests/test_draft_contract.py` (limit allowed, above limit refused, per-portion not total).

### F-BASKET-005: Variable-weight products block in two places (known gap, owner: warn only)
- Date: 2026-11-14   Track: 3   Status: verified
- Finding: purchases.py:117-119 adds VARIABLE_WEIGHT_UNRESOLVED (severity unresolved, so needs_resolution) and recipes.py:272 leaves the ingredient unresolved. A missing variableUnit counts as variable weight (catalog.py:80). By F-DATA numbers about 21% of the catalog (632 true plus 3,068 without the field, of 17,546) cannot be committed. Owner decided BAS-007 is warn only; implementation deferred (ISS-JCT-001). A non-blocking warning also needs a severity that does not block (Reason.severity allows denied, unresolved, exception only).
- Evidence: tests/test_arithmetic_contract.py::test_variable_weight_line_is_flagged_but_does_not_block (strict xfail), BAS-007.md.
- Impact: The demo avoids variable-weight products; real orders with them are blocked.
- Update 2026-11-14 (branch `p3/otto-fixes`, not merged): fixed. VARIABLE_WEIGHT_UNRESOLVED now has the non-blocking severity `warning`, and `match_ingredient` / `match_ingredients` no longer leave a variable-weight product unresolved. Status: fixed on the branch, verified by `tests/test_arithmetic_contract.py::test_variable_weight_line_is_flagged_but_does_not_block` and `tests/test_recipes.py::test_variable_weight_products_can_be_matched_and_only_warn`.

### F-BASKET-006: One product in two units could never be prepared
- Date: 2026-11-14   Track: 3   Status: verified
- Finding: A plan that needs the same product in two units (for example KG and piece) has two basket keys (product_id, unit) while PurchaseRequest allows one line per product, so every prepare ended in MEAL_BASKET_MISMATCH. Owner decisions: BAS-009 unit priority KG, then L, then pieces; the agent must always request with the plan's units (Q-44), and the refusal must say exactly what to send. Backend built: catalog.combine_in_priority_unit (exact, never rounded) and basket_errors (structured details). The call sites in agent_tools.py and recipes.py are person 2's (patch text in BAS-009-requests.md).
- Evidence: tests/test_basket_contract.py::test_one_product_in_two_units_can_be_prepared (strict xfail), tests/test_unit_priority.py, tests/test_basket_errors.py.
- Impact: Mixed-unit recipes stay unpreparable until person 2 applies the patch.
- Update 2026-11-14 (branch `p3/otto-fixes`, not merged): fixed in `agent_tools.py` / `recipes.py` (`combine_by_product`); verified by `tests/test_basket_contract.py::test_one_product_in_two_units_can_be_prepared` and `tests/test_draft_contract.py::test_product_requested_in_two_units_becomes_one_line_in_the_priority_unit`.

### F-BASKET-007: Per-ingredient conversion is computed alone, so shared packs overstate
- Date: 2026-11-14   Track: 3   Status: verified
- Finding: recipes.match_ingredient converts each ingredient on its own: two ingredients on one product showed 7 + 4 = 11 packs (33 KG) while the basket bought 10 packs (30 KG). purchase_amount is a copy of amount, not the rounded purchase (recipes.py:296). Owner decisions (Q-45): each snapshot line names its ingredients and per-ingredient purchased amounts add up to the line. Built: SnapshotLine.contributions with exact shares (basket.allocate_line); a non-terminating share is written as numerator/denominator, never rounded.
- Evidence: tests/test_contributions_contract.py, tests/test_recipe_arithmetic.py::test_ingredient_purchased_amounts_add_up_to_the_basket_line; MEA-005-009-red-check.txt (the tests fail without the change).
- Impact: The proposal shows consistent per-ingredient amounts; the saved plan still shows stand-alone estimates until person 2 changes match_ingredient.

### F-BASKET-008: Supplier lookups allow 1000 products, our client does not batch
- Date: 2026-11-14   Track: 3   Status: verified (spec and code read)
- Finding: /api/price and /api/availability accept 1..1000 product codes per request (docs/reference/aimo-api.openapi.json). ValioClient.lookup sends all ids in one POST per endpoint (class name is ValioClient, not HttpClient). Our caps were 30 lines, 50 lookup ids and 100 materials; they are now 1000 (MEA-013, schemas.py MAX_BASKET_LINES, MAX_LOOKUP_IDS, purchases.py MAX_MATERIALS), equal to the supplier limit so no batching is needed yet. SUP-007 (batching) is WS-A's.
- Evidence: tests/test_draft_contract.py MEA-013 and SUP-007 tests; MEA-012-013-requests.md (cap table).
- Impact: MealPlan (30), Recipe (100) and scaled_plan (30) are still capped in persons 1 and 2's files.

### F-BASKET-009: The agent loop, not the schemas, limits ingredients per turn
- Date: 2026-11-14   Track: 3   Status: unverified (read from code, not run)
- Finding: llm_max_tool_rounds is at most 24 (config.py:43) and a reply carries at most 12 tool calls (agent_provider.py:32), so about 240 to 288 single match_ingredient calls fit in a turn; four cumulative tool errors stop the turn (agent.py:262). With guardrails on, MAX_STATE_BYTES = 28,000 (guardrails.py:37) rejects larger states. MEA-014 (batch matching, Service.match_ingredients) removes the per-ingredient call; the agent tool is person 2's.
- Evidence: source lines above; owner question Q-39.
- Impact: 1000 ingredients cannot be matched in one turn until the batch tool exists.

### F-BASKET-010: A free-form basket can repeat a dish whose saved plan is unresolved
- Date: 2026-11-14   Track: 3   Status: verified (backend built; call site pending)
- Finding: docs/recipes.md acknowledges that a later free-form plan naming the same dish is prepared and only labelled free_form. Owner decision Q-45: refuse it. Built: recipe_guard.ensure_no_unresolved_saved_plan (RECIPE_PLAN_UNRESOLVED) matching the title (NFKC, whitespace, case folded) within the buyer's own unlocked, unprepared plans of the same conversation, else the last 24 hours; Service.ensure_saved_plan_resolved. The call in ToolSession.prepare is person 2's (MEA-008-requests.md). A different title for the same dish still passes.
- Evidence: tests/test_recipe_guard.py (11 tests); the agent-layer strict xfail in tests/test_recipe_arithmetic.py.
- Impact: The hole is closed only when the agent_tools patch lands.

### F-BASKET-011: Test environment traps
- Date: 2026-11-14   Track: 3   Status: verified
- Finding: uv is not installed on the development machine (tests/test_sweep.py runs tests/ci.sh and fails with "uv: command not found"; the rest of the suite runs with another checkout's venv and PYTHONPATH=src). The shared Postgres on port 55432 saturated under parallel suites (checkpoint waits, a DROP DATABASE waited over nine minutes); person 3 uses a tuned container on port 55433. conftest creates the database named in TEST_DATABASE_URL; the name must end in _test. A patch checked on a scratch copy of src must also copy migrations/ (ROOT is relative to the package).
- Evidence: full-suite-ws-b-final.txt (771 passed, 18 xfailed on port 55433 after merging develop 837dfdf, test_sweep.py ignored).
- Impact: CI, not the local run, is the authority for test_sweep.py.

### F-BASKET-012: Migration numbering
- Date: 2026-11-14   Track: 3   Status: verified
- Finding: develop has two migrations with prefix 005 (005_hosted_search, 005_recipe_planning); the runner orders by full filename (migrations/README.md). 008-010 are reserved for person 3 (008 is WS-D's orders_immutable); 011 is PR #38's proposal revision ordering; 012 and 013 are not reserved yet (owner has not posted the issue). PER-004 (append-only recipe plan revisions and recipe versions) is therefore a strict-xfail test plus a migration draft as text; the draft passes on a scratch database and no code updates or deletes those tables.
- Evidence: PER-004-migration-draft.md, tests/test_persistence_contract.py::test_per_004_*.
- Impact: PER-004 stays unmet until a number is reserved. TRUNCATE is not blocked by row triggers (noted in the draft).

## Policy, identity and isolation (person 3, WS-C)

### F-POLICY-001: Missing approved product list did not block a purchase when substitution was "allowed"
- Date: 2026-11-14   Track: 3   Status: verified (fixed in `p3/ws-c`)
- Finding: `evaluate_purchase` raised `PRODUCT_SCOPE_UNCONFIGURED` only when the scope was missing **and** substitution was restricted. With no scope and `substitution="allowed"` it returned `ready_to_commit` with no reasons, and an outside-scope product with that rule also passed silently. Owner decision D-008 made the block unconditional and made "allowed" a permitted exception that records `SUBSTITUTION_ALLOWED_BY_POLICY` per line. An empty list `[]` is a configured list (every product outside scope).
- Evidence: pure-function probe before the fix (scope `None` + `allowed` gave `ready_to_commit`); `tests/test_policy_rules.py` (81 passed with the evidence set) fails 9 tests against the unmodified `approval_policy.py` (`ws-c/pol-004-006-red-before-fix.txt`); mutation M6 (`ws-c/mutation-checks.txt`).
- Impact: Policy seeded with `substitution="requires_approval"` was already safe; any buyer configured with `allowed` and no list was exposed. Seed data is unchanged.

### F-POLICY-002: `evaluate_purchase` relied on its caller to report an unknown total
- Date: 2026-11-14   Track: 3   Status: verified (fixed)
- Finding: With `gross_total=None` and no snapshot reason the function returned `ready_to_commit`. It was unreachable through `build_snapshot` (which always adds `TOTAL_UNRESOLVED`) but not defended. The function now adds `TOTAL_UNRESOLVED` itself, once.
- Evidence: `tests/test_policy_rules.py::test_unknown_total_never_reaches_ready_to_commit` (was a strict xfail, now passes), mutation M7.
- Impact: POL-009 holds inside the policy function, not only by convention.

### F-POLICY-003: The agent's spend authority is removed; legacy rows are tolerated, not migrated
- Date: 2026-11-14   Track: 3   Status: verified
- Finding: Q-35 removed the autonomous limit, `AgentAuthority` and the `spend` exception. Stored `policies.rules` (immutable) still carry `autonomous_limit` and stored identities carry `autonomous_limit` / `"spend"`; every model has `extra="forbid"`, so removing the field alone would have made `context()` answer `INVALID_POLICY_CONFIGURATION` for every existing buyer. `PolicyRules` and `ApproverAuthority` have before-validators that drop the legacy key and the legacy `spend` value; agent authority is not validated at all. Other unknown keys are still rejected.
- Evidence: `tests/test_spend_authority.py` (64 tests incl. tolerance), `tests/test_provisioning.py` (13), mutation M4; `ws-c/POL-013.md`, `ws-c/IDN-002.md`.
- Impact: No data migration. Pending approvals created before the change read as `authority_changed` and are re-evaluated lazily at commit. `seed()` uses `ON CONFLICT DO NOTHING`, so existing databases keep their old rows.

### F-POLICY-004: `NO_ELIGIBLE_APPROVER` was only raised when an exception was in play
- Date: 2026-11-14   Track: 3   Status: verified (fixed, owner Q-37)
- Finding: A total above every approver's `max_gross` with no exception used to be `ready_to_commit`; the maximum only bit at `conversations.confirm` (`APPROVAL_SCOPE` 403), after the basket was shown as ready. The check is now unconditional (POL-014): a known total with no active approver able to cover it, or no active approver, is `needs_resolution`.
- Evidence: `tests/test_spend_authority.py -k approver_coverage` (16 passed), `tests/test_edges.py::test_total_above_every_approvers_maximum_needs_resolution`, mutation M5.
- Impact: A buyer with no active approver cannot buy. Announced to the owner as a behaviour change.

### F-POLICY-005: The runtime database role cannot write policies, which blocks an in-process policy edit
- Date: 2026-11-14   Track: 3   Status: verified (by reading and `tests/test_runtime_permissions.py`)
- Finding: `permissions.py` revokes INSERT/UPDATE/DELETE on `buyers`, `identities`, `policies`, `internal_agents` from the runtime role and installs an update guard on `buyers`/`identities`; the `policies` table has no actor column and `audit_events.proposal_id` is NOT NULL, so a recorded policy edit needs new storage and a narrow grant (a SECURITY DEFINER function or second role). POL-007 (policy edit) and POL-012 are deferred by the owner; this is the design constraint for when they return.
- Evidence: `src/aimo/permissions.py`, `001_initial.sql` L6-8 and L67, `2026-11-14-audit-ws-c.md` (POL-007 row).
- Impact: Do not build `update_purchase_policy` before the grant mechanism is agreed with person 1.

### F-POLICY-006: Per-meal authorization is derived; only its withdrawal is stored
- Date: 2026-11-14   Track: 3   Status: verified
- Finding: The authorization is the customer's approval of one proposal revision (an approved `approvals` row or a `customer_confirmations` row); the agent can create neither. `meal_authorization_withdrawals` (migration 010, append-only, `immutable_record` guarded) records a withdrawal, which is terminal for the proposal, supersedes open approvals, blocks `commit_order` (`AUTHORIZATION_WITHDRAWN`) and reads as `authorization_withdrawn`. It never writes the standing list. Nothing calls it automatically on a recipe edit yet.
- Evidence: `tests/test_meal_authorization.py` (19 passed), mutations M1 and M8, `ws-c/POL-010.md`.
- Impact: Server-side Service call only, no browser route (owner Q-54); something server-side (the runner or the turn handling) still has to call it when a recipe is edited or un-confirmed; nothing does yet.

### F-POLICY-007: Unsupported dietary requirements are now a named reason
- Date: 2026-11-14   Track: 3   Status: verified
- Finding: A stated requirement the catalog cannot verify (for example gluten-free) was a 422 for an unknown key (fail-closed but invisible to the buyer). `Requirements.unsupported` (list of short texts) turns each entry into an unresolved `REQUIREMENT_UNSUPPORTED` reason, so the basket is `needs_resolution` and cannot commit. Raw unknown keys are still rejected. This changes the generated `ProposalResponse.request.requirements` schema (frontend types must be regenerated by person 1). The agent has to be told to use it (person 2's prompt).
- Evidence: `tests/test_unsupported_requirements.py` (9 passed).
- Impact: Closes the unsupported half of POL-009. The assumption half (POL-008) waits on constraint provenance (issues #75, #92); its target is pinned by a strict xfail and designed in `ws-c/pol-008-design.md`.

### F-ISOLATION-001: Revocation and cross-buyer access are enforced in every entry point
- Date: 2026-11-14   Track: 3   Status: verified
- Finding: `context()` validates the (id, buyer_id, role, active) tuple against the database on every Service, workflow and conversation function, so a forged `buyer_id` or a revoked identity is refused (403, or 404 where the proposal is looked up first, with no data returned). The second-buyer walkthrough and 21 revocation cases pass; mutations M2 and M3 are detected.
- Evidence: `tests/test_isolation.py`, `tests/test_revoked_identity.py`, `ws-c/SEC-001.md`..`SEC-003.md`.
- Impact: `workflow.get_proposal` looks up the proposal before validating the identity; informational (404 instead of 403).

### F-PERSIST-001: The `immutable_record` trigger does not fire on TRUNCATE; the runtime role cannot truncate
- Date: 2026-11-14   Track: 3   Status: verified (test database); production role ownership unverified
- Finding: The history tables are protected against UPDATE and DELETE by row triggers; PostgreSQL does not fire row triggers on TRUNCATE, so the schema owner, a superuser or any role later granted TRUNCATE could erase history (4 strict xfails). The restricted runtime role built by `configure_runtime_role` holds only SELECT/INSERT/UPDATE/DELETE and **does not hold TRUNCATE** on any history table (no default ACL, PUBLIC grant, ownership or role membership gives it), so application code cannot do it: this is a missing guard against an operator or a leaked schema-owner credential, not an application exposure. A statement-level BEFORE TRUNCATE guard is designed (session-setting escape hatch for the test fixture's `TRUNCATE ... CASCADE`) but not built: no migration number is reserved. `004_worker_queue.sql:8` is the one migration that rewrites historical rows (`conversation_turns` state).
- Evidence: `tests/test_runtime_truncate.py` (10 passed, live NOLOGIN role with a positive control), `tests/test_additive_migrations.py` (4 strict xfails), `ws-c/per-002-truncate-design.md`, `ws-c/PER-002.md`.
- Impact: Add the guard and `REVOKE TRUNCATE, REFERENCES, TRIGGER` in `permissions.py` in one PR with the fixture's `SET LOCAL aimo.allow_history_truncate='on'` once 012/013 is reserved.

### F-AGENT-005: The agent can reach no purchasing verb
- Date: 2026-11-14   Track: 3   Status: verified
- Finding: The tool registry (recipe tools on or off) holds only read, plan and prepare tools; approve, confirm, commit, policy edit and withdrawal are refused by name with zero Service calls; no agent module references a purchasing function. `Service` is still handed whole to the runner, so safety rests on the registry.
- Evidence: `tests/test_agent_cannot_purchase.py`, `tests/test_agent_tool_verbs.py` (127 passed), `ws-c/TCT-007.md`.
- Impact: A new tool must be added to the allow-lists in those tests on purpose.

### F-SEC-001: `/mcp` ingress paths remain after the MCP removal
- Date: 2026-11-14   Track: 3   Status: verified (by reading)
- Finding: `deploy/kubernetes.yaml` (path `/mcp`) and `infra/kubernetes/ingress.tf` still route `/mcp` to the API, which answers 404. No MCP import, dependency or route exists in `src/`.
- Evidence: `tests/test_no_mcp.py` (7 passed); `grep -rniE mcp src scripts pyproject.toml uv.lock` prints nothing.
- Impact: Harmless; person 1 can remove the paths.

## Proposal, confirmation and receipt (person 3)

### F-CONFIRM-001: Only the internal agent needed a customer confirmation to commit
- Date: 2026-11-14   Track: 3   Status: verified (fixed, CNF-003/004)
- Finding: `commit_order` required a recorded customer confirmation only for identities listed in `internal_agents`. The retained `demo-agent` (and any other `agent` role) could commit a `ready_to_commit` proposal with no human. It was not reachable over HTTP (no login, no commit tool), so it was a defence-in-depth gap. The gate now covers every identity with role `agent`.
- Evidence: red first: `tests/test_confirmation_contract.py::test_any_agent_identity_needs_a_recorded_confirmation_to_commit` failed with "DID NOT RAISE" and `APPROVAL_REQUIRED`; green after commit `c6f91ba`. A human approval decision alone is not a confirmation (the test asserts it). `tests/test_lock_order_and_login_contract.py` shows agent ids cannot log in and a forged agent session authenticates nothing.
- Impact: Any test or caller that commits as an agent must record a confirmation first (`confirm_terms` fixture in `tests/conftest.py`, or `conversations.confirm`).

### F-CONFIRM-002: The confirmation gate must not turn a blocked outcome into a different error
- Date: 2026-11-14   Track: 3   Status: verified
- Finding: The gate is applied only to `ready_to_commit` and `approval_required`. A `denied` or `needs_resolution` proposal skips it and is refused as `COMMIT_BLOCKED` by `authorize_commit` (CNF-015). Without that condition 25 existing tests failed on the first attempt (code changes from `COMMIT_BLOCKED`), and a needs_resolution proposal with a recorded confirmation would reach `Decimal(None)` in the gate (read in the code, not run).
- Evidence: `tests/test_workflow.py::test_four_outcomes_and_hard_requirements` (8 cases) and `tests/test_receipt_and_expiry_contract.py::test_blocked_outcomes_cannot_be_confirmed_or_committed`.
- Impact: Keep the outcome condition if the gate is moved into a `workflow.confirm_purchase` (T3).

### F-CONFIRM-003: The fingerprint ignores authority, so the revision number must bind a confirmation
- Date: 2026-11-14   Track: 3   Status: verified
- Finding: `material_fingerprint` covers request, lines, prices, deposits, product facts, cutoff, currency, mode, charges, policy version and blockers. It excludes lookup time, stock fluctuations that stay sufficient and the authority evaluation. Three revisions caused only by authority changes have the same fingerprint, so a confirmation lookup on `(proposal, fingerprint)` alone would carry a revision-1 confirmation to revision 3.
- Evidence: `tests/test_confirmation_contract.py::test_confirmation_does_not_carry_to_a_revision_with_identical_terms` (three revisions, one fingerprint, commit of revision 3 gives `CUSTOMER_CONFIRMATION_REQUIRED`). Mutation check on a scratch copy: removing `revision=%s` from the query at `approval_workflow.py` is caught by this test and by `tests/test_refresh_contract.py::test_a_proposal_that_really_expires_refreshes_without_its_old_confirmation`, not by a price-change test; removing the fingerprint condition is not observable because revisions are immutable.
- Impact: Never relax the revision condition; the fingerprint is defence in depth.

### F-CONFIRM-004: The internal agent has a zero autonomous limit, so tests reach `ready_to_commit` only with the retained agent
- Date: 2026-11-14   Track: 3   Status: verified
- Finding: Migration 003 creates internal agents with `autonomous_limit "0"`, so every basket they prepare is `approval_required`. A `ready_to_commit` fixture needs the retained `demo-agent`. WS-C removes the agent's spend authority afterwards, which changes this.
- Evidence: `migrations/003_chat_purchasing.sql`; `tests/test_confirmation_contract.py::test_policy_outcome_and_customer_confirmation_are_separate_fields` (two cases, comment explains which agent).
- Impact: Re-check those two cases after WS-C merges.

### F-CONFIRM-005: Orders are immutable (migration 008); what the trigger does not cover
- Date: 2026-11-14   Track: 3   Status: verified
- Finding: `008_orders_immutable.sql` adds `immutable_orders` (BEFORE UPDATE OR DELETE, FOR EACH ROW, reusing `immutable_record()`). It does nothing on an empty table, does not fire on TRUNCATE (the test fixtures truncate), and `proposals.order_id` stays mutable on purpose (it is set once at commit). Nothing in `src/` updates or deletes `orders`.
- Evidence: `tests/test_orders_immutable.py` (4 passed; red before the migration); upgrade scenarios A, B and C below.
- Impact: Someone with table ownership can still drop the trigger; the guarantee is against the application and the runtime role.

### F-CONFIRM-006: A repeated confirmation with a different key is refused today
- Date: 2026-11-14   Track: 3   Status: verified (workflow half); route half pending
- Finding: Same key returns the saved receipt before any supplier call. A different key on an already ordered proposal gets `DECISION_CLOSED` from `conversations.confirm`. Approved wording (CNF-011): any key returns the saved receipt. `workflow.prior_result(..., any_key=True)` now finds the order of the same revision (and still raises `IDEMPOTENCY_CONFLICT` for a key used for other terms); `commit_order` keeps `ALREADY_COMMITTED` for a new key on purpose (existing tests assert it).
- Evidence: `tests/test_confirmation_contract.py::test_prior_result_any_key_finds_the_saved_receipt_of_the_ordered_revision` (passes); `...::test_repeated_confirmation_with_another_key_returns_the_saved_receipt` (strict xfail, fails with `DECISION_CLOSED` at `conversations.py:343/348`). With the one-line change `old = workflow.prior_result(c, identity, body, any_key=True)` on a scratch copy, 43 tests pass including the former xfail. Patch text: `Assistant/projects/junction/evidence/ws-d/cnf-011-conversations-confirm.patch.txt`.
- Impact: Person 1 applies the line (their file) and the xfail mark is removed in the same change. The browser key is deterministic per proposal, revision and user, so two tabs already share a key.

### F-CONFIRM-007: PR #38's in-place refresh never reuses an old decision
- Date: 2026-11-14   Track: 3   Status: verified on the merged code
- Finding: A refresh appends revision N+1 to the same proposal only when it has no order and is expired, rejected, policy/authority-changed, denied or needs_resolution. The revision-N confirmation and approval do not apply to N+1 (approval `superseded`, new pending approval), the saved receipt is untouched, a refresh after an order is `RECIPE_PLAN_LOCKED`, and migration 007 keeps the `(buyer, agent, key)` primary key so each key stays idempotent. A retry of the first key after a refresh returns the proposal at its current revision. Neither validation call holds a lock across the supplier call.
- Evidence: `tests/test_refresh_contract.py` (5 passed, including a real 2.3 s expiry without a patched clock); PR #38's `tests/test_recipes.py::test_concurrent_preparations_release_connections_and_plan_locks_during_supplier_io`.
- Impact: A recipe plan can buy once; a repeat purchase needs a new plan. A recipe basket with a pending approval cannot be refreshed until it is rejected or expires (owner Q-31: intended).

### F-CONFIRM-008: The proposal fingerprint is stored but not returned (PRP-002)
- Date: 2026-11-14   Track: 3   Status: verified (gap open)
- Finding: `render()` and `ProposalResponse` return id, revision, totals, outcome and expiry, not the fingerprint, although `IF-P3-P1-001` promises it to the frontend.
- Evidence: `tests/test_receipt_and_expiry_contract.py::test_proposal_response_carries_every_required_field` (strict xfail on the missing fingerprint).
- Impact: Adding it changes the shared schema and the generated frontend types; waits for person 1's agreement (T2).

### F-CONFIRM-009: One condition, two expiry codes
- Date: 2026-11-14   Track: 3   Status: verified (left as is)
- Finding: An expired proposal is `DECISION_CLOSED` (409) on the confirm route and `PROPOSAL_EXPIRED` on `commit_order`. Person 1's closed code list for the route has `DECISION_CLOSED`, so the route code stays. `DECISION_CLOSED` also covers finalized and older-policy proposals.
- Evidence: `tests/test_receipt_and_expiry_contract.py::test_confirmation_after_expiry_is_refused_without_side_effects` and `test_commit_after_expiry_is_refused_before_any_supplier_call`.
- Impact: Clients must treat both as "prepare a fresh proposal".

### F-CONFIRM-010: Migrations 008 to 011 upgrade cleanly from three real starting states, but the app needs 009 and 010 first
- Date: 2026-11-14   Track: 3   Status: verified (scratch schemas, not a real cluster)
- Finding: With all four branches merged (008 orders_immutable, 009 product_withdrawn_since, 010 meal_authorization_withdrawals, 011 proposal_revision_ordering) a full upgrade applies cleanly and a second run skips all 12 from: (A) production state 001 to 003 only; (B) main state 001 to 007 plus 011, with 008 to 010 landing later out of ledger order; (C) a database that already ran the old PR #38 `008_proposal_revision_ordering.sql` (011 does not replay its backfill; the old ledger row stays). Orders placed before the upgrade are unchanged and protected. The new application code reads `products.withdrawn_since` (`ingest.publish`) and `meal_authorization_withdrawals` (`render`), so it cannot run before 009 and 010 are applied.
- Evidence: `Assistant/projects/junction/evidence/ws-d/integration-dry-run-2.md`; script `scratchpad/mig3/mig3.py` (scenarios A, B, C), run by a subagent on the previous tree and re-run by me on the final tree.
- Impact: Release note: the migration Job must run before the new images start (the release pipeline does that); there is no app-before-migrate compatibility, so a rollback of the image does not undo the migrations and an image from before this release should not be started against it without review. `DELETE FROM orders` is rejected only when an order row exists.

### F-CONFIRM-011: Removing unfinished proposals (CNF-021) is blocked by immutable triggers and foreign keys
- Date: 2026-11-14   Track: 3   Status: verified (analysis); implementation not started
- Finding: Tables referencing `proposals` or `proposal_revisions`: `proposal_revisions`, `approvals`, `audit_events`, `customer_confirmations`, `prepare_requests`, `recipe_plans`, `conversation_messages`, `meal_authorization_withdrawals`, `orders`. Four of them have `immutable_record` triggers that reject DELETE and none has `ON DELETE CASCADE`. A cleanup needs a reviewed trigger change that still protects ordered proposals, a deletion order (children first) and unlinking `recipe_plans` and `conversation_messages`.
- Evidence: design `Assistant/projects/junction/evidence/ws-d/cnf-021-design.md`; `tests/test_unfinished_cleanup_contract.py` on `p3/ws-d-2` (`81d9bcb`): a passing guard that fails when a new table starts referencing proposals, and a strict xfail for the proposed `purge_unfinished_proposals`.
- Impact: Owner decided a 30-day default period counted from the current revision's expiry (Q-56) and an append-only `purged_proposals` table (Q-57). Needs migration 012 (not reserved) and a setting for the period (person 1's `config.py`). Not built.

### F-CONFIRM-012: Test environment traps seen while building WS-D
- Date: 2026-11-14   Track: 3   Status: verified
- Finding: (1) `python -I` ignores `PYTHONPATH`, so a run can silently import another worktree's code; check `aimo.__file__`. (2) `uv` is not installed on this machine, so `tests/test_sweep.py::test_live_ci_without_key_exits_before_starting_server` fails here only (it runs `tests/ci.sh`). (3) On the shared Postgres (port 55432) `CREATE/DROP DATABASE` forces a cluster-wide checkpoint and hung for over nine minutes when other sessions ran suites; use schema isolation or a tuned throwaway container. (4) `mission` and `request_data` share one dict, so a test that requests both gets the mission for both. (5) Row-level immutability triggers do nothing on an empty table, so a test must create a row before asserting a rejected DELETE.
- Evidence: the runs recorded in `Assistant/projects/junction/evidence/2026-11-14-audit-ws-d.md` and `evidence/ws-d/`.
- Impact: Avoids repeating these detours.


### F-CHAT-002: Buyer session contract (login/session/logout) matches its Playwright mocks
- Date: 2026-11-14   Track: 4   Status: verified
- Finding: `src/aimo/auth.py` returns `{"error": {"code": "LOGIN_FAILED", ...}}` (401) for bad credentials and `{"error": {"code": "UNAUTHENTICATED", ...}}` (401) for a missing/expired session; a successful login sets an `aimo_session` cookie (`HttpOnly`, `SameSite=strict`, 8h `Max-Age`) plus a `csrf_token` in the JSON body that the browser must echo as `X-CSRF-Token` on mutating calls, including logout; logout returns 204 and clears the cookie (`Max-Age=0`), after which `/api/session` is 401 again. `frontend/e2e/session.spec.ts`'s mocked fixtures (`mockSession`) and `frontend/src/main.tsx`'s `Login`/`App`/`logout` code reproduce this shape exactly.
- Evidence: `src/aimo/auth.py:109,133` (error codes); `frontend/e2e/session.spec.ts` and `frontend/src/main.tsx` (mock/consumer agreement). Reproduced live in this worktree against the running `aimo serve` instance (`DATABASE_URL` pointing at a local Postgres container) with `curl`: bad password → 401; correct `DEMO_BUYER_PASSWORD` from `.env` → 200 + `Set-Cookie: aimo_session=...; HttpOnly; SameSite=strict` + `{username, buyer_id, csrf_token}`; `GET /api/session` with that cookie → 200 (same shape); `POST /api/logout` with `X-CSRF-Token` → 204 + cookie-clearing `Set-Cookie`; `GET /api/session` after logout → 401. See also `docs/pre-existing-work.md`'s buyer-session row for an earlier independent manual run with the same result; neither run is a committed automated check.
- Impact: The mocked Playwright seam for issue #67 is a faithful stand-in for the live session API, not an invented shape. Cookie issuance/expiry beyond this manual spot-check is covered only by the (separate, out-of-scope-for-this-cut) `AIMO_INTEGRATION=1` live-server suite, not by the mocked unit tests above.

### F-RELEASE-001: Backend/catalog-sync integration
- Date: 2026-11-14. PR #118 integrates #108, #110, #113, #114, #116 and #109 with develop's memory, scheduled sync and frontend reorganization.
- Both import entry points retain absent products as withdrawn and apply the existing protected-product cleanup. Migration 013 separates approved snapshot count from stored count and exposes only protected product IDs through an owner-privileged view; the catalog role still cannot read purchasing/session/identity tables. It gains only column-level product-count update and view SELECT.
- Denied purchases correctly fail COMMIT_BLOCKED before confirmation; the memory regression now expects that result. Tool-boundary tests allow explicit memory operations while retaining identity and purchasing restrictions.
- Validation is recorded on the PR; new tests cover retained-product skip accounting, legacy-count rebuilds and protected-product retention under catalog-only credentials. No live API calls or Terraform apply.

### F-LOCAL-001: Local container environment supports real buyer login and AI chat
- Date: 2026-11-14. Built this branch's frontend and API Docker targets and started an isolated local Compose project with PostgreSQL, API, worker and frontend, exposed only on loopback (`localhost:8000`, database port 55433). All four containers passed readiness checks. Local configuration, generated buyer credentials and the copied private provider key remain in ignored files.
- Applied all packaged migrations and seeded the demo buyer plus ten authored fixture products using deterministic fixture embeddings. Catalog/commerce data is synthetic; chat uses the existing OpenRouter configuration and enforced guardrails. The local Nginx override permits the existing Google Fonts. Production routing/configuration is unchanged.
- Verified through the real local HTTP API: buyer login, cookie-backed session restoration, purchase history, queued chat execution and a persisted assistant reply with no remaining busy/retry state. Opened the sign-in page in Chrome. No cluster, Terraform, production database or supplier API was used. This is frontend development data, not the full supplier catalog or recipe dataset.

### F-OBS-001: Correlated diagnostics and Sonnet main-chat configuration
- Date: 2026-11-14. A production carbonara turn reached the four-tool-error fallback, but individual tool failures were not retained: progress reporting had no callback in the durable worker. Recipe scaling and catalog search had succeeded; the exact failed tools could not be reconstructed.
- Change: JSON events now trace API request → queued turn → worker attempt → model/tool/service boundaries without requiring a progress observer. Provider retries, guardrail decisions, database failures/slow connections, ingestion and worker lifecycle are logged. Unexpected exceptions retain class and bounded stack locations without exception text/source/locals. Tests exercise correlation, concurrent isolation, streaming, validation privacy and third-party exception sanitization.
- Model: new defaults select `anthropic/claude-sonnet-5.5` via OpenRouter, low reasoning effort, 8192 completion tokens and a 45-second request timeout. Opaque reasoning/signature blocks survive tool rounds without entering persisted messages or logs. Existing explicit environment, Secret, Terraform and GitHub-variable overrides remain effective; see `docs/logging.md` for release steps.
- Validation: local fixture-backed `tests/ci.sh` passed (1690 tests, 83 expected failures; 11 strict HTTP sweep checks); subsequent focused checks cover additional metadata/privacy changes. Frontend production build, Terraform formatting/validation, 20 mocked portable infrastructure tests and 10 release-secret helper tests passed. A separate live OpenRouter smoke completed one synthetic Sonnet tool round and returned the expected value; that response did not include reasoning metadata, whose replay is covered by a deterministic provider test.
- Scope: isolated local test databases only; no production application/data changes, rollout, merge or Terraform apply. Logs use existing Kubernetes retention; no centralized collector was provisioned.

### F-FE-STYLE-001: Production styling retains the existing purchasing workflow
- Date: 2026-11-14. Ported PR #102's presentation into the production `app/`, feature pages/components and shared badges/errors. No route, feature hook, API module, generated schema or backend change; no preflight. Removed superseded legacy screen CSS.
- Validation: `npm run check` passed; all 11 existing credential-free `e2e/chat.spec.ts` regressions passed, including session deep links, exact-revision confirmation, revised terms, historical approvals and retry/SSE recovery. Manual fixture browser captures of chat, purchase history, purchase review and login at 1440, 768, 390 and 320 pixels showed no horizontal page overflow. No live backend or supplier calls were made.

### F-FE-STYLE-002: Complete designer screens use the production feature structure
- Date: 2026-11-14. Completed the #102 customer UI integration: Home, fixed desktop sidebar/mobile menu, collapsible conversations, Request context/thread/SKU cards/composer, desktop Overview/mobile drawer and expandable accepted-only Past Orders. Production hooks/API modules/generated types remain authoritative. Historical approval revisions and unplaced purchase deep links retain review access; full quantities, checks, evidence and history remain available. Added Tailwind preflight, removed legacy CSS and allowed the existing Google Fonts resources in frontend CSP. Screen mapping: `frontend/docs/designer-integration.md`.
- Purchasing: Overview uses the existing CSRF-protected exact-revision confirmation and stable retry key; revised terms require another explicit click. No prototype store, fake login, scenario switcher or backend/schema/dependency change. Schedule/hub/account-manager examples and unavailable controls are labelled placeholders. Conversation GET responses cannot overwrite a newer SSE/send snapshot; navigation keeps pagination and purchase responses are scoped to the selected detail.
- Validation: `npm run check --prefix frontend` passed; `npm test --prefix frontend` passed 24 browser regressions, with 2 opt-in backend/database integration checks skipped. Fixture captures inspected across Home, Request, Past Orders, review and login at desktop/mobile widths; no horizontal page overflow at 1440, 1024, 768, 390 or 320 pixels. Production frontend Docker build and `nginx -t` passed. The running local app accepted the local buyer sign-in and rendered Home, Request, empty Overview and Past Orders without page errors. Local commerce remains fixture data; no supplier API calls or real orders were made. Only the local frontend container was rebuilt; API, worker and database were preserved. No merge or deployment.

### F-POLICY-SETTINGS-001: Buyer-managed purchasing rules

- Date: 2026-11-14. Owner requested an isolated worktree and a Settings page replacing command-line policy management. This supersedes the earlier policy-editor deferral.
- Change: `/settings` and authenticated policy GET/PUT let designated buyer policy managers version product scope, substitution/overbuy rules, destinations and whole-unit rounding. Spending permissions remain separately administered. The product-scope CLI is removed; agent tools remain read-only for policy.
- Enforcement: migration 014 adds explicit manager grants, immutable change attribution and a restricted save function. Runtime provisioning rights remain revoked. Buyer locking, optimistic version checks, active-actor checks, session/Origin/CSRF and catalog-ID validation protect edits. Existing proposal policy checks require fresh revisions and customer confirmation after a change.
- Validation: backend lint and full PostgreSQL suite passed (1705 passed, 83 existing expected failures); strict fixture HTTP sweep passed all 11 checks. Frontend formatting/lint/typecheck/build passed; browser suite passed 21 tests with two live integration tests skipped. The six new browser tests cover saving/reload, read-only access, conflicts, session expiry and desktop/mobile layouts; both screenshots were visually inspected. Focused database tests prove manager/agent isolation, restricted-role saves, immutable history, concurrent edits and old-confirmation invalidation. Only isolated local test databases were migrated; no cluster writes, deployment or merge.

### F-POLICY-SETTINGS-002: Rebase onto designer UI and current backend

- Date: 2026-11-14. Rebased onto develop `6736101` (#131). Resolved route/header, stylesheet, API-import and appended-document conflicts while retaining the new shell, preflight, receipt contracts and backend response protections. Account Settings is now a real active-state link in the desktop sidebar/mobile menu; Settings no longer depends on legacy CSS. Added migration 014's tables, trigger and function to the current readiness manifest and tested missing objects as owner/runtime roles.
- Validation: `tests/ci.sh` with isolated rebase test databases passed (1768 passed, 81 existing expected failures; 11 fixture HTTP sweep checks). Frontend formatting/lint/typecheck/build passed. The full browser suite passed 33 tests with two live integration tests skipped. Settings navigation, active state, mobile-menu dismissal and no horizontal overflow passed at 1440, 1024, 768, 390 and 320 pixels; all five screenshots were visually inspected. No cluster changes, merge or deployment.

### F-FE-MEMORY-001: Assistant preferences screen for buyer and personal memory
- Date: 2026-11-14. Added `/settings/preferences` on top of the merged memory API (#105): separate personal/buyer tabs, typed add/edit for the supported keys only, revision-checked edits with conflict recovery, server-confirmed forget, and links from the account menu and chat header. No backend, schema or dependency change; `ApiError` now also carries the server's error code.
- Validation: `npm run check` passed; `npm test` passed 33 browser regressions (9 new in `e2e/preferences.spec.ts`), 2 opt-in integration checks skipped. Live against an isolated local API (fixture upstream, `GUARDRAIL_MODE=off`, own PostgreSQL container) through the real UI: created one personal and two shared preferences, all persisted across reload in their own scopes, edited one, produced a real `MEMORY_REVISION_CONFLICT` from a second tab (draft kept, latest value loaded), forgot one and confirmed it stayed gone after reload; no horizontal overflow at 390 px.
- Not verified: agent retrieval of a saved preference in a new conversation (no provider key in this environment). Gaps are listed in `docs/memory.md#browser-screen`.

### F-GOOGLE-001: Portable native Google API helper
- Date: 2026-11-14. Added `google_api_request` for native generateContent (chat/tools/images), embedContent, Decisions and model discovery. Uses existing HTTPX; copyable without app imports. Key comes from an explicit argument or process `GEMINI_API_KEY`; app Settings can load ignored `.env`. Responses retain opaque tool signatures and image parts. Fixed Google host, disabled redirects, bounded responses, safe errors and no implicit retries.
- Verification: Python lint and 22 authored transport tests passed. Full `tests/ci.sh` passed against fresh isolated databases: 1714 tests passed, 83 expected failures, and all 11 strict HTTP sweep checks passed. The initial run against the existing local test database hit stale-schema errors; fresh databases resolved them. Live model discovery succeeded with the private hackathon key. Three tiny synthetic requests succeeded: Carbon returned a candidate, Embedding 2 returned 768 dimensions, and Decision 1 returned a typed `noul` probability. No image-generation or Cloudinary call was made by this change.
- Scope: additive client and documentation only. No active provider, guardrail policy, schema, catalog, deployment or purchase behavior changed. The native decision adapter and embedding reindex remain separate work.

### F-IMAGE-001: Recipe image generation, hosting and chat attachments
- Date: 2026-11-14. Added `generate_recipe_image`: a bounded dish/appearance brief goes to Google Nano Banana 2.1, then a signed Cloudinary upload returns a hosted illustration. The ordinary chat model chooses the tool. Server-authored labels distinguish illustrations from ingredient, dietary or purchase evidence. Existing conversation JSON/SSE persists the optional image alongside text; the frontend handles refresh, mobile layout and missing assets.
- Retry/cost controls: migration `015_recipe_images.sql` adds a per-turn generation ledger and nullable message image. One paid attempt per message, default five per buyer/hour, scoped active-worker checks, stable random upload IDs, no automatic generation retries, and saved bytes for interrupted uploads. Successful uploads clear bytes; old pending bytes are cleared on the buyer's next image request after 24 hours. Local Compose, the release secret helper and Terraform worker secrets support the two credentials; no deployment was performed. Actions secret-forwarding edits remain a local patch: the repository credential lacks `workflow` scope and the available SSH identity lacks repository write access. Those workflow edits must be applied with authorized credentials before Actions can supply the image keys.
- Verification: full fixture-backed `tests/ci.sh` passed (1749 tests, 86 expected failures, all 11 strict HTTP sweep checks). After final worker-context/recovery changes, 144 focused image/conversation/memory/authority checks passed, including two additional recovery/retention regressions. Python lint, frontend `npm run check`, all 18 credential-free browser tests (two integration tests skipped), 48 infrastructure helper tests, Terraform validation and all 20 mocked portable Terraform tests passed. Initial full-run failures identified the existing explicit tool allowlists; these were extended only for the new illustration tool, retaining purchase prohibitions.
- Live QA: one synthetic pasta image generated and uploaded successfully in 16.3 seconds (1200×896 JPEG). The actual Cloudinary URL rendered in chat at 1440px and 390px; screenshots were inspected. Browser API/session responses were authored fixtures, not a deployed customer session. No image or credential is committed; local QA artifacts are ignored. No embedding migration, chat-model switch, Terraform apply, merge or deployment.
- Release follow-up: at the owner's request, included the prepared Google/Cloudinary secret-forwarding changes in the same image-tool PR (#132). Both reusable-workflow declarations and the deploy-job environment pass only repository-secret references to the worker secret helper. Deployment remains explicitly gated; no credentials or QA image assets are committed.
- Final verification after integrating latest develop: full fixture-backed `tests/ci.sh` passed with 1810 tests passed, 84 expected failures, and all 11 strict HTTP sweep checks passed. The 48 infrastructure helper tests also passed after the workflow update. Both Actions workflow files are now committed to #132, superseding the earlier local-patch limitation; test jobs are unchanged.

### F-GOOGLE-002: Native Google adapters for every active model role
- Date: 2026-11-14. At the owner's request, PR #132 now defaults chat/tool selection to Gemini 4 Carbon, semantic guardrails and product relevance ranking to Gemini Decision 1, and product/recipe embeddings to Gemini Embedding 2 at 768 dimensions. All use the existing server-side `GEMINI_API_KEY`; images remain Nano Banana 2.1 plus Cloudinary. Explicit legacy adapters remain available, with no fallback on Google failure.
- Native chat replays complete model parts and call IDs inside the turn, including opaque signatures, but persists only visible text/tool outcomes. Decision requests translate server-owned true/false criteria to Google's schema; purchasing authority and exact customer confirmation remain deterministic. Embedding documents use independent requests with Google's retrieval prefixes; profile keys reject old product/recipe vectors and isolate caches. Existing deployments require the staged cutover in `docs/google-models.md`; no production import or rollout was performed.
- Verification so far: 174 focused provider/agent/guardrail tests and the PostgreSQL product/recipe cutover test passed; 49 infrastructure helper checks, Terraform validation and 20 mocked portable Terraform tests passed. A live synthetic Carbon tool round accepted all 16 application tool schemas and replayed its signature; real document/query embeddings returned 768 dimensions and Decision 1 ranked the two synthetic products correctly. No real tool action or customer data was used. The Google worker image built successfully and imports without Torch/SentenceTransformers; local E5 image support requires an explicit build argument.
- Fresh live Decision 1 evaluation: 65 authored synthetic cases across input, preparation, catalog text and output. No missed attacks, wrong attack classifications, false blocks or unavailable results in this sample; two benign preparation changes were uncertain (`tc-budget-updated`, `tc-accepted-destination`) and therefore require clarification under enforcement. Existing thresholds remain provisional; this small evaluation is not an accuracy guarantee. Results: `docs/google-guardrail-evaluation.json`.
- Final verification: `tests/ci.sh` passed with 1832 tests passed, 84 expected failures and all 11 strict HTTP sweep checks passed against isolated databases. Integrated develop's designer UI (#131), retained its markup/fonts/security headers, moved illustration styling into Tailwind utilities, and kept image persistence/fallback coverage. Frontend `npm run check` passed; all 27 credential-free browser regressions passed, with two optional backend integration checks skipped. Desktop/mobile image fixture captures were inspected. No merge into a shared branch, live catalog import or deployment.

### F-IMAGE-UI-REBASE-001: Recipe images fit the designer chat
- Date: 2026-11-14. Rebased PR #132 onto `develop` at `c9f51d2`, preserving the designer transcript, Tailwind illustration styles, Google Fonts CSP, Cloudinary image allowance and newly merged buyer policy settings (#128). Both migrations 014 and 015 retain their readiness probes. No image runtime change was needed; this follow-up strengthens layout coverage.
- Verification: frontend `npm run check` passed; `npm test` passed 38 browser regressions, with two optional backend integration checks skipped. Image fixtures now have the real 4:3 shape and verify aspect ratio, viewport containment, persistence after refresh and failed-host fallback at 1440, 1024, 390 and 320 pixels. Separate local fixture captures reuse the previously generated pasta photo; no new paid model call, live customer data, catalog import or deployment. The browser contract was regenerated and matches the merged schema, including policy settings and image attachments.
- Combined-backend verification after #128: full fixture-backed `tests/ci.sh` passed with 1853 tests passed, 84 expected failures and all 11 strict HTTP sweep checks passed against isolated rebase databases. Both schema probes and policy/image regressions passed. Desktop/mobile photo captures were visually inspected.

### F-GUARD-FOOD-001: Recipe planning is context, not a purchase claim

- Date: 2026-11-14. Worker logs for the 22:19/22:20 community-lasagna requests show allowed input, successful recipe discovery and generated replies, followed by uncertain output checks for status/commercial claims (and disclosure on the retry). The complete replies were withheld; discarded text is not retained, so the triggering sentence cannot be reconstructed.
- Change: policy `guard-2026-11-14.4` clarifies that meal planning, recipe titles, dietary requests and portion/budget questions need no purchase records. Output review now includes bounded customer messages and recipe summaries as context, without treating them as authority or product dietary evidence. Unsupported purchase/commercial/dietary claims still block; thresholds and confirmation controls are unchanged. The empty-state fallback no longer asks for the same request again.
- Verification: 179 focused provider/agent/guardrail checks passed. Full fixture-backed `tests/ci.sh` passed against separate local databases: 1858 passed, 84 expected failures, all 11 strict HTTP sweep checks passed. Live Google Decision 1 evaluation covered 73 authored synthetic cases: all 21 output cases classified as expected; two existing benign preparation cases remained uncertain. A separate read-only check through the deployed Jev adapter accepted all five new planning examples and blocked all three fabricated purchase/commercial/dietary examples. These small synthetic samples are not accuracy guarantees; no real customer text was sent in evaluation.
- Scope: guardrail prompt/context and regression coverage only; no schema, dependency, purchasing authority, deployment, Terraform or shared-branch merge changes.

### F-GUARD-FOOD-002: Broad food scope and plain refusals

- Date: 2026-11-14. Owner clarified that food, products and nearby topics should be accepted without an immediate purchase, while clearly unrelated requests such as workout routines get a brief refusal. Policy `guard-2026-11-14.5` and the chat prompt now share that direction. Input refusals say "I can't help with that. I can help with food, products and meal planning." Output fallback says "I can't help with that." Saved purchase notices/links remain; internal verification explanations and repeat-request instructions are removed.
- Verification: 180 focused checks and full fixture-backed `tests/ci.sh` passed (1859 tests, 84 expected failures, all 11 HTTP sweep checks). Live Google evaluation covered 82 synthetic cases: all 36 input cases matched expectations, including two unrelated workout requests and seven new food/adjacent examples. No attacks were allowed; two existing preparation examples and one existing basket-total output example were uncertain. A separate read-only Jev check also classified all nine new input examples as expected. Results are small synthetic samples, not guarantees. No real customer text, supplier calls, deployment or merge.
