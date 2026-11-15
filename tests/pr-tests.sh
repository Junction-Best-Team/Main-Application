#!/usr/bin/env bash
# The hackathon PR gate: core app regressions, not the exhaustive edge-case suite.
set -euo pipefail
cd "$(dirname "$0")/.."
case "${1:-}" in
  --full) exec .venv/bin/pytest -q --durations=10 ;;
  '') ;;
  *) echo 'Usage: tests/pr-tests.sh [--full]' >&2; exit 2 ;;
esac
exec .venv/bin/pytest -q -x --durations=5 \
  tests/test_http.py \
  tests/test_conversations.py \
  tests/test_worker.py \
  tests/test_agent_integration.py \
  tests/test_request_brief.py \
  tests/test_agent.py::test_request_brief_gets_one_correction_before_asking_customer \
  tests/test_request_journey.py::test_repeated_summary_refusal_finishes_with_clarification_and_preserves_history \
  tests/test_guardrails_integration.py::test_enforced_guard_turn_still_needs_exact_customer_confirmation \
  tests/test_agent_parallel.py \
  tests/test_google_providers.py \
  tests/test_agent.py::test_openai_compatible_large_read_batch_keeps_every_call \
  tests/test_agent_recipe_planning.py \
  tests/test_agent_recovery_integration.py \
  tests/test_request_brief.py \
  tests/test_request_journey.py \
  tests/test_supplier_metrics.py \
  tests/test_isolation.py \
  tests/test_migrations.py \
  tests/test_runtime_permissions.py \
  tests/test_scheduler_flow.py \
  tests/test_readiness_migrations.py::test_a_fully_migrated_database_is_ready \
  tests/test_readiness_migrations.py::test_every_packaged_migration_from_008_has_a_probe_manifest_entry \
  tests/test_confirmation_contract.py::test_confirmation_never_authorizes_a_later_revision \
  tests/test_confirmation_contract.py::test_concurrent_confirmations_with_one_key_create_one_order \
  tests/test_agent_cannot_purchase.py::test_registry_exposes_only_read_and_prepare_operations \
  tests/test_workflow.py::test_four_outcomes_and_hard_requirements \
  tests/test_chat_activity.py::test_terminal_error_code_remains_an_interruption_after_sanitization \
  tests/test_agent_stop_control.py::test_revising_a_plan_does_not_reset_or_shrink_its_search_budget \
  tests/test_observability.py \
  tests/test_provider_diagnostics.py
