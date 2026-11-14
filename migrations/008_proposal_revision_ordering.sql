-- Keep original creation time; purchase history follows the latest terms revision.
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
CREATE INDEX proposals_buyer_updated ON proposals(buyer_id, updated_at DESC, id);
