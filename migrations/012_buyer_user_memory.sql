-- Explicitly saved buyer-shared and personal assistant memory (docs/memory.md).
-- Additive only: no existing row changes. 008-010 stay reserved for Person 3.
-- Composite keys let memory rows prove that every referenced identity and
-- conversation belongs to the same buyer.
ALTER TABLE identities ADD CONSTRAINT identities_id_buyer UNIQUE (id, buyer_id);
ALTER TABLE conversations ADD CONSTRAINT conversations_id_buyer UNIQUE (id, buyer_id);
ALTER TABLE conversation_messages
 ADD CONSTRAINT conversation_messages_id_conversation UNIQUE (id, conversation_id);
-- requested_by is the latest executor: a colleague's retry of a failed turn replaces it.
-- submitted_by is the message author and never changes. Existing turns stay NULL; the
-- migration never guesses an author, and memory is unavailable for such turns.
ALTER TABLE conversation_turns ADD COLUMN submitted_by text REFERENCES identities(id);

CREATE TABLE memories (
 id uuid PRIMARY KEY,
 buyer_id text NOT NULL REFERENCES buyers(id),
 scope text NOT NULL CHECK (scope IN ('buyer','user')),
 owner_id text,
 kind text NOT NULL CHECK (kind IN ('default','preference','instruction')),
 key text NOT NULL CHECK (
  key ~ '^(default|preference|instruction)\.[a-z0-9_]{1,40}(\.[a-z0-9_]{1,40})?$'
  AND split_part(key, '.', 1) = kind
 ),
 value jsonb NOT NULL CHECK (jsonb_typeof(value) = 'object' AND octet_length(value::text) <= 1024),
 description text CHECK (char_length(description) BETWEEN 1 AND 200),
 revision integer NOT NULL DEFAULT 1 CHECK (revision >= 1),
 created_at timestamptz NOT NULL DEFAULT now(),
 updated_at timestamptz NOT NULL DEFAULT now(),
 created_by text NOT NULL,
 updated_by text NOT NULL,
 source_conversation_id uuid,
 source_message_id bigint,
 search tsvector GENERATED ALWAYS AS (
  to_tsvector('simple', replace(key, '.', ' ') || ' ' || coalesce(description, '') || ' ' || value::text)
 ) STORED,
 CONSTRAINT memories_owner_scope CHECK ((scope = 'user') = (owner_id IS NOT NULL)),
 CONSTRAINT memories_source_pair CHECK ((source_conversation_id IS NULL) = (source_message_id IS NULL)),
 FOREIGN KEY (owner_id, buyer_id) REFERENCES identities(id, buyer_id),
 FOREIGN KEY (created_by, buyer_id) REFERENCES identities(id, buyer_id),
 FOREIGN KEY (updated_by, buyer_id) REFERENCES identities(id, buyer_id),
 FOREIGN KEY (source_conversation_id, buyer_id) REFERENCES conversations(id, buyer_id),
 FOREIGN KEY (source_message_id, source_conversation_id)
  REFERENCES conversation_messages(id, conversation_id)
);
-- One item per key and owner: a shared buyer key, or a key per person within the buyer.
CREATE UNIQUE INDEX memories_buyer_key ON memories(buyer_id, key) WHERE scope = 'buyer';
CREATE UNIQUE INDEX memories_user_key ON memories(buyer_id, owner_id, key) WHERE scope = 'user';
CREATE INDEX memories_search ON memories USING gin(search);

-- Durable idempotency for memory writes. Rows hold minimal metadata only: once a
-- memory is forgotten its save/update request hashes are cleared, so no copy or
-- fingerprint of the deleted content remains. Chat keys derive from the trusted turn.
CREATE TABLE memory_mutations (
 buyer_id text NOT NULL REFERENCES buyers(id),
 actor_id text NOT NULL,
 key text NOT NULL CHECK (char_length(key) BETWEEN 8 AND 200),
 request_hash text,
 action text NOT NULL CHECK (action IN ('save','update','delete')),
 outcome text NOT NULL CHECK (outcome IN ('created','updated','unchanged','deleted')),
 memory_id uuid NOT NULL,
 result_revision integer NOT NULL,
 turn_id uuid REFERENCES conversation_turns(id),
 created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY (buyer_id, actor_id, key),
 FOREIGN KEY (actor_id, buyer_id) REFERENCES identities(id, buyer_id)
);
CREATE INDEX memory_mutations_memory ON memory_mutations(memory_id);
