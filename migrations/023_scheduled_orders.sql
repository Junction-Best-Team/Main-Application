-- WS-E scheduled (standing) re-orders. Additive. Every order it places is a MOCK order.
-- Number 023: the next free one after WS-D's 018 and 019, Otto's 020_chat_attachments, 021_turn_constraints and 022_buyer_settings.

-- 1. A separate scheduler identity per buyer: no login, no model, no authority.
ALTER TABLE identities DROP CONSTRAINT identities_role_check;
ALTER TABLE identities ADD CONSTRAINT identities_role_check
 CHECK (role IN ('agent','approver','scheduler'));
INSERT INTO identities(id,buyer_id,role,active,credential_hash,authority)
SELECT 'scheduler:' || md5(id), id, 'scheduler', true, '!scheduler-no-login', '{}'::jsonb FROM buyers
ON CONFLICT DO NOTHING;
CREATE TABLE scheduler_identities (
 buyer_id text PRIMARY KEY REFERENCES buyers(id),
 identity_id text NOT NULL UNIQUE REFERENCES identities(id)
);
INSERT INTO scheduler_identities SELECT buyer_id,id FROM identities WHERE role='scheduler'
ON CONFLICT DO NOTHING;

-- Composite keys (as migration 012 did for identities and conversations) let the scheduler tables
-- prove that every row they point at belongs to the same buyer.
ALTER TABLE orders ADD CONSTRAINT orders_id_buyer UNIQUE (id, buyer_id);
ALTER TABLE proposals ADD CONSTRAINT proposals_id_buyer UNIQUE (id, buyer_id);

-- 2. The customer's standing authorization. Terms never change; only the status moves.
--    line_rules: per product_id {"accepted_substitutes": [ids], "price_range_pct": "5"} (CNF-036, POL-012).
CREATE TABLE scheduled_authorizations (
 id uuid PRIMARY KEY,
 buyer_id text NOT NULL REFERENCES buyers(id),
 created_by text NOT NULL,
 source_order_id uuid NOT NULL,
 supersedes_id uuid,
 create_key text NOT NULL,
 create_hash text NOT NULL,
 title text,
 request jsonb NOT NULL,
 line_rules jsonb NOT NULL DEFAULT '{}'::jsonb,
 agreed_lines jsonb NOT NULL,
 terms_fingerprint text NOT NULL,
 currency text NOT NULL,
 agreed_gross_total numeric(14,2) NOT NULL CHECK (agreed_gross_total > 0),
 price_ceiling_gross numeric(14,2) NOT NULL,
 delivery_offset_days integer NOT NULL CHECK (delivery_offset_days BETWEEN 1 AND 60),
 recurrence jsonb NOT NULL,
 first_run_date date NOT NULL,
 valid_until date NOT NULL,
 status text NOT NULL DEFAULT 'active'
  CHECK (status IN ('active','paused','stopped','cancelled','expired','superseded')),
 stop_reason text,
 next_run_date date,
 paused_at timestamptz,
 created_at timestamptz NOT NULL DEFAULT now(),
 updated_at timestamptz NOT NULL DEFAULT now(),
 CONSTRAINT sched_auth_create_key UNIQUE (buyer_id, create_key),
 CONSTRAINT sched_auth_title CHECK (title IS NULL OR char_length(title) BETWEEN 1 AND 80),
 CONSTRAINT sched_auth_ceiling CHECK (price_ceiling_gross >= agreed_gross_total),
 CONSTRAINT sched_auth_one_year CHECK (valid_until <= first_run_date + 365),
 CONSTRAINT sched_auth_stop_reason CHECK (status <> 'stopped' OR stop_reason IS NOT NULL),
 CONSTRAINT sched_auth_paused_at CHECK ((status = 'paused') = (paused_at IS NOT NULL)),
 CONSTRAINT sched_auth_window CHECK (valid_until >= first_run_date),
 CONSTRAINT sched_auth_next_run CHECK (
  next_run_date IS NULL OR (next_run_date >= first_run_date AND next_run_date <= valid_until)),
 CONSTRAINT sched_auth_id_buyer UNIQUE (id, buyer_id),
 FOREIGN KEY (created_by, buyer_id) REFERENCES identities(id, buyer_id),
 FOREIGN KEY (source_order_id, buyer_id) REFERENCES orders(id, buyer_id),
 FOREIGN KEY (supersedes_id, buyer_id) REFERENCES scheduled_authorizations(id, buyer_id)
);
CREATE INDEX sched_auth_due ON scheduled_authorizations(next_run_date)
 WHERE status IN ('active','paused');
