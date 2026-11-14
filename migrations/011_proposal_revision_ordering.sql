-- 008-010 are reserved for Person 3. This replaces the earlier PR #38 file
-- 008_proposal_revision_ordering.sql without replaying its backfill if applied.
DO $$
BEGIN
 IF NOT EXISTS (
  SELECT 1 FROM pg_attribute WHERE attrelid='proposals'::regclass
  AND attname='updated_at' AND NOT attisdropped
 ) THEN
  ALTER TABLE proposals ADD COLUMN updated_at timestamptz NOT NULL DEFAULT now();
  UPDATE proposals p SET updated_at = latest.updated_at
  FROM (
      SELECT p.id, COALESCE(MAX(a.created_at) FILTER (
          WHERE a.event IN ('proposal_prepared', 'proposal_revised')
      ), p.created_at) AS updated_at
      FROM proposals p LEFT JOIN audit_events a ON a.proposal_id = p.id
      GROUP BY p.id
  ) latest
  WHERE p.id = latest.id;
 END IF;
END $$;
CREATE INDEX IF NOT EXISTS proposals_buyer_updated ON proposals(buyer_id, updated_at DESC, id);
