-- Additive cutover: historical identities, proposals, approvals and orders are retained.
CREATE TABLE internal_agents (
 buyer_id text PRIMARY KEY REFERENCES buyers(id),
 identity_id text NOT NULL UNIQUE REFERENCES identities(id)
);
-- New internal actors start with zero autonomous authority. Customer authority is
-- still checked by the existing policy/approval engine; migration grants no scope.
INSERT INTO identities(id,buyer_id,role,active,credential_hash,authority)
SELECT 'internal:' || md5(id), id, 'agent', true, '!internal-no-bearer-login',
 '{"currency":"EUR","autonomous_limit":"0"}'::jsonb FROM buyers;
INSERT INTO internal_agents SELECT buyer_id,id FROM identities
 WHERE id LIKE 'internal:%' AND credential_hash='!internal-no-bearer-login';

CREATE TABLE conversations (
 id uuid PRIMARY KEY, buyer_id text NOT NULL REFERENCES buyers(id),
 title text NOT NULL, create_key text NOT NULL, create_hash text NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(buyer_id,create_key)
);
CREATE INDEX conversations_buyer ON conversations(buyer_id,updated_at DESC,id);
CREATE TABLE conversation_turns (
 id uuid PRIMARY KEY, conversation_id uuid NOT NULL REFERENCES conversations(id),
 key text NOT NULL, payload_hash text NOT NULL,
 state text NOT NULL CHECK(state IN ('running','complete','failed')),
 lease_until timestamptz NOT NULL, attempt uuid NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(), UNIQUE(conversation_id,key)
);
CREATE TABLE conversation_messages (
 id bigserial PRIMARY KEY, conversation_id uuid NOT NULL REFERENCES conversations(id),
 turn_id uuid NOT NULL REFERENCES conversation_turns(id),
 role text NOT NULL CHECK(role IN ('user','assistant')), text text NOT NULL,
 meal_plan jsonb, proposal_id uuid REFERENCES proposals(id),
 created_at timestamptz NOT NULL DEFAULT now(), UNIQUE(turn_id,role)
);
CREATE INDEX conversation_messages_order ON conversation_messages(conversation_id,id);
CREATE TABLE customer_confirmations (
 proposal_id uuid NOT NULL, revision integer NOT NULL, fingerprint text NOT NULL,
 actor_id text NOT NULL REFERENCES identities(id), key text NOT NULL,
 buyer_id text NOT NULL REFERENCES buyers(id), created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(proposal_id,revision,actor_id), UNIQUE(buyer_id,key),
 FOREIGN KEY(proposal_id,revision) REFERENCES proposal_revisions
);
CREATE TRIGGER immutable_confirmations BEFORE UPDATE OR DELETE ON customer_confirmations
 FOR EACH ROW EXECUTE FUNCTION immutable_record();
