-- Every active human buyer can edit the account's purchasing cap and basket rules.
-- Product scope, delivery scope and personal approval authority stay untouched.
CREATE FUNCTION save_buyer_settings(actor text, expected_version integer, settings jsonb)
RETURNS integer LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE account text; current_version integer; next_version integer; old_rules jsonb; new_rules jsonb;
BEGIN
 SELECT buyer_id INTO account FROM identities WHERE id=actor;
 SELECT current_policy INTO current_version FROM buyers WHERE id=account FOR UPDATE;
 PERFORM id FROM identities WHERE buyer_id=account ORDER BY id FOR SHARE;
 IF NOT EXISTS (
   SELECT 1 FROM identities WHERE id=actor AND buyer_id=account AND active AND role='approver'
 ) THEN
   RAISE EXCEPTION 'POLICY_FORBIDDEN';
 END IF;
 IF current_version IS DISTINCT FROM expected_version THEN
   RAISE EXCEPTION 'POLICY_CONFLICT';
 END IF;
 IF jsonb_typeof(settings) IS DISTINCT FROM 'object'
    OR settings - ARRAY['max_order_gross','substitution','overbuy','whole_sales_units'] <> '{}'::jsonb
    OR NOT settings ?& ARRAY['max_order_gross','substitution','overbuy','whole_sales_units']
    OR coalesce(settings->>'substitution','') NOT IN ('allowed','requires_approval','forbidden')
    OR coalesce(settings->>'overbuy','') NOT IN ('allowed','requires_approval','forbidden')
    OR jsonb_typeof(settings->'whole_sales_units') IS DISTINCT FROM 'boolean' THEN
   RAISE EXCEPTION 'POLICY_SETTINGS_INVALID';
 END IF;
 IF settings->'max_order_gross' <> 'null'::jsonb THEN
   IF coalesce(settings->>'max_order_gross','') !~ '^[0-9]{1,12}(\.[0-9]{1,2})?$' THEN
     RAISE EXCEPTION 'POLICY_SETTINGS_INVALID';
   END IF;
 END IF;
 SELECT rules INTO old_rules FROM policies WHERE buyer_id=account AND version=current_version;
 new_rules := (old_rules - 'autonomous_limit') || settings;
 -- An absent cap and a cleared cap both mean no additional account ceiling.
 IF new_rules->'max_order_gross' = 'null'::jsonb THEN
   new_rules := new_rules - 'max_order_gross';
 END IF;
 IF old_rules - 'autonomous_limit' = new_rules THEN
   RETURN current_version;
 END IF;
 SELECT coalesce(max(version),0)+1 INTO next_version FROM policies WHERE buyer_id=account;
 INSERT INTO policies(buyer_id,version,rules) VALUES(account,next_version,new_rules);
 UPDATE buyers SET current_policy=next_version WHERE id=account;
 INSERT INTO policy_changes(buyer_id,version,actor_id) VALUES(account,next_version,actor);
 RETURN next_version;
END;
$$;
DO $$ BEGIN
 EXECUTE format('ALTER FUNCTION save_buyer_settings(text,integer,jsonb) SET search_path=%I,pg_temp', current_schema());
END $$;
REVOKE ALL ON FUNCTION save_buyer_settings(text,integer,jsonb) FROM PUBLIC;
