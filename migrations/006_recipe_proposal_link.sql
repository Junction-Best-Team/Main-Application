-- Keep a recipe plan tied to one proposal through commercial refreshes.
ALTER TABLE recipe_plans ADD COLUMN proposal_id uuid UNIQUE REFERENCES proposals(id);

-- Upgrade plans prepared before this link existed. Never choose arbitrarily
-- between multiple legacy proposals: an operator must resolve that ambiguity.
DO $$
BEGIN
 IF EXISTS (
  SELECT rp.id FROM recipe_plans rp
  JOIN proposals p ON p.buyer_id=rp.buyer_id AND p.agent_id=rp.agent_id
  JOIN proposal_revisions r ON r.proposal_id=p.id AND r.revision=p.current_revision
  WHERE r.request->>'recipe_plan_id'=rp.id::text
  GROUP BY rp.id HAVING count(*) > 1
 ) THEN
  RAISE EXCEPTION 'Resolve multiple proposals for one recipe plan before migrating';
 END IF;
END $$;

UPDATE recipe_plans rp SET proposal_id=p.id, locked=true
FROM proposals p JOIN proposal_revisions r
 ON r.proposal_id=p.id AND r.revision=p.current_revision
WHERE p.buyer_id=rp.buyer_id AND p.agent_id=rp.agent_id
 AND r.request->>'recipe_plan_id'=rp.id::text;
