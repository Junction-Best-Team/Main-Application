# Migration allocation

The runner sorts `.sql` files by full filename and records that filename in
`schema_migrations`. Numeric prefixes are an ordering convention, not ledger IDs.
Do not rename applied migrations or delete their ledger rows.

| Prefix | Owner / purpose |
| --- | --- |
| 001–004 | Existing purchasing and chat schema |
| 005_hosted_search | Merged catalog embedding upgrade |
| 005_recipe_planning | PR #38 recipe storage; retained because prior application is unknown |
| 006–007 | PR #38 recipe/proposal link and refresh retry keys |
| **008–010** | **Person 3**: `008_orders_immutable` (orders become history: no update or delete), `009_product_withdrawn_since` (when a catalog product became withdrawn; nullable column, partial index, backfill from retained generations), `010_meal_authorization_withdrawals` (append-only record of a withdrawn per-meal authorization). Policy edit history is added in 014 |
| **011** | **PR #38** proposal revision ordering |
| **018** | **Person 3**: `018_purge_unfinished_proposals` (CNF-021: append-only `purged_proposals`; the four per-proposal history guards become purge-aware: a DELETE is allowed only under the transaction-local flag `aimo.purge_unfinished` and only for a proposal with no order). An operator command, `aimo purge-proposals`, run by hand with the **schema owner's** `DATABASE_URL` (not scheduled): since owner decision Q-99 the runtime role holds no UPDATE or DELETE on the history tables and cannot insert into `purged_proposals`. Default period 30 days from the current revision's expiry |
| **019** | **Person 3**: `019_history_immutability` (PER-004: UPDATE and DELETE of `recipe_plan_revisions` and `recipe_versions` are refused; PER-002: a statement-level guard refuses TRUNCATE of the history tables unless the transaction sets `aimo.allow_history_truncate = 'on'`) |
| 012_buyer_user_memory | Buyer and user memory (`docs/memory.md`) |
| 012_catalog_import_profile | Catalog sync: `catalog_generations.import_profile` (additive, nullable) |
| 013_catalog_sync_withdrawals | Release integration: source snapshot count and product-ID-only cleanup protection view |
| 014_policy_settings | Buyer policy managers, append-only change attribution and restricted policy save function |
| 015_recipe_images | Optional chat illustrations, durable generation/upload recovery |
| 021_turn_constraints | The customer's structured limits (budget, dietary toggles) stored with the chat turn that carries them (POL-008 producer, owner Q-97). One nullable `jsonb` column on `conversation_turns`; additive |
| 023_chat_draft_cart | Display-only selected ingredients and checked unit prices; attempt-fenced, no confirmation authority |
| 022_chat_activity | Bounded, sanitized worker activity on conversation turns; attempt-fenced updates, no purchasing authority |
| 022_buyer_settings | Narrow signed-in buyer settings save; preserve hidden scope and personal authority |
| **023_scheduled_orders** | **Person 3 (WS-E)**: role `scheduler` and one scheduler identity per buyer, `scheduled_authorizations` (terms immutable, pause and resume allowed), `scheduled_runs` (unique per authorization and date), append-only event logs, `order_request_cancellations`, message role `system`. applies after 018 and 019 (WS-D) |
| 024_message_notice | `conversation_messages.notice`: marks the plain assistant notice stored when a chat turn fails because the model provider fails (owner Q-108). One nullable `text` column; additive |
| 025_demo_clock | The per-buyer demo clock (JNP3-CLK): `demo_clock` (one offset per buyer) and append-only `demo_clock_events` (idempotent jumps and resets). Additive; inert unless `DEMO_CLOCK_ENABLED` is on |
| 026_supplier_datasets | API enhancements: independent versioned reliability/carbon CSV snapshots, product-ID values and atomic active pointers. Operator imports; runtime SELECT only. No purchase/catalog changes |

Before allocating another number, check remote branch tips and open PRs and update
this table with the agreed allocation. Reservations do not create migration files.

PR #38 previously used `008_proposal_revision_ordering.sql` at commit `1e86209`.
It is replaced by `011_proposal_revision_ordering.sql` to release 008 to Person 3.
011 also handles a database that already applied the old 008: existing timestamps
and the old ledger row are preserved. Person 3 must use a distinct descriptive
filename for their 008. No operator should rename ledger rows or undo existing DDL.

Both 005 files and both 012 files retain their original names because prior
application is unknown. The two 012 migrations are independent and use distinct
full-filename ledger entries. Tests cover full-filename
ordering, repeated/concurrent migration runs, populated pre-recipe and pre-link
upgrades, and the old-008-to-011 transition. All pending DDL and ledger inserts
commit together; a failure rolls the transaction back.

## Applying 008 to 011 (checked on scratch schemas, 2026-11-14)

A database at any of these states upgrades cleanly with `migrate`, and a second run skips
everything: only 001 to 003 (the last production deploy); 001 to 007 plus 011 (main), where 008 to
010 then apply later and appear after 011 in the ledger; or one that already ran the old
`008_proposal_revision_ordering.sql` (011 does not replay its backfill). The application code from
this release reads `products.withdrawn_since` (009) and `meal_authorization_withdrawals` (010), so
the migration Job must run before the new images start; there is no app-before-migrate
compatibility.
