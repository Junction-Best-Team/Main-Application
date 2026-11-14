-- Policy management is an explicit buyer permission, separate from spending authority.
CREATE TABLE policy_managers (
 buyer_id text NOT NULL REFERENCES buyers(id),
 identity_id text NOT NULL REFERENCES identities(id),
 PRIMARY KEY (buyer_id, identity_id)
);
INSERT INTO policy_managers
 SELECT buyer_id,id FROM identities WHERE id='buyer' AND buyer_id='demo-hotel' AND role='approver';

CREATE TABLE policy_changes (
 buyer_id text NOT NULL, version integer NOT NULL, actor_id text NOT NULL REFERENCES identities(id),
 created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY (buyer_id,version), FOREIGN KEY (buyer_id,version) REFERENCES policies
);
CREATE TRIGGER immutable_policy_changes BEFORE UPDATE OR DELETE ON policy_changes
 FOR EACH ROW EXECUTE FUNCTION immutable_record();

-- The runtime role still cannot write policies, buyer provisioning or manager grants directly.
-- Only the authenticated browser API exposes this operation; no agent tool calls it.
CREATE FUNCTION save_buyer_policy(actor text, expected_version integer, new_rules jsonb)
RETURNS integer LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE account text; current_version integer; next_version integer;
BEGIN
 SELECT buyer_id INTO account FROM identities WHERE id=actor;
 SELECT current_policy INTO current_version FROM buyers WHERE id=account FOR UPDATE;
 PERFORM id FROM identities WHERE buyer_id=account ORDER BY id FOR SHARE;
 IF NOT EXISTS (
   SELECT 1 FROM identities i JOIN policy_managers m ON m.identity_id=i.id AND m.buyer_id=i.buyer_id
   WHERE i.id=actor AND i.active AND i.role='approver'
 ) THEN
   RAISE EXCEPTION 'POLICY_FORBIDDEN';
 END IF;
 IF current_version IS DISTINCT FROM expected_version THEN
   RAISE EXCEPTION 'POLICY_CONFLICT';
 END IF;
 IF (SELECT rules - 'autonomous_limit' FROM policies WHERE buyer_id=account AND version=current_version) = new_rules THEN
   RETURN current_version;
 END IF;
 SELECT coalesce(max(version),0)+1 INTO next_version FROM policies WHERE buyer_id=account;
 INSERT INTO policies(buyer_id,version,rules) VALUES(account,next_version,new_rules);
 UPDATE buyers SET current_policy=next_version WHERE id=account;
 INSERT INTO policy_changes(buyer_id,version,actor_id) VALUES(account,next_version,actor);
 RETURN next_version;
END;
$$;
-- Capture the installation schema, including isolated migration-test schemas.
DO $$ BEGIN
 EXECUTE format('ALTER FUNCTION save_buyer_policy(text,integer,jsonb) SET search_path=%I,pg_temp', current_schema());
END $$;
REVOKE ALL ON FUNCTION save_buyer_policy(text,integer,jsonb) FROM PUBLIC;
