-- Durable queue shared by API and worker; retain every historical turn/message.
ALTER TABLE conversation_turns DROP CONSTRAINT conversation_turns_state_check;
ALTER TABLE conversation_turns ADD CONSTRAINT conversation_turns_state_check
 CHECK (state IN ('queued','running','complete','failed'));
ALTER TABLE conversation_turns ADD COLUMN requested_by text REFERENCES identities(id);
ALTER TABLE conversation_turns ADD COLUMN worker_attempts integer NOT NULL DEFAULT 0;
-- Old interrupted turns have no authenticated submitter recorded. Never guess one.
UPDATE conversation_turns SET state='failed' WHERE state='running';
CREATE INDEX conversation_turns_pending ON conversation_turns(state,lease_until)
 WHERE state IN ('queued','running');
