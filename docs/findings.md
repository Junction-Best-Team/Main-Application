# Findings

Non-obvious facts, traps, decisions and known issues, each with evidence. Append to your track's section. Do not delete another track's finding; change its status and say why. Rules are in `AGENTS.md`.

Entry format:

```
### F-<area>-<nnn>: <short title>
- Date: YYYY-MM-DD   Track: <1-4 or all>   Status: verified | unverified | superseded
- Finding: <the fact, stated plainly>
- Evidence: <command, file path, request, or source; how someone can re-check it>
- Impact: <what it means for the build>
```

Owner decisions use `D-<nnn>` and quote the owner's words verbatim.

## Owner decisions

### D-001: Build the Valio Aimo side, not the buyer's agent
- Date: 2026-11-13   Track: all   Status: verified
- Decision: "Can you get rid of the buyer agent interface, and stick with what the brief wanted."
- Impact: Scope is the interface and operating model (lookup, quote and order, mandates and approvals, audit). A thin reference client exists only for demo and testing. See `docs/architecture.md`.

### D-002: Connect to the team remote and extend its rules
- Date: 2026-11-13   Track: all   Status: verified
- Decision: "Connect to remote, and extend the rules to also include finding and history behaviors"
- Impact: The existing `AGENTS.md` and `CLAUDE.md` were kept and extended with Data and secrets, Findings and History sections.

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
- Finding: Only 189 of 17,546 products have `substitutions`, shaped as `[{"product": "460025", "substituteProduct": "460150"}]`. The rest are `null`.
- Evidence: count of products with a non-null `substitutions`.
- Impact: Most substitute candidates must come from our own logic (same category and compatible attributes). Use the provided pairs as the highest-confidence source.

### F-DATA-005: Units and volume need derivation
- Date: 2026-11-13   Track: 1   Status: unverified (field layout verified, derivation not tested)
- Finding: Each product has `salesUnit` (most common: `KI` 8,005; `ST` 5,607; `KG` 1,068), `baseUnit`, and `units[]` with `{unitId, gtin, sizeInBaseUnits}`. Volume such as "1 l" appears in the product name text. `synkkaData.unitConversions` has packaging dimensions and weights but is present on only 14,478 of 17,546 products.
- Evidence: field inspection of `data/valio_aimo_junction26_product_data.json`.
- Impact: Converting "1,000 litres" to a number of sales units is the riskiest step. Needs an experiment on lactose-free milk before the Quote contract is final.

### F-DATA-006: Reliability and carbon files are partial
- Date: 2026-11-13   Track: 1   Status: verified
- Finding: Delivery reliability has 4,425 rows and carbon footprint has 11,033 rows, against 17,546 products. Columns: `productId,deliveryReliability` and `productId,AVG kg CO2-eq/kg`.
- Evidence: `wc -l` on the CSV files in `data/` (minus the header).
- Impact: The interface must represent "unknown" explicitly, not zero.

## Live API (from `docs/reference/aimo-api.openapi.json`)

### F-API-001: What the spec says
- Date: 2026-11-13   Track: 2   Status: unverified (taken from the spec, not tested live)
- Finding: Endpoints are `/api/ping`, `/api/availability`, `/api/price` and three download endpoints; there is **no order endpoint**. Each price or availability request takes 1 to 1,000 product codes. The customer number does not affect responses. Rate limits exist but are undisclosed. For Terminal products `availableAmount` is always 999999 because the real stock is unknown. `scheduleLines` is empty when a product cannot be delivered on any date. Auth is an `X-API-Key` header.
- Evidence: the `description` fields in the OpenAPI file.
- Impact: Ordering is our mock. Treat Terminal availability as "unknown but orderable" and check `closingTime`, `salesBlock` and `availableDate` against the requested date.

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
