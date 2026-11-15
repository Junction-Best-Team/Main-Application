# Database migrations

The runner sorts `.sql` files by full filename and records that filename in
`schema_migrations`. Numeric prefixes are an ordering convention, not ledger IDs.
Do not rename applied migrations, delete their ledger rows or remove migration
files during documentation cleanup. The SQL files are the schema inventory.

## Adding a migration

Check the latest `origin/develop`, remote branch tips and open PRs before choosing
a descriptive filename. Coordinate schema and runtime-grant changes with teammates.
Some prefixes are shared by independent migrations; the complete filename must be
unique. Avoid depending on numeric prefixes alone for execution order.

All pending DDL and ledger inserts commit together; a failure rolls the transaction
back. Preserve populated databases and historical policy, recipe, approval and order
records. Migration tests cover ordering, repeated/concurrent runs and upgrades from
older populated schemas.

## Existing compatibility cases

- `011_proposal_revision_ordering.sql` also handles databases that already applied
  the old `008_proposal_revision_ordering.sql`. Existing timestamps and the old
  ledger row remain. Do not rename that row or undo its DDL.
- Both 005 files and both 012 files retain their original full-filename ledger
  entries; prior application cannot be assumed absent.
- History guards protect orders, recipe versions/revisions and purchasing records
  from mutation. Never bypass them to perform a routine upgrade.
- Unfinished-proposal cleanup is the explicit `aimo purge-proposals` operator
  command, using the schema owner's database connection. It defaults to 30 days
  after expiry and preserves orders and referenced history. The runtime role
  cannot update/delete history or insert purge records.

## Applying migrations

For local setup, run `uv run aimo migrate` with the setup role, then seed missing
demo data as described in [README](../README.md). Reapply runtime grants whenever
new schema objects require them; application startup does not migrate or seed.

Routine releases run the [migration/grant Job](../docs/release-migrations.md)
before changing app images. The one-time bootstrap is documented in
[infrastructure](../infra/README.md#initial-setup). Never reset an existing database,
re-import a catalog as a side effect of migration, or assume an image rollback
undoes schema changes.
