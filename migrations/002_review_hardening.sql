-- Preparation retries share one proposal across all replicas. Existing proposals
-- remain readable; only new prepare calls require a separate idempotency key.
CREATE TABLE prepare_requests (
 buyer_id text NOT NULL REFERENCES buyers(id),
 agent_id text NOT NULL REFERENCES identities(id),
 key text NOT NULL, payload_hash text NOT NULL,
 proposal_id uuid NOT NULL UNIQUE REFERENCES proposals(id),
 PRIMARY KEY(buyer_id,agent_id,key)
);
CREATE INDEX login_attempts_expiry ON login_attempts(window_start);
CREATE INDEX sessions_expiry ON sessions(expires_at);
CREATE INDEX audit_events_proposal ON audit_events(proposal_id,id);
