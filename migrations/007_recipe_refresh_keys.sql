-- A refreshed proposal can have multiple immutable preparation retry keys.
-- Buyer/agent/key remains the primary key and still enforces idempotency.
ALTER TABLE prepare_requests DROP CONSTRAINT prepare_requests_proposal_id_key;
CREATE INDEX prepare_requests_proposal_id ON prepare_requests(proposal_id);