CREATE INDEX sched_auth_buyer ON scheduled_authorizations(buyer_id, created_at DESC);
-- Active <-> paused may repeat (CNF-037); a stopped one can only be cancelled by the customer
-- (CNF-027); any other status is final. Terms never change.
CREATE FUNCTION scheduled_authorization_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'immutable history; append a new record instead'; END IF;
 IF OLD.status NOT IN ('active','paused')
    AND NOT (OLD.status = 'stopped' AND NEW.status = 'cancelled') THEN
  RAISE EXCEPTION 'a finished authorization never changes; create a new one';
 END IF;
 IF (NEW.id, NEW.buyer_id, NEW.created_by, NEW.source_order_id, NEW.supersedes_id,
     NEW.create_key, NEW.create_hash, NEW.title, NEW.request, NEW.line_rules, NEW.agreed_lines,
     NEW.terms_fingerprint, NEW.currency, NEW.agreed_gross_total, NEW.price_ceiling_gross,
     NEW.delivery_offset_days, NEW.recurrence, NEW.first_run_date, NEW.valid_until, NEW.created_at)
    IS DISTINCT FROM
    (OLD.id, OLD.buyer_id, OLD.created_by, OLD.source_order_id, OLD.supersedes_id,
     OLD.create_key, OLD.create_hash, OLD.title, OLD.request, OLD.line_rules, OLD.agreed_lines,
     OLD.terms_fingerprint, OLD.currency, OLD.agreed_gross_total, OLD.price_ceiling_gross,
     OLD.delivery_offset_days, OLD.recurrence, OLD.first_run_date, OLD.valid_until, OLD.created_at) THEN
  RAISE EXCEPTION 'authorized terms are immutable; create a new authorization';
 END IF;
 RETURN NEW;
END; $$;
CREATE TRIGGER sched_auth_guard BEFORE UPDATE OR DELETE ON scheduled_authorizations
 FOR EACH ROW EXECUTE FUNCTION scheduled_authorization_guard();
-- Only a customer creates a standing order, and a buyer never holds more than 20 open ones (owner Q-87).
CREATE FUNCTION scheduled_authorization_insert_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NOT EXISTS (SELECT 1 FROM identities
                WHERE id = NEW.created_by AND buyer_id = NEW.buyer_id AND role = 'approver') THEN
  RAISE EXCEPTION 'only a customer can create a standing order';
 END IF;
 IF NEW.status IN ('active','paused') AND
    (SELECT count(*) FROM scheduled_authorizations
     WHERE buyer_id = NEW.buyer_id AND status IN ('active','paused')) >= 20 THEN
  RAISE EXCEPTION 'a buyer holds at most 20 open standing orders';
 END IF;
 RETURN NEW;
END; $$;
CREATE TRIGGER sched_auth_insert_guard BEFORE INSERT ON scheduled_authorizations
 FOR EACH ROW EXECUTE FUNCTION scheduled_authorization_insert_guard();
