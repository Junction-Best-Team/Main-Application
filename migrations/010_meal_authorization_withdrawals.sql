-- JNP3-POL-010: append-only record that a customer's per-meal authorization was withdrawn.
-- A per-meal authorization is the customer's approval of one proposal revision (an approved
-- approvals row or a customer_confirmations row); nothing is stored for the grant itself.
-- A withdrawal is terminal for the proposal: a changed recipe needs a fresh proposal.
-- Additive only: no existing table is altered and no history is rewritten.
CREATE TABLE meal_authorization_withdrawals (
 proposal_id uuid PRIMARY KEY REFERENCES proposals(id),
 buyer_id text NOT NULL REFERENCES buyers(id),
 plan_id uuid REFERENCES recipe_plans(id),
 revision integer NOT NULL,
 withdrawn_by text NOT NULL REFERENCES identities(id),
 reason text NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX meal_authorization_withdrawals_buyer ON meal_authorization_withdrawals(buyer_id);
CREATE TRIGGER immutable_meal_authorization_withdrawals
 BEFORE UPDATE OR DELETE ON meal_authorization_withdrawals
 FOR EACH ROW EXECUTE FUNCTION immutable_record();
