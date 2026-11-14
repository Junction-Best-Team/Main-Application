-- Preserve the 384-dimensional catalog/cache while allowing a new 4096-dimensional
-- generation. Search uses exact cosine ranking within one materialized generation.
-- pgvector HNSW on vector is limited to 2000 dimensions and is not used by this query.
DROP INDEX IF EXISTS products_vector;
ALTER TABLE products ALTER COLUMN embedding TYPE vector;
ALTER TABLE embedding_cache ALTER COLUMN embedding TYPE vector;
ALTER TABLE catalog_generations ADD COLUMN embedding_dimensions integer NOT NULL DEFAULT 384
    CHECK (embedding_dimensions BETWEEN 1 AND 16000);

CREATE FUNCTION check_catalog_embedding_dimensions() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF vector_dims(NEW.embedding) IS DISTINCT FROM
       (SELECT embedding_dimensions FROM catalog_generations WHERE id=NEW.generation) THEN
        RAISE EXCEPTION 'Embedding dimensions differ from catalog generation';
    END IF;
    RETURN NEW;
END; $$;
CREATE TRIGGER check_catalog_embedding_dimensions BEFORE INSERT OR UPDATE ON products
    FOR EACH ROW EXECUTE FUNCTION check_catalog_embedding_dimensions();
