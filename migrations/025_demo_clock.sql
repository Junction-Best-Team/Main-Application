-- Demo clock (owner Q-112, Q-115, Q-116): a per-buyer simulated-time offset that moves only the
-- derived fulfilment status and the scheduler's dates. Off unless DEMO_CLOCK_ENABLED. Additive: two
-- new tables, no existing row or column changes.
CREATE TABLE demo_clock (
 buyer_id text PRIMARY KEY REFERENCES buyers(id),
 -- forward only, at most 400 days in total (a 365 day schedule plus margin)
 offset_seconds integer NOT NULL DEFAULT 0 CHECK (offset_seconds BETWEEN 0 AND 34560000),
 updated_at timestamptz NOT NULL DEFAULT now()
);

-- Every change is recorded and never altered: who, which buyer, the old and new offsets and the
-- REAL time of the change. The key makes a repeated request apply once.
CREATE TABLE demo_clock_events (
 id bigserial PRIMARY KEY,
 buyer_id text NOT NULL REFERENCES buyers(id),
 actor_id text NOT NULL,
 kind text NOT NULL CHECK (kind IN ('advance','reset')),
 jump_days integer CHECK (jump_days BETWEEN 1 AND 30),
 jump_to text CHECK (jump_to = 'delivery_day'),
 old_offset_seconds integer NOT NULL CHECK (old_offset_seconds BETWEEN 0 AND 34560000),
 new_offset_seconds integer NOT NULL CHECK (new_offset_seconds BETWEEN 0 AND 34560000),
 real_at timestamptz NOT NULL,
 idempotency_key text NOT NULL CHECK (char_length(idempotency_key) BETWEEN 8 AND 120),
 created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE (buyer_id, idempotency_key),
 FOREIGN KEY (actor_id, buyer_id) REFERENCES identities(id, buyer_id),
 CHECK (kind = 'reset' OR ((jump_days IS NOT NULL) <> (jump_to IS NOT NULL)))
);
CREATE TRIGGER immutable_demo_clock_events BEFORE UPDATE OR DELETE ON demo_clock_events
 FOR EACH ROW EXECUTE FUNCTION immutable_record();
CREATE TRIGGER immutable_truncate BEFORE TRUNCATE ON demo_clock_events
 FOR EACH STATEMENT EXECUTE FUNCTION immutable_truncate_guard();
