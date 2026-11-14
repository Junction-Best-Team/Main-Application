-- PER-004: a recipe plan revision and a recipe version are history too. Block every UPDATE and
-- DELETE with the same guard as the other history tables (immutable_record(), 001). Additive: two
-- new triggers; no row, column or constraint changes. Nothing in the application updates or
-- deletes these tables (plan revisions are only appended, recipe versions only inserted with
-- ON CONFLICT DO NOTHING), so existing behaviour is unchanged.
CREATE TRIGGER immutable_recipe_plan_revisions BEFORE UPDATE OR DELETE ON recipe_plan_revisions
 FOR EACH ROW EXECUTE FUNCTION immutable_record();
CREATE TRIGGER immutable_recipe_versions BEFORE UPDATE OR DELETE ON recipe_versions
 FOR EACH ROW EXECUTE FUNCTION immutable_record();
