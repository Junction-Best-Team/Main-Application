# Findings

Non-obvious facts, traps, decisions and known issues, each with evidence. Append to your track's section. Do not delete another track's finding; change its status and say why.

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
- Finding: The owner requested “separete all into their apps, worker is a pod api fe etc” and “new pr new worktree”. The frontend, API and worker now have independent build targets, Kubernetes Deployments/Services, probes and credentials. PostgreSQL stores queued turns; workers claim with bounded leases and attempt fencing. Migration 004 preserves business history and makes historical interrupted turns explicitly retryable.
- Evidence: 144 PostgreSQL-backed backend tests; Python lint; three successful Docker target builds; 8 mocked portable Terraform plans; 28 infrastructure helper tests (including the merged OpenRouter sync); rendered Traefik chart. A three-container smoke with fixture embeddings/provider returned a queued message in 0.02 seconds with the worker stopped, retained it across API restart, processed it after worker startup, and delivered SSE through the frontend proxy. No live supplier calls or production changes were made by these checks.
- Impact: The API no longer loads ML weights or runs agent turns inline. The static frontend receives no secrets. Apply migration 004 and the reviewed separate-app Terraform cutover before enabling the new three-image release pipeline; see `docs/separate-apps.md`.

## Owner decisions

### D-001: Build the Valio Aimo side, not the buyer's agent
- Date: 2026-11-13   Track: all   Status: verified
- Decision: "Can you get rid of the buyer agent interface, and stick with what the brief wanted."
- Impact: Scope is the interface and operating model (lookup, quote and order, mandates and approvals, audit). A thin reference client exists only for demo and testing. See `Plan/post-mvp-plan.md`.

### D-003: The agent contract is fixed in source code
- Date: 2026-11-14   Track: 3 (affects 2, 4)   Status: verified (decision); applies to the MVP, extended for the full product by D-004; design is a draft in `Plan/post-mvp-plan.md`
- Decision: "For the mandate, I would like this to behave as a contract, which is the behavior of how the MCP will behave with the agent. I want it to be fixed in the code, and be unchangable without source code changes."
- Impact: What the agent may do alone is a frozen constant in source, with no endpoint, tool or setting that changes it. Every policy decision and audit event records the contract hash. The human realm only approves or rejects held orders; it cannot edit limits. Production path: replace the constant with a buyer-signed mandate.

### D-004: Two-part contract; client-editable in the full product
- Date: 2026-11-14   Track: 3 (affects 2, 4)   Status: verified (decision); design is a draft in `Plan/post-mvp-plan.md` section 6
- Decision: "In the full feature list, I would like for the contract to be editable by the client only, as part of some sort of settings, but only specific elements. there would be a distribution part of the contract, and a client part of the contract"
- Impact: The contract has a distribution part (Aimo-owned, changed by code release) and a client part (customer-owned). The client part may contain only fields the distribution part lists as client-editable, inside its bounds. The effective contract is the stricter of the two. In the MVP both parts are still frozen constants (D-003).

### D-005: MVP and full design as two parts; customer and agent are separate entities
- Date: 2026-11-14   Track: all   Status: verified (decision)
- Decision: "They are technically one device, but two seperate entities. Also, in the architecture for type1, can you write out the elements/contracts as two seperate elements. Requiremnts for MVP, and requiremnets that would make a great product. So we aren't over commiting, but at the same time, we make sure we build a good first product."
- Impact: The Type1 draft has Part A (MVP) and Part B (full product), with seams so the MVP grows into the full design. The approval request goes to the customer through a channel that does not pass through the agent, and the agent's output contains no approval secret.

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
