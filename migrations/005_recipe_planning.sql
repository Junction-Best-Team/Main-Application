-- Additive recipe storage. Dataset import and embedding calls are explicit CLI operations.
CREATE TABLE recipes (id text PRIMARY KEY);
CREATE TABLE recipe_versions (
 recipe_id text REFERENCES recipes(id), version text NOT NULL, data jsonb NOT NULL,
 source text NOT NULL, source_version text NOT NULL, source_hash text NOT NULL,
 attribution text NOT NULL, license text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(recipe_id,version)
);
CREATE TABLE recipe_ingredients (
 recipe_id text, version text, ingredient_id text NOT NULL, ordinal integer NOT NULL,
 data jsonb NOT NULL, PRIMARY KEY(recipe_id,version,ingredient_id),
 FOREIGN KEY(recipe_id,version) REFERENCES recipe_versions(recipe_id,version)
);
CREATE TABLE recipe_embedding_cache (
 model_key text, text_hash text, embedding vector NOT NULL,
 PRIMARY KEY(model_key,text_hash)
);
CREATE TABLE recipe_catalogs (
 id uuid PRIMARY KEY, source_hash text NOT NULL, model_key text NOT NULL,
 dimensions integer NOT NULL CHECK(dimensions > 0), recipe_count integer NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE recipe_catalog_entries (
 catalog_id uuid REFERENCES recipe_catalogs(id), recipe_id text, version text,
 search_text text NOT NULL, embedding vector NOT NULL,
 search_document tsvector GENERATED ALWAYS AS (to_tsvector('simple',search_text) || to_tsvector('english',search_text)) STORED,
 PRIMARY KEY(catalog_id,recipe_id),
 FOREIGN KEY(recipe_id,version) REFERENCES recipe_versions(recipe_id,version)
);
CREATE INDEX recipe_search_document ON recipe_catalog_entries USING gin(search_document);
CREATE TABLE active_recipe_catalog (
 singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton),
 catalog_id uuid NOT NULL REFERENCES recipe_catalogs(id)
);
CREATE TABLE recipe_product_evidence (
 product_id text NOT NULL, product_fingerprint text NOT NULL, ingredient_id text NOT NULL,
 form text NOT NULL, source text NOT NULL, piece_per_sales numeric CHECK(piece_per_sales > 0),
 PRIMARY KEY(product_id,product_fingerprint,ingredient_id,form)
);
CREATE TABLE recipe_plans (
 id uuid PRIMARY KEY, buyer_id text NOT NULL REFERENCES buyers(id),
 agent_id text NOT NULL REFERENCES identities(id), turn_id text NOT NULL,
 recipe_id text NOT NULL, recipe_version text NOT NULL, portions integer NOT NULL CHECK(portions BETWEEN 1 AND 10000),
 revision integer NOT NULL DEFAULT 1, locked boolean NOT NULL DEFAULT false,
 UNIQUE(buyer_id,agent_id,turn_id),
 FOREIGN KEY(recipe_id,recipe_version) REFERENCES recipe_versions(recipe_id,version)
);
CREATE TABLE recipe_plan_revisions (
 plan_id uuid REFERENCES recipe_plans(id), revision integer NOT NULL, data jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(plan_id,revision)
);
