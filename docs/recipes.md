# Recipe planning

Recipe discovery and purchasing are a standard part of the chat worker (no feature
flag). It uses the existing Service, PostgreSQL/pgvector and purchasing/confirmation
controls. All orders remain mock. The merged release pipeline applies schema/grants
before rollout; recipe import remains an explicit operator action.

## Customer flow

The customer names a meal and guest count. The assistant chooses a suitable saved
recipe, scales it on the server, finds catalog products and prepares the basket.
It chooses normal serving sizes and does not ask the customer to calculate grams,
ingredient ratios or pack counts. Missing delivery facts are asked for only when
needed for preparation; a missing hard budget is left unset, with policy limits
and exact customer confirmation still enforced.

If no suitable saved recipe exists or discovery is unavailable, `draft_recipe`
accepts an assistant-authored ingredient basis and base servings. The server uses
the same exact scaling and upward four-decimal rounding as saved recipes, publishes
the estimate, and preserves its totals while products are attached. This draft is
labelled as assistant-authored and stays a free-form plan: it has no saved-recipe
completeness, suitability or cooked-yield guarantee. It never creates a recipe
database entry or replaces a selected unresolved saved recipe. Plans persist in
ordinary conversation messages; Overview shows the latest draft before a proposal
exists. Pricing, policy and dietary blockers do not prevent showing a draft, but
still prevent a purchase. No new public API, schema migration or dependency.

## Setup and import

1. After the migration credential bootstrap, the release pipeline applies
   the recipe migrations (`005_recipe_planning.sql`, `006_recipe_proposal_link.sql`,
   `007_recipe_refresh_keys.sql`, `011_proposal_revision_ordering.sql`) and runtime
   grants before app rollout.
   For manual local setup use `aimo migrate` with the migration/setup role.
   Schema migration performs no download, seed, embedding or dataset import.
2. With the worker image/code and the same embedding profile as serving, run the
   explicit importer. The default now uses Gemini Embedding 2 with the shared
   server-side `GEMINI_API_KEY`. Existing installations must reimport both recipe
   and product vectors during the [Google cutover](google-models.md).
3. Add reviewed recipe-form/quantity overrides and matching product evidence for
   recipes intended for purchasing. Discovery alone does not establish readiness
   for an executable basket.
4. Recipe tools are always registered. Before an import, or if the active corpus
   was built with a different embedding profile, they report `RECIPES_NOT_READY` or
   `RECIPE_MODEL_MISMATCH`. These tools never invent database records; the
   assistant can offer the separately labelled draft flow above.

Download a selected revision of [UniTools World Recipes](https://github.com/farcrak/unitools-recipes),
retain it privately, independently check its SHA-256, then run:

```sh
# Worker environment: DATABASE_URL and embedding provider settings already supplied.
aimo ingest-recipes --file /data/unitools-recipes.json --expected-sha256 VERIFIED_SHA256
# With reviewed normalization, use the same command plus:
# --review-file /data/recipe-reviews.json
```

The importer validates every record before embedding; caches each successful batch;
atomically activates a complete corpus; and skips unchanged content. An interrupted
import can be rerun without paying for completed batches. Changed recipes produce
immutable content versions; existing plans retain the exact version. Old recipe
versions/corpora are retained for history; automatic pruning is not implemented.
The corpus is a global shared read-only source, while plans are buyer/agent scoped.
An intentional smaller subsequent import replaces the discovery corpus, retaining
old versions. Review the input before activation; staged operator activation is not
part of this importer yet.

Recipe vectors use a separate cache and a `recipes-v1` profile. Qwen query inputs
use a cooking-recipe instruction, bypassing the provider's product-specific query
prefix. Keyword and semantic rankings are fused. With the hosted profile,
only the bounded shortlist is reranked; a reranker outage reports `unavailable`
and retains hybrid ordering. Local E5 and fixture modes also work. Recipe category
is a structured filter; no unverified dietary tags are treated as guarantees.
Reranking happens during discovery, not ingestion. Provider changes require a
recipe reimport as well as the independent product-catalog cutover.

## Reviewed normalization and product facts

The source commonly lacks explicit raw/dry/cooked fields. Preserve `unspecified`
and block purchasing until the relevant recipe forms have been reviewed.
A review file is operator-authored data, never model input. Example shape:

```json
{
  "source": "Operator review reference and date",
  "recipes": {
    "spaghetti-carbonara": {
      "ingredients": {
        "spaghetti": {"form": "dry"},
        "egg": {"form": "raw"},
        "yolks": {"form": "raw"}
      }
    }
  }
}
```

Reviews may also set `quantity`, `unit`, `scaling` and `note`. They create a new
recipe version, retain the original source record and record the review reference.
Do not set `linear` merely to bypass `damped`: establish an appropriate recipe
basis first. Only linear quantities in g/kg/ml/l/piece currently produce executable
amounts; other units, unspecified quantities and fixed/damped/sublinear rules stay
unresolved. Scaled totals round upward to four decimal places.
All source ingredients are required, including salt and pantry items. There is no
pantry exemption, customer quantity-resolution UI or arbitrary editing of saved
recipes. Assistant-authored drafts remain separate from these reviewed records.

Product evidence is also an explicit reviewed import:

```sh
aimo import-recipe-product-evidence --file /data/product-evidence.json
```

The file is a JSON array. Each row contains `product_id`, `product_fingerprint`
(the existing `aimo.db.fingerprint` of the full normalized current product),
`ingredient_id`, `form`, `source`, and optional `piece_per_sales`. Use the exact
source ingredient ID, such as `spaghetti`, not a recipe-row index. Evidence matches
one exact product fact snapshot and ingredient/form. A catalog change invalidates
it. A name or semantic score alone does not establish suitability. Current product
scope, supported dietary checks, stock, price and policy are still enforced by the
purchasing layer. Missing physical weight cannot be repaired by a suitability row.
Variable/unknown-weight products can be matched; the proposal carries a non-blocking
`VARIABLE_WEIGHT_UNRESOLVED` warning (severity `warning`, kept under its earlier code) on
every such line: the final weight and price settle at delivery, so the price is an estimate.
The snapshot line carries `price_is_estimate: true` and the snapshot `totals_are_estimates:
true` (both absent otherwise), and the chat's trusted notice repeats the warning (BAS-007,
owner Q-68).