CREATE TABLE scheduled_authorization_events (
 id bigserial PRIMARY KEY,
 authorization_id uuid NOT NULL REFERENCES scheduled_authorizations(id),
 actor_id text NOT NULL,
 event text NOT NULL,
 detail jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX sched_auth_events ON scheduled_authorization_events(authorization_id, id);
CREATE TRIGGER immutable_scheduled_authorization_events
 BEFORE UPDATE OR DELETE ON scheduled_authorization_events
 FOR EACH ROW EXECUTE FUNCTION immutable_record();

-- 3. One row per authorization per scheduled date: the unique key is the idempotency of CNF-025.
--    skipped = the date fell in a pause (CNF-037): no order, no chat, no disruption.
--    substitutions: [{original, substitute, original_gross, substitute_gross}] used by the run.
CREATE TABLE scheduled_runs (
 id uuid PRIMARY KEY,
 authorization_id uuid NOT NULL REFERENCES scheduled_authorizations(id),
 buyer_id text NOT NULL REFERENCES buyers(id),
 scheduled_date date NOT NULL,
 delivery_date date NOT NULL,
 status text NOT NULL DEFAULT 'due'
  CHECK (status IN ('due','prepared','committed','disrupted','skipped')),
 attempts integer NOT NULL DEFAULT 0,
 lease_until timestamptz,
 proposal_id uuid UNIQUE,
 order_id uuid UNIQUE,
 conversation_id uuid UNIQUE,
 reason_code text,
 reason jsonb,
 substitutions jsonb NOT NULL DEFAULT '[]'::jsonb,
 created_at timestamptz NOT NULL DEFAULT now(),
 updated_at timestamptz NOT NULL DEFAULT now(),
 CONSTRAINT scheduled_runs_once UNIQUE (authorization_id, scheduled_date),
 CONSTRAINT scheduled_runs_reason CHECK (
  status NOT IN ('disrupted','skipped') OR reason_code IS NOT NULL),
 CONSTRAINT scheduled_runs_committed CHECK (status <> 'committed' OR order_id IS NOT NULL),
 CONSTRAINT scheduled_runs_prepared CHECK (status <> 'prepared' OR proposal_id IS NOT NULL),
 CONSTRAINT scheduled_runs_attempts CHECK (attempts >= 0),
 CONSTRAINT scheduled_runs_id_buyer UNIQUE (id, buyer_id),
 FOREIGN KEY (authorization_id, buyer_id) REFERENCES scheduled_authorizations(id, buyer_id),
 FOREIGN KEY (proposal_id, buyer_id) REFERENCES proposals(id, buyer_id),
 FOREIGN KEY (order_id, buyer_id) REFERENCES orders(id, buyer_id),
 FOREIGN KEY (conversation_id, buyer_id) REFERENCES conversations(id, buyer_id)
);
CREATE INDEX scheduled_runs_claim ON scheduled_runs(lease_until) WHERE status IN ('due','prepared');
CREATE INDEX scheduled_runs_buyer ON scheduled_runs(buyer_id, scheduled_date DESC);
-- A run is the record that a date was handled (the idempotency of CNF-025): it is never deleted, its
-- identity never moves, a handled run never changes (only a disrupted one may receive its chat, once),
-- and an order of a run belongs to the proposal of that run.
CREATE FUNCTION scheduled_run_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'immutable history; append a new record instead'; END IF;
 IF (NEW.id, NEW.authorization_id, NEW.buyer_id, NEW.scheduled_date, NEW.delivery_date, NEW.created_at)
    IS DISTINCT FROM
    (OLD.id, OLD.authorization_id, OLD.buyer_id, OLD.scheduled_date, OLD.delivery_date, OLD.created_at) THEN
  RAISE EXCEPTION 'a run keeps its authorization, buyer and dates';
 END IF;
 IF OLD.status IN ('committed','disrupted','skipped') THEN
  IF (NEW.status, NEW.order_id, NEW.proposal_id, NEW.attempts, NEW.reason_code, NEW.reason,
      NEW.substitutions)
     IS DISTINCT FROM
     (OLD.status, OLD.order_id, OLD.proposal_id, OLD.attempts, OLD.reason_code, OLD.reason,
      OLD.substitutions)
     OR (NEW.conversation_id IS DISTINCT FROM OLD.conversation_id
         AND (OLD.conversation_id IS NOT NULL OR OLD.status <> 'disrupted')) THEN
   RAISE EXCEPTION 'a handled run never changes';
  END IF;
 END IF;
 IF NEW.order_id IS NOT NULL AND NEW.proposal_id IS NOT NULL
    AND NOT EXISTS (SELECT 1 FROM orders WHERE id = NEW.order_id AND proposal_id = NEW.proposal_id) THEN
  RAISE EXCEPTION 'the order of a run must belong to the proposal of that run';
 END IF;
 RETURN NEW;
END; $$;
CREATE TRIGGER scheduled_run_guard BEFORE UPDATE OR DELETE ON scheduled_runs
 FOR EACH ROW EXECUTE FUNCTION scheduled_run_guard();
CREATE FUNCTION scheduled_run_order_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.order_id IS NOT NULL AND NEW.proposal_id IS NOT NULL
    AND NOT EXISTS (SELECT 1 FROM orders WHERE id = NEW.order_id AND proposal_id = NEW.proposal_id) THEN
  RAISE EXCEPTION 'the order of a run must belong to the proposal of that run';
 END IF;
 RETURN NEW;
END; $$;
CREATE TRIGGER scheduled_run_order BEFORE INSERT ON scheduled_runs
 FOR EACH ROW EXECUTE FUNCTION scheduled_run_order_guard();
CREATE TABLE scheduled_run_events (
 id bigserial PRIMARY KEY,
 run_id uuid NOT NULL REFERENCES scheduled_runs(id),
 actor_id text NOT NULL,
 event text NOT NULL,
 detail jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX scheduled_run_events_run ON scheduled_run_events(run_id, id);
CREATE TRIGGER immutable_scheduled_run_events BEFORE UPDATE OR DELETE ON scheduled_run_events
 FOR EACH ROW EXECUTE FUNCTION immutable_record();

-- 4. "Cancelled" is recorded for an order REQUEST (a proposal); orders stay immutable (CNF-020).
CREATE FUNCTION cancellation_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF EXISTS (SELECT 1 FROM orders WHERE proposal_id = NEW.proposal_id) THEN
  RAISE EXCEPTION 'a placed order cannot be cancelled';
 END IF;
 RETURN NEW;
END; $$;
CREATE TABLE order_request_cancellations (
 proposal_id uuid PRIMARY KEY,
 buyer_id text NOT NULL REFERENCES buyers(id),
 reason text NOT NULL
  CHECK (reason IN ('run_disrupted','run_retry','customer_revised','customer_cancelled')),
 run_id uuid,
 cancelled_by text NOT NULL REFERENCES identities(id),
 created_at timestamptz NOT NULL DEFAULT now(),
 FOREIGN KEY (proposal_id, buyer_id) REFERENCES proposals(id, buyer_id),
 FOREIGN KEY (run_id, buyer_id) REFERENCES scheduled_runs(id, buyer_id)
);
CREATE INDEX order_request_cancellations_buyer ON order_request_cancellations(buyer_id, created_at DESC);
CREATE TRIGGER cancellation_no_order BEFORE INSERT ON order_request_cancellations
 FOR EACH ROW EXECUTE FUNCTION cancellation_guard();
CREATE TRIGGER immutable_order_request_cancellations
 BEFORE UPDATE OR DELETE ON order_request_cancellations
 FOR EACH ROW EXECUTE FUNCTION immutable_record();

-- 5. The system-authored first message of a disrupted run's chat.
ALTER TABLE conversation_messages DROP CONSTRAINT conversation_messages_role_check;
ALTER TABLE conversation_messages ADD CONSTRAINT conversation_messages_role_check
 CHECK (role IN ('user','assistant','system'));

-- 6. History cannot be erased by TRUNCATE either, unless the transaction says a reset is deliberate
--    (the same flag WS-D's immutable_truncate_guard uses: aimo.allow_history_truncate = 'on').
CREATE FUNCTION scheduler_truncate_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF current_setting('aimo.allow_history_truncate', true) IS DISTINCT FROM 'on' THEN
  RAISE EXCEPTION 'immutable history; erasing it needs aimo.allow_history_truncate = on';
 END IF;
 RETURN NULL;
END; $$;
CREATE TRIGGER scheduler_truncate BEFORE TRUNCATE ON scheduled_authorizations
 FOR EACH STATEMENT EXECUTE FUNCTION scheduler_truncate_guard();
CREATE TRIGGER scheduler_truncate BEFORE TRUNCATE ON scheduled_runs
 FOR EACH STATEMENT EXECUTE FUNCTION scheduler_truncate_guard();
CREATE TRIGGER scheduler_truncate BEFORE TRUNCATE ON scheduled_run_events
 FOR EACH STATEMENT EXECUTE FUNCTION scheduler_truncate_guard();
CREATE TRIGGER scheduler_truncate BEFORE TRUNCATE ON scheduled_authorization_events
 FOR EACH STATEMENT EXECUTE FUNCTION scheduler_truncate_guard();
CREATE TRIGGER scheduler_truncate BEFORE TRUNCATE ON order_request_cancellations
 FOR EACH STATEMENT EXECUTE FUNCTION scheduler_truncate_guard();
