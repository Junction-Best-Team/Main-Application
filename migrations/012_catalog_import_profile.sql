-- Record which normalization/search-document code built each catalog generation, so an
-- unattended catalog sync never treats a catalog built by different import code as current.
-- Existing generations keep NULL (unknown profile): the first sync rebuilds them once,
-- reusing every cached embedding whose document text is unchanged. Additive only.
ALTER TABLE catalog_generations ADD COLUMN IF NOT EXISTS import_profile text;