`piece_per_sales` is the reviewed ingredient yield per purchasable sales unit, e.g.
30 whole eggs per tray. Do not equate yolks with whole eggs without evidence.
The backend preserves ingredient count through purchasing conversion so rounding
excess still triggers overbuy policy. Every prepare and commit revalidation reads
current product suitability and matching count evidence; it never trusts model-authored
pack counts. Revoked suitability blocks confirmation.

## Agent and persistence

Tools: `search_recipes`, `get_recipe`, `scale_recipe`, `get_recipe_plan`, `draft_recipe`,
`match_ingredient`, `match_ingredients` (several ingredient and product pairs, one plan revision,
all-or-nothing), plus the existing product discovery and purchasing tools.

Scaling stores a buyer/agent-scoped plan and all source ingredients. One server
turn fixes one recipe version/portion count; repeat scaling returns the saved plan.
Matching requires inspected product facts, creates a new immutable plan revision,
and preserves unresolved ingredients with reasons. Before preparation the Service
requires exact aggregate quantities for every ingredient, the current plan revision
and unchanged catalog facts. A selected saved recipe cannot be replaced with a
free-form `publish_meal_plan` or prepared without its reference. Enabling recipe
tools is additive: direct product requests retain the ordinary publish/prepare
workflow without a recipe reference.

Known scaled quantities with reviewed forms start as `proposed`: a missing product
selection is separate from an unresolved quantity or form. Customer cards describe
those actual blockers without asking the customer to match products or calculate
weights. The trusted reply summarizes pending product selections by count.
Historical cards also hide the old internal “Match a suitable catalog product” text.
The transcript rephrases the exact old server-generated unresolved-ingredient list
as a product-selection count when it matches the stored plan; persisted messages
and surrounding narrative are preserved.

The runner requires inspection after three consecutive product searches and a
persisted match after three candidate reads on a pending saved plan. It refuses
further discovery when every remaining ingredient lacks a quantity or reviewed
form; catalog search cannot repair those facts. Valid ingredients can still be
matched while another ingredient is blocked. These checkpoints preserve all
existing evidence and preparation checks. A retry includes the current turn's
persisted recipe-plan ID/revision so the assistant reloads its latest matches,
including progress saved before a provider timeout. Provider-failure notices and
exact retry keys retain their existing behavior.

This has a cross-turn enforcement limit: the server does not recognize that a new
free-form plan names the same dish as an earlier unresolved saved recipe. Such a
basket can be prepared without source-recipe coverage or recipe-specific quantity
validation. Its catalog, pack, commercial, policy and customer-confirmation checks
still apply. The server derives `recipe_basis` (`saved_recipe` or `free_form`) from
the persisted, validated recipe reference; the model cannot set this response field.
Chat labels free-form plans and the purchase review explicitly states **recipe
completeness and ingredient conversions are not checked against a saved recipe**.
A free-form label must never be interpreted as an executable saved recipe.

