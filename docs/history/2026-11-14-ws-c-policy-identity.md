# 2026-11-14: policy, identity and isolation (person 3, WS-C)

## Summary
Audited the policy, identity and isolation requirements on `origin/develop`, then built what the owner decided: a missing approved product list always blocks (POL-004), "allowed" substitutions pass with a recorded reason (POL-006), an unknown total can never be ready (POL-009), the agent's spend authority and the autonomous limit are removed with legacy rows tolerated (POL-013, IDN-002; owner Q-35), a total above every active approver's maximum or no active approver is `needs_resolution` (POL-014; Q-37), and a customer can withdraw a per-meal authorization (POL-010, migration 010). about 410 new tests plus 17 replaced obsolete ones; 22 requirements have a verification file. All results are local runs, not CI.

## Changes
Branch `p3/ws-c`, base `origin/develop` `17579d8`, merged `p3/ws-d` (`b192f85`); commits (not pushed):
- `5a4ff5c` WS-D T1 hunks applied by hand (replaced by the merge).
- `7c4816b` `src/aimo/approval_policy.py`, `schemas.py`, `purchases.py`, `cli.py`: POL-004/006/009/013/014, IDN-002.
- `ad3a382` `migrations/010_meal_authorization_withdrawals.sql`, `src/aimo/meal_authorization.py`, hooks in `approval_workflow.py` and `service.py`: POL-010 and the Q-35 call sites.
- `a66d721`, `6a46f10`, `29553b6`, `a0f9f03` new tests: `test_policy_rules.py`, `test_spend_authority.py`, `test_provisioning.py`, `test_confirm_keeps_policy.py`, `test_isolation.py`, `test_revoked_identity.py`, `test_historical_actors.py`, `test_no_mcp.py`, `test_agent_cannot_purchase.py`, `test_agent_tool_verbs.py`, `test_in_process_tools.py`, `test_additive_migrations.py`, `test_meal_authorization.py`, helper `wsc_support.py`.
- `0d6d8fa` replaced tests that depended on the autonomous limit (`test_conversations`, `test_edges`, `test_evidence`, `test_http`, `test_purchases`, `test_workflow`, `test_workflow_races`).
- `f84f1e4` merge of `p3/ws-d` (one conflict in `tests/test_workflow.py`, WS-C replacements kept); `794ffd3`, `bfc1893`, `0b7d27c` scan fix for migration 008, README / `docs/chat-purchasing.md` / `migrations/README.md`, rename to `test_agent_tool_verbs.py`.
- `82884de` `Requirements.unsupported` and the reason `REQUIREMENT_UNSUPPORTED` (`schemas.py`, `approval_policy.py`, `tests/test_unsupported_requirements.py`): POL-009 unsupported half.
- `3e62092` POL-008 strict xfail in `tests/test_policy_rules.py` (+ ruff format of that file). `8819f36` `tests/test_runtime_truncate.py`: PER-002, the runtime role holds no TRUNCATE.
- `ca6a745` two owner-approved edits to person 2's files (`tests/test_agent_integration.py` expected reason, `scripts/evaluate_guardrails.py` fixture reason; owner page Q-50).
- Not committed (evidence only): `evidence/ws-c/pol-008-design.md`, `per-002-truncate-design.md`.

## Lessons
- Missing scope did not block when substitution was "allowed": F-POLICY-001. Unknown total reliance on the caller: F-POLICY-002.
- Removing a field from an `extra="forbid"` model breaks every stored row; the legacy key needs a before-validator, not a migration: F-POLICY-003.
- `NO_ELIGIBLE_APPROVER` was conditional on an exception: F-POLICY-004.
- The runtime role cannot write policies, so a policy editor needs a grant decision first: F-POLICY-005.
- Per-meal authorization is derived from approvals and confirmations; only the withdrawal is stored: F-POLICY-006.
- Unsupported requirements: F-POLICY-007. Isolation and revocation: F-ISOLATION-001. TRUNCATE gap: F-PERSIST-001. Agent tool surface: F-AGENT-005. `/mcp` ingress: F-SEC-001.
- Mutation checks on a scratch copy of `src/` caught eight deliberate breaks; a first mutation that produced a SQL error instead of a test failure proved nothing and was redone.
- A borrowed virtualenv and a shared Postgres were needed (no `uv` here); parallel suites saturated the shared server, so a tuned disposable container on port 55433 was used from then on.

## Carry forward
- Person 2: told that `ca6a745` edits two of their files (`tests/test_agent_integration.py`, `scripts/evaluate_guardrails.py`); a signal for recipe edits or un-confirmation; the agent must use `requirements.unsupported`; constraint provenance for POL-008 (issues #75, #92; stored as a JSON field on the request record, owner Q-53, no migration; design in `evidence/ws-c/pol-008-design.md`, strict xfail `test_unconfirmed_assumption_never_loosens_hard_limits`).
- Person 1: no browser route for the withdrawal (owner Q-54); regenerate `frontend/openapi.json` and `api-types.ts` (the `Requirements` schema gained `unsupported`); check rendering of `exception`-severity reasons without a pending approval; remove the `/mcp` ingress paths.
- Open: POL-008 enforcement; the TRUNCATE guard (designed, needs migration number 012/013 plus a one-line `SET LOCAL` in `tests/conftest.py` and `tests/ci.sh`; the runtime role itself holds no TRUNCATE); `004_worker_queue.sql` history rewrite decision.
- Deferred by the owner: POL-007 (policy editing, needs a runtime grant), POL-011, POL-012.
- Merge notes: `p3/ws-b` conflicts only in the `purchases.py` import lines; WS-C is last in merge order.
