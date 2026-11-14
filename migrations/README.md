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
| **008–010** | **Reserved for Person 3**: policy edit history, per-meal authorization/revocation, spare |
| **011** | **PR #38** proposal revision ordering |

Before allocating another number, check remote branch tips and open PRs and update
this table with the agreed allocation. Reservations do not create migration files.

PR #38 previously used `008_proposal_revision_ordering.sql` at commit `1e86209`.
It is replaced by `011_proposal_revision_ordering.sql` to release 008 to Person 3.
011 also handles a database that already applied the old 008: existing timestamps
and the old ledger row are preserved. Person 3 must use a distinct descriptive
filename for their 008. No operator should rename ledger rows or undo existing DDL.

Both 005 files are intentional compatibility names. Tests cover full-filename
ordering, repeated/concurrent migration runs, populated pre-recipe and pre-link
upgrades, and the old-008-to-011 transition. All pending DDL and ledger inserts
commit together; a failure rolls the transaction back.
