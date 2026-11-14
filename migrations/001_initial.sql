CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE IF NOT EXISTS schema_migrations (version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE buyers (
 id text PRIMARY KEY, upstream_customer text NOT NULL, current_policy integer NOT NULL
);
CREATE TABLE policies (
 buyer_id text REFERENCES buyers(id), version integer NOT NULL, rules jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY (buyer_id, version)
);
CREATE TABLE identities (
 id text PRIMARY KEY, buyer_id text NOT NULL REFERENCES buyers(id),
 role text NOT NULL CHECK (role IN ('agent','approver')), active boolean NOT NULL DEFAULT true,
 credential_hash text NOT NULL, authority jsonb NOT NULL
);
CREATE TABLE sessions (
 token_hash text PRIMARY KEY, identity_id text NOT NULL REFERENCES identities(id),
 csrf_hash text NOT NULL, expires_at timestamptz NOT NULL
);
CREATE TABLE login_attempts (key text PRIMARY KEY, attempts integer NOT NULL, window_start timestamptz NOT NULL);
CREATE TABLE catalog_generations (
 id uuid PRIMARY KEY, source text NOT NULL, source_hash text NOT NULL,
 model_key text NOT NULL, product_count integer NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE active_catalog (singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton), generation uuid NOT NULL REFERENCES catalog_generations(id));
CREATE TABLE embedding_cache (
 model_key text NOT NULL, text_hash text NOT NULL, embedding vector(384) NOT NULL,
 PRIMARY KEY(model_key,text_hash)
);
CREATE TABLE products (
 generation uuid NOT NULL REFERENCES catalog_generations(id), id text NOT NULL,
 gtin text, search_text text NOT NULL, facts jsonb NOT NULL, embedding vector(384) NOT NULL,
 search_document tsvector GENERATED ALWAYS AS (
  to_tsvector('simple', search_text) || to_tsvector('finnish', search_text) || to_tsvector('english', search_text)
 ) STORED,
 PRIMARY KEY(generation,id)
);
CREATE INDEX products_fts ON products USING gin(search_document);
CREATE INDEX products_vector ON products USING hnsw(embedding vector_cosine_ops);
CREATE INDEX products_gtin ON products(gtin);
CREATE TABLE proposals (
 id uuid PRIMARY KEY, buyer_id text NOT NULL REFERENCES buyers(id), agent_id text NOT NULL REFERENCES identities(id),
 current_revision integer NOT NULL, order_id uuid, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE proposal_revisions (
 proposal_id uuid REFERENCES proposals(id), revision integer NOT NULL,
 policy_version integer NOT NULL, request jsonb NOT NULL, snapshot jsonb NOT NULL,
 fingerprint text NOT NULL, policy_outcome text NOT NULL, reasons jsonb NOT NULL,
 required_exceptions jsonb NOT NULL, expires_at timestamptz NOT NULL,
 PRIMARY KEY(proposal_id,revision)
);
CREATE TABLE approvals (
 id uuid PRIMARY KEY, proposal_id uuid NOT NULL, revision integer NOT NULL,
 status text NOT NULL CHECK(status IN ('pending','approved','rejected','superseded')),
 actor_id text REFERENCES identities(id), decided_at timestamptz, fingerprint text NOT NULL,
 UNIQUE(proposal_id, revision), FOREIGN KEY(proposal_id,revision) REFERENCES proposal_revisions
);
CREATE INDEX approvals_pending ON approvals(proposal_id) WHERE status='pending';
CREATE TABLE orders (
 id uuid PRIMARY KEY, proposal_id uuid NOT NULL UNIQUE REFERENCES proposals(id),
 buyer_id text NOT NULL REFERENCES buyers(id), revision integer NOT NULL,
 receipt jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE idempotency (
 buyer_id text NOT NULL REFERENCES buyers(id), key text NOT NULL, payload_hash text NOT NULL,
 order_id uuid NOT NULL REFERENCES orders(id), PRIMARY KEY(buyer_id,key)
);
CREATE TABLE audit_events (
 id bigserial PRIMARY KEY, proposal_id uuid NOT NULL REFERENCES proposals(id),
 actor_id text NOT NULL, event text NOT NULL, detail jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE FUNCTION immutable_record() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'immutable history; append a new record instead'; END; $$;
CREATE TRIGGER immutable_revisions BEFORE UPDATE OR DELETE ON proposal_revisions FOR EACH ROW EXECUTE FUNCTION immutable_record();
CREATE TRIGGER immutable_audit BEFORE UPDATE OR DELETE ON audit_events FOR EACH ROW EXECUTE FUNCTION immutable_record();
CREATE TRIGGER immutable_policies BEFORE UPDATE OR DELETE ON policies FOR EACH ROW EXECUTE FUNCTION immutable_record();
