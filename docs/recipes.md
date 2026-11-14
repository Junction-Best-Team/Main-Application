# Recipe planning

Opt-in recipe discovery and purchasing inside the existing chat worker. It uses the
existing Service, PostgreSQL/pgvector and purchasing/confirmation controls. All
orders remain mock. The merged release pipeline applies schema/grants before rollout;
recipe import and feature activation remain explicit operator actions.

## Enablement and import

1. After the migration credential bootstrap, the release pipeline applies
   the recipe migrations (`005_recipe_planning.sql`, `006_recipe_proposal_link.sql`,
   `007_recipe_refresh_keys.sql`) and runtime grants before app rollout.
   For manual local setup use `aimo migrate` with the migration/setup role.
   Schema migration performs no download, seed, embedding or dataset import.
2. With the worker image/code and the same embedding profile as serving, run the
   explicit importer. For Qwen3 Embedding 8B + Reranker 8B, use the configured
   OpenRouter provider merged in PR #34. This feature reuses that provider;
   it does not add another credential, model service or ingestion daemon.
3. Add reviewed recipe-form/quantity overrides and matching product evidence for
   recipes intended for purchasing. Discovery alone does not establish readiness
   for an executable basket.
4. Set `RECIPE_PLANNING_ENABLED=true` for local/Compose worker execution, or set
   Terraform `recipe_planning_enabled=true` for the shared ConfigMap, and restart
   the worker through the authorized rollout. Leave the flag
   false until import succeeds. Enabled recipe tools report `RECIPES_NOT_READY` or
   `RECIPE_MODEL_MISMATCH` if the corpus/profile is unavailable. No invented fallback.

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
unresolved. Nonterminating or >4-decimal scaled totals are not silently rounded.
All source ingredients are required, including salt and pantry items. There is no
pantry exemption, customer quantity-resolution UI, AI recipe generation or arbitrary
recipe editing in this initial implementation.

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
Variable/unknown-weight products remain blocked in the fixed-quantity MVP.

`piece_per_sales` is the reviewed ingredient yield per purchasable sales unit, e.g.
30 whole eggs per tray. Do not equate yolks with whole eggs without evidence.
The backend preserves ingredient count through purchasing conversion so rounding
excess still triggers overbuy policy. Every prepare and commit revalidation reads
current product suitability and matching count evidence; it never trusts model-authored
pack counts. Revoked suitability blocks confirmation.

## Agent and persistence

Tools: `search_recipes`, `get_recipe`, `scale_recipe`, `get_recipe_plan`,
`match_ingredient`, plus the existing product discovery and purchasing tools.

Scaling stores a buyer/agent-scoped plan and all source ingredients. One server
turn fixes one recipe version/portion count; repeat scaling returns the saved plan.
Matching requires inspected product facts, creates a new immutable plan revision,
and preserves unresolved ingredients with reasons. Before preparation the Service
requires exact aggregate quantities for every ingredient, the current plan revision
and unchanged catalog facts. A selected saved recipe cannot be replaced with a
free-form `publish_meal_plan` or prepared without its reference. Enabling recipe
tools is additive: direct product requests retain the ordinary publish/prepare
workflow without a recipe reference.

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
expires, is rejected, is denied/needs resolution, or requires policy/authority
refresh, a new customer turn may reload the same plan and refresh commercial terms.
This appends a revision to the **same proposal**, preserving matched ingredients.
Old revisions/decisions stay in history; approval/confirmation is required again.
A rejection is never retried automatically. Concurrent refreshes fence the prior
proposal revision so only one can append; failed persistence rolls everything back.
Recipe/product changes still need a new plan and matching evidence. Unprepared
plans remain unlocked after a failed first preparation.

Migration 006 adds a unique plan-to-proposal link and backfills old prepared plans;
it fails if legacy history ambiguously contains multiple proposals for one plan.
Migration 007 allows multiple preparation retry keys to reference one proposal;
the buyer/agent/key primary key and payload conflict checks remain unchanged.
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
462 backend tests, Python lint, TypeScript/production build, four focused browser
flows, all 10 API sweep checks and the combined 95% coverage gate passed (95.21%).
Earlier infrastructure checks passed: 37 helper tests and 11 mocked Kubernetes
Terraform plans. Regressions include one/two-connection pools, simultaneous prepares
and refreshes, stale confirmations, immutable history, migration backfill/ambiguity,
blocked-proposal recovery without rematching, import rejection before paid work,
and the documented cross-turn free-form distinction. No production import,
rollout, paid model call or real supplier purchase was performed for this feature.
