-- Distinguish approved snapshot size from retained/trimmed catalog size.
ALTER TABLE catalog_generations ADD COLUMN source_product_count integer
    CHECK (source_product_count >= 0);

-- Owner-privileged view: ingestion can protect catalog IDs without reading purchasing data.
CREATE VIEW catalog_protected_products AS
SELECT DISTINCT line->>'product_id' AS product_id FROM proposals p
JOIN proposal_revisions r ON r.proposal_id=p.id AND r.revision=p.current_revision
LEFT JOIN approvals a ON a.proposal_id=p.id AND a.revision=p.current_revision
CROSS JOIN LATERAL jsonb_array_elements(r.snapshot->'lines') AS line
WHERE p.order_id IS NULL AND COALESCE(a.status,'') NOT IN ('rejected','superseded')
AND line->>'product_id' IS NOT NULL
AND ((r.policy_outcome <> 'denied' AND r.expires_at > now())
     OR EXISTS (SELECT 1 FROM recipe_plans rp WHERE rp.proposal_id=p.id));
REVOKE ALL ON catalog_protected_products FROM PUBLIC;
