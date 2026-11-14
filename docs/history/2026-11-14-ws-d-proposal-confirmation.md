# 2026-11-14: proposal, confirmation and receipt (person 3, WS-D)

## Summary
WS-D audited its 24 requirements (CNF-001 to 019, PRP-001 to 005) on develop `8f39b8c`, found that only the internal agent needed a customer confirmation to commit, and then closed the gaps test first on `p3/ws-d` (base develop `17579d8`, tip `b192f85`): every agent role now needs a recorded confirmation (CNF-003/004); saved orders are immutable through migration 008; the workflow half of "a repeated confirmation returns the saved receipt whatever its key" (CNF-011) is in; and 47 new contract tests (45 pass, 2 are strict xfails) cover confirmation binding, revisions, receipts, expiry, lock order, agent login and PR #38's refresh. Two integration dry runs merged the four workstreams on current develop and found the conflicts and cross-branch failures listed below.

## Changes
Branch `p3/ws-d` (not pushed). Commits, oldest first: `c6f91ba` confirmation gate for every agent role (CNF-003, CNF-004; `approval_workflow.py`, `tests/conftest.py` `confirm_terms`, migrated tests); `d82715b` `migrations/008_orders_immutable.sql` and `tests/test_orders_immutable.py` (CNF-017, CNF-020); `e316c06` `tests/test_confirmation_contract.py` and `prior_result(any_key=True)` (CNF-011 workflow half); `359fd2a` `tests/test_proposal_revisions_contract.py`, `tests/test_receipt_and_expiry_contract.py`, `tests/test_refresh_contract.py`; `1d7d383` `tests/test_lock_order_and_login_contract.py` (CNF-005, CNF-003); `f8648c6` real-clock refresh test (CNF-008); `b192f85` PRP-007 as passing tests (owner Q-41: confirming the revision accepts the substitute).
Existing tests edited only where they committed as the retained agent: `test_workflow.py` (6), `test_hardening.py` (2), `test_http.py` (1), `test_workflow_races.py` (3), plus the `confirm_terms` fixture; no assertion weakened.
Branch `p3/ws-d-2` (from `b192f85`, `81d9bcb`): `tests/test_unfinished_cleanup_contract.py` for CNF-021 (schema guard plus a strict xfail). No migration other than 008 was created.
Scratch (never pushed): `p3/integration-dryrun` in `worktrees/p3-integration`; reports `evidence/ws-d/integration-dry-run.md` and `integration-dry-run-2.md`; fix diffs `evidence/ws-d/integration-fix-ws-a-confirm-terms.diff`, `integration-fix-ws-c-agent-integration.diff`.
Evidence: `Assistant/projects/junction/evidence/2026-11-14-audit-ws-d.md`, `evidence/ws-d/verification-package.md`, `evidence/ws-d/cnf-011-conversations-confirm.patch.txt`, `evidence/ws-d/cnf-021-design.md`. Results are local runs, not CI: final `p3/ws-d` suite 595 passed, 2 xfailed, 1 failed (the failure needs `uv`, not installed here).

## Lessons
- The gate only for internal agents left a path with no human: F-CONFIRM-001; keep blocked outcomes as `COMMIT_BLOCKED`: F-CONFIRM-002.
- The revision number, not the fingerprint, binds a confirmation: F-CONFIRM-003.
- Orders are frozen by a row trigger with known limits: F-CONFIRM-005. PR #38's refresh is safe for decisions and receipts: F-CONFIRM-007.
- Upgrade paths work from three starting states, but the new app needs 009 and 010 first: F-CONFIRM-010.
- Unfinished-proposal cleanup is blocked by triggers and foreign keys: F-CONFIRM-011. Test environment traps: F-CONFIRM-012.
- Combining branches: develop #103 removed `RECIPE_PLANNING_ENABLED` while every branch still used it; four failures exist only in combination (009 backfill missing from the migration-review list, a WS-B strict xfail that WS-A's batching turns into an XPASS, an import expectation in `test_in_process_tools.py`, and `Requirements.unsupported` breaking the additive wire shape). Branches must merge latest develop before their PRs.

## Carry forward
- CNF-011 route half: person 1 applies one line in `conversations.confirm` (patch text saved); then remove the strict xfail.
- PRP-002 (return the fingerprint) and T3 (`workflow.confirm_purchase`, one expiry code) wait for person 1.
- CNF-021 (Approved): not built. Owner decided a 30-day default period counted from the current revision's expiry (Q-56) and an append-only `purged_proposals` table (Q-57). Implementation needs migration 012 (not reserved) and the setting in `config.py`; the schema guard, the strict xfail and the design are ready.
- `p3/integration-fix` (fifth PR) carries the cross-branch fixes: the 009 backfill review entry, the SUP-007 xfail mark, the `unsupported` wire shape (with `tests/test_requirements_wire_shape.py`), the migrations README rows, the CNF-021 cleanup contract test, this history and the findings and TEST-GUIDE entries of all four tracks.
- Release note: migrations 009 and 010 must be applied before the new image runs.
