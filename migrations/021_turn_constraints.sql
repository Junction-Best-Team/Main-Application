-- POL-008 producer (owner Q-97): the structured fields a customer sets on a message (a hard
-- budget, the lactose-free and milk-free toggles) are stored with the turn that carries them, so
-- the worker that answers later hands them to the policy engine as trusted constraints.
-- Additive: one nullable column, no default, no data change. It is server-only: no API response
-- model has it. The idempotency hash of the turn covers it.
ALTER TABLE conversation_turns ADD COLUMN constraints jsonb;
