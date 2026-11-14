-- PER-004: a recipe plan revision and a recipe version are history too. Block every UPDATE and
-- DELETE with the same guard as the other history tables (immutable_record(), 001). Additive: two
-- new triggers; no row, column or constraint changes. Nothing in the application updates or
-- deletes these tables (plan revisions are only appended, recipe versions only inserted with
-- ON CONFLICT DO NOTHING), so existing behaviour is unchanged.
CREATE TRIGGER immutable_recipe_plan_revisions BEFORE UPDATE OR DELETE ON recipe_plan_revisions
 FOR EACH ROW EXECUTE FUNCTION immutable_record();
CREATE TRIGGER immutable_recipe_versions BEFORE UPDATE OR DELETE ON recipe_versions
 FOR EACH ROW EXECUTE FUNCTION immutable_record();

-- PER-002: immutable_record() is a row trigger and PostgreSQL does not fire row triggers for
-- TRUNCATE, so the schema owner could erase history that cannot be UPDATEd or DELETEd. This adds a
-- statement-level BEFORE TRUNCATE guard to the history tables. It refuses unless the session set
-- the transaction-local flag `aimo.allow_history_truncate = 'on'` (a deliberate reset such as the
-- test fixtures, or a development reset; never put the flag in a role or database default).
-- Additive, no row changes. The runtime role never held TRUNCATE (permissions.py also revokes it).
CREATE FUNCTION immutable_truncate_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF current_setting('aimo.allow_history_truncate', true) IS DISTINCT FROM 'on' THEN
  RAISE EXCEPTION 'immutable history; erasing it needs aimo.allow_history_truncate = on';
 END IF;
 RETURN NULL;
END; $$;

CREATE TRIGGER immutable_truncate BEFORE TRUNCATE ON proposal_revisions
 FOR EACH STATEMENT EXECUTE FUNCTION immutable_truncate_guard();
CREATE TRIGGER immutable_truncate BEFORE TRUNCATE ON audit_events
 FOR EACH STATEMENT EXECUTE FUNCTION immutable_truncate_guard();
CREATE TRIGGER immutable_truncate BEFORE TRUNCATE ON policies
 FOR EACH STATEMENT EXECUTE FUNCTION immutable_truncate_guard();
CREATE TRIGGER immutable_truncate BEFORE TRUNCATE ON customer_confirmations
 FOR EACH STATEMENT EXECUTE FUNCTION immutable_truncate_guard();
CREATE TRIGGER immutable_truncate BEFORE TRUNCATE ON orders
 FOR EACH STATEMENT EXECUTE FUNCTION immutable_truncate_guard();
CREATE TRIGGER immutable_truncate BEFORE TRUNCATE ON meal_authorization_withdrawals
 FOR EACH STATEMENT EXECUTE FUNCTION immutable_truncate_guard();
CREATE TRIGGER immutable_truncate BEFORE TRUNCATE ON purged_proposals
 FOR EACH STATEMENT EXECUTE FUNCTION immutable_truncate_guard();
