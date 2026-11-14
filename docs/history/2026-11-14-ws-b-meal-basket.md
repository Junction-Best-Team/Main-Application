# 2026-11-14: person 3, WS-B (meal and basket arithmetic)

## Summary
Audited the meal and basket arithmetic against develop (first at 8f39b8c, then PR #38 and the merged 17579d8), built the owner-approved gaps test first, and pinned the rest with contract tests. Built: exact rational deposit pricing (BAS-005), unknown line amounts for an unpriced deposit (PRP-006), numeric shortfall (BAS-008), 1000-line purchase and lookup caps (MEA-013, our half), batch matching of ingredients in one call (MEA-014), unit priority combine and structured mismatch errors (BAS-009, our half), exact per-ingredient shares on each basket line (MEA-005, MEA-009, BAS-002) and the backend refusal of a free-form basket for an unresolved saved dish (MEA-008, backend half). Everything that sits in person 1's or person 2's files is delivered as exact patch text, checked on scratch copies. Full backend suite on the tuned database after merging origin/develop 837dfdf: 771 passed, 18 xfailed (tests/test_sweep.py not run: needs uv).

## Changes
Branch p3/ws-b, built on origin/develop 17579d8 and merged with 837dfdf, 18 local commits (not pushed), tip c06bb23. In order:
- 138e6c1 tests/test_arithmetic_contract.py (BAS-006, MEA-009, PRP-006 total, float guard, BAS-007 strict xfail)
- a295e6b tests/test_draft_contract.py (strict xfails for the Draft requirements)
- ef0422d PRP-006 line fix in src/aimo/purchases.py
- 0ab959f, 128f61c, 5b51246 verification test files: test_recipe_arithmetic.py (MEA-001 to MEA-010), test_basket_contract.py (BAS-001 to BAS-005), test_persistence_contract.py (PER-001, PER-003)
- 52f4435 BAS-005 exact deposit pricing (purchases.py)
- e54c13f, 5311346 MEA-014: tests, then src/aimo/recipe_batch.py and Service.match_ingredients
- 66fda68 BAS-008: QuantityCalculation.shortfall (schemas.py, purchases.py)
- 2c068fb MEA-013 our half: MAX_BASKET_LINES, MAX_LOOKUP_IDS, MAX_MATERIALS = 1000
- 6b8739a BAS-009: catalog.combine_in_priority_unit, UNIT_PRIORITY, per_sales_for (quantity() output unchanged on 2,880 hashed cases)
- 3e8f154 PER-003 read-by-number tests dropped (Q-46), PER-004 append-only tests (Q-47)
- 80f6d56 MEA-008 backend: src/aimo/recipe_guard.py, Service.ensure_saved_plan_resolved
- f25af65 BAS-009 Q-44: src/aimo/basket_errors.py (structured details)
- 5e15493 MEA-005, MEA-009, BAS-002: src/aimo/basket.py, SnapshotLine.contributions, LineRequest.contributions, recipe_batch rejected record
- 196907a merge of origin/develop 837dfdf (no conflicts); c06bb23 recipe planning flag removed from our code and tests (develop #103)
Evidence: Assistant/projects/junction/evidence/ws-b/ (one file per requirement, final-verification-built.md, audits 2026-11-14-audit-ws-b.md and 2026-11-14-audit-ws-b-per.md). Patch requests for others: MEA-012-013-requests.md, MEA-014-requests.md, BAS-009-requests.md, MEA-005-009-requests.md, MEA-008-requests.md.

## Lessons
See findings F-BASKET-001 to F-BASKET-012. In short: Decimal division mispriced a one-third deposit; a failed deposit left a misleading line; the 4-decimal Amount loses most gram quantities when portions do not divide; there is no quantity bound; variable weight blocks in two places; a product in two units could not be prepared; per-ingredient conversion overstates shared packs; the agent loop caps ingredients per turn before the schemas do; the shared Postgres saturates under parallel suites (use port 55433) and uv is missing locally. Subagents wrote five of the test files and three modules; every result was re-run by the session before committing, and a retroactive red check showed the contributions tests fail without the change (MEA-005-009-red-check.txt).

## Carry forward
- Patches for persons 1 and 2 (agent_tools.py, recipes.py, recipe_schemas.py, chat_schemas.py, api.py, agent.py, guardrails.py, frontend types): the strict xfails for MEA-005 (single match rejection, MealPlan.rejected), BAS-002 free-form, BAS-009 end to end, MEA-008 agent layer, MEA-012 and MEA-013 (MealPlan, Recipe, scaled_plan) stay until the patches land; remove each marker in the same change.
- MEA-011 (maximum per portion) deferred, person 2. SUP-007 (lookup batching) WS-A. BAS-007 warn only deferred (ISS-JCT-001). MEA-010 constraint provenance: no code, needs a migration and person 1's persistence.
- PER-004: migration draft as text only until the owner reserves a number (012 and 013 are not reserved).
- Review at merge: my purchases.py hunks (imports, MAX_MATERIALS and exact_money above context(), build_snapshot contributions and shortfall and the deposit loop) overlap WS-C's AgentAuthority import; service.py has two added methods (match_ingredients, ensure_saved_plan_resolved).
- Ask the owner: BAS-009 when the request offers 4 ST + 6 L for a plan needing 10 ST (refused, now with exact details); whether a different title for the same dish should also trigger the MEA-008 refusal.