Preparation validates in short database transactions before and after supplier I/O.
No connection or plan lock is retained during that I/O. Proposal creation, retry
key and the prepared-plan lock commit together. A concurrent edit invalidates the
in-flight preparation; concurrent prepares of one plan can create only one proposal.
The same retry key returns the existing proposal. An active basket or completed
order cannot be prepared again with a different key. When an unordered proposal
expires, is denied, needs resolution, or requires policy/authority refresh, a new
customer turn may reload the same plan and prepare corrected commercial terms.
This appends a revision to the **same proposal**, preserving matched ingredients.
Old revisions/decisions stay in history; approval/confirmation is required again.
An approver rejection is final for that recipe plan, including after expiry or
policy changes; a new purchase requires a new customer request and saved plan.
A policy denial can be retried after correcting its cause (date, destination,
budget or buyer policy), retaining the matched ingredients. Every refresh rechecks
recipe completeness, catalog/evidence, quantities, commercial facts and policy;
an unchanged denial still blocks commitment. A current denied recipe proposal
returns `revise_request` so the agent asks for corrected terms; an ordinary current
denial keeps `stop`. Approver rejection takes priority over either hint, including
after expiry. Recipe/product changes still require
a new plan. Ordinary denied proposals retain fresh-preparation guidance after
expiry or policy/authority changes.
Concurrent refreshes fence the prior proposal revision so only one can append;
failed persistence rolls everything back.
Recipe/product changes still need a new plan and matching evidence. Unprepared
plans remain unlocked after a failed first preparation.

Migration 006 adds a unique plan-to-proposal link and backfills old prepared plans;
it fails if legacy history ambiguously contains multiple proposals for one plan.
The owner cannot confirm whether 005 was applied to a shared database, so its schema
is left intact and 006 remains an additive upgrade rather than rewriting history.
Migration 007 allows multiple preparation retry keys to reference one proposal;
the buyer/agent/key primary key and payload conflict checks remain unchanged.
Migration 011 adds an indexed proposal revision timestamp, backfilled from revision
audit events (falling back to creation time). Purchases sorts by this timestamp so
fresh terms return to the top without changing original creation/history dates.
Migration numbers **008–010 are reserved for Person 3** (policy edits, meal
revocation and a spare); **011 belongs to recipe proposal ordering**. No new 008–010
file is added by this PR. An earlier PR revision used
`008_proposal_revision_ordering.sql`: if already applied, leave its ledger row in
place. Migration 011 detects the existing column/index and preserves timestamps.
Both 005 files retain their original names because prior application is unknown;
the runner orders and records full filenames, which is tested.
The API session exposes the recipe flag; chat and purchase recipe-basis labels
appear only when it is enabled. Keep the API and worker flag settings aligned.
Prepared plans remain readable in the same or a new turn; changed recipes require
a new plan/customer turn. Reading another plan after preparation does not replace
the already prepared plan in the agent's result. Browser messages persist plan IDs,
revisions, attribution and matching/conversion status; purchase revisions retain
the recipe-plan reference. Exact authenticated confirmation remains required for
internal-agent purchases, and changed commercial terms retain existing reapproval.

The browser displays unresolved reasons, product IDs, pack counts and excess.
Recipe estimates remain visibly labeled for review; deterministic scaling does not
validate a dataset's culinary quality or its suitability for cooking 200 portions.

## Source and validation

Source: UniTools World Recipes v2.0.0, [upstream data](https://github.com/farcrak/unitools-recipes).
Attribution: **UniTools — theunitools.com**. Recipe data is **CC BY-SA 4.0**;
retain attribution and comply with share-alike for distributed adapted data. Photos
have separate licenses and are not imported. No public recipe records are bundled
into source or images; tests use explicitly authored fixtures.

The checked upstream snapshot SHA-256 is
`41fdc0572b7272ca557d2df22a0fac1cc1f18146e97ebd2c8258c395daf87d8a`.
All 501 recipes and 5,404 ingredients imported into a dedicated local PostgreSQL
`_test` database with fixture embeddings; repeat import reused all 501 vectors and
kept the same active corpus. This is source/schema/import verification, not a live
Qwen retrieval benchmark or live supplier test. Public carbonara still needs review
for forms, yolk/count yields, pepper scaling, salt quantity and missing product facts
before it can produce a complete executable real-catalog basket.

Local verification after the re-review fixes and integration with current develop:
475 backend tests, Python lint, TypeScript/production build, six focused browser
flows, all 10 API sweep checks and the combined 95% coverage gate passed (95.22%).
Earlier infrastructure checks passed: 37 helper tests and 11 mocked Kubernetes
Terraform plans. Regressions include one/two-connection pools, simultaneous prepares
and refreshes, stale confirmations, immutable history, migration backfill/ambiguity,
blocked-proposal recovery without rematching, import rejection before paid work,
and the documented cross-turn free-form distinction. No production import,
rollout, paid model call or real supplier purchase was performed for this feature.
