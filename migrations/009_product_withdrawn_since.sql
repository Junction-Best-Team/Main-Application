-- Additive: when a catalog row became withdrawn (NULL = not withdrawn).
ALTER TABLE products ADD COLUMN withdrawn_since timestamptz;
-- Best available evidence for rows already flagged `deleted`: the first retained generation that
-- carries them. The true withdrawal date is unknown for those rows.
UPDATE products p SET withdrawn_since = g.created_at
FROM catalog_generations g
WHERE g.id = p.generation AND p.facts->'deleted' = 'true'::jsonb;
CREATE INDEX products_withdrawn_since ON products (generation, withdrawn_since)
 WHERE withdrawn_since IS NOT NULL;
