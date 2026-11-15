-- Adopt the existing hosted dataset contract without replacing imports or active hashes.
-- This migration creates empty storage on a fresh installation; it imports no data.
CREATE TABLE IF NOT EXISTS supplier_dataset_imports (
    dataset text NOT NULL,
    sha256 text NOT NULL,
    source text NOT NULL,
    row_count integer NOT NULL,
    imported_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (dataset, sha256)
);
CREATE TABLE IF NOT EXISTS supplier_dataset_values (
    dataset text NOT NULL,
    sha256 text NOT NULL,
    product_id text NOT NULL,
    value numeric NOT NULL,
    PRIMARY KEY (dataset, sha256, product_id)
);
CREATE TABLE IF NOT EXISTS active_supplier_datasets (
    dataset text PRIMARY KEY,
    sha256 text NOT NULL
);
