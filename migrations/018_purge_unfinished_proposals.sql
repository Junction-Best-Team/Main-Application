-- CNF-021: let proposals and approvals that never became orders be removed after a configured
-- period, without weakening the history guards for anything that has an order. Additive: one new
-- table and a replaced guard function on four history tables; no row is changed.
--
-- purged_proposals is the append-only record of every removal (owner Q-57). It has no foreign key
-- so it survives the rows it describes.
CREATE TABLE purged_proposals (
 proposal_id uuid PRIMARY KEY,
 buyer_id text NOT NULL,
 created_at timestamptz NOT NULL,
 last_revision integer NOT NULL,
 last_outcome text NOT NULL,
 last_expires_at timestamptz NOT NULL,
 period_days integer NOT NULL,
 purged_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX purged_proposals_buyer ON purged_proposals(buyer_id, purged_at);
CREATE TRIGGER immutable_purged_proposals BEFORE UPDATE OR DELETE ON purged_proposals
 FOR EACH ROW EXECUTE FUNCTION immutable_record();

-- Same refusal as immutable_record(), except a DELETE is allowed when the transaction set
-- aimo.purge_unfinished = 'on' (done by the purge function) AND the proposal has no order AND a
-- purged_proposals record for it already exists (the purge writes it before it deletes). Any SQL
-- running as the app role can set the flag, so the flag alone proves nothing: with these two
-- conditions every deletion leaves a permanent record, and the no-order test keeps rows of an
-- ordered proposal undeletable whatever the flag says. UPDATE is always refused. (The retention
-- period and the selection live in workflow.purge_unfinished_proposals.)
CREATE FUNCTION immutable_unless_purging() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP = 'DELETE'
  AND current_setting('aimo.purge_unfinished', true) = 'on'
  AND NOT EXISTS (SELECT 1 FROM orders o WHERE o.proposal_id = OLD.proposal_id)
  AND NOT EXISTS (SELECT 1 FROM proposals p WHERE p.id = OLD.proposal_id AND p.order_id IS NOT NULL)
  AND EXISTS (SELECT 1 FROM purged_proposals pp WHERE pp.proposal_id = OLD.proposal_id)
 THEN
  RETURN OLD;
 END IF;
 RAISE EXCEPTION 'immutable history; append a new record instead';
END; $$;

DROP TRIGGER IF EXISTS immutable_revisions ON proposal_revisions;
CREATE TRIGGER immutable_revisions BEFORE UPDATE OR DELETE ON proposal_revisions
 FOR EACH ROW EXECUTE FUNCTION immutable_unless_purging();
DROP TRIGGER IF EXISTS immutable_audit ON audit_events;
CREATE TRIGGER immutable_audit BEFORE UPDATE OR DELETE ON audit_events
 FOR EACH ROW EXECUTE FUNCTION immutable_unless_purging();
DROP TRIGGER IF EXISTS immutable_confirmations ON customer_confirmations;
CREATE TRIGGER immutable_confirmations BEFORE UPDATE OR DELETE ON customer_confirmations
 FOR EACH ROW EXECUTE FUNCTION immutable_unless_purging();
DROP TRIGGER IF EXISTS immutable_meal_authorization_withdrawals ON meal_authorization_withdrawals;
CREATE TRIGGER immutable_meal_authorization_withdrawals
 BEFORE UPDATE OR DELETE ON meal_authorization_withdrawals
 FOR EACH ROW EXECUTE FUNCTION immutable_unless_purging();
