-- Static supplier evidence, independent of catalog embeddings and purchase history.
CREATE TABLE supplier_dataset_imports (
 dataset text NOT NULL CHECK (dataset IN ('delivery_reliability','carbon_footprint')),
 sha256 text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
 source text NOT NULL,
 row_count integer NOT NULL CHECK (row_count > 0),
 imported_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY (dataset,sha256)
);
CREATE TABLE supplier_dataset_values (
 dataset text NOT NULL,
 sha256 text NOT NULL,
 product_id text NOT NULL CHECK (product_id ~ '^[0-9]{1,32}$'),
 value numeric,
 PRIMARY KEY (dataset,sha256,product_id),
 FOREIGN KEY (dataset,sha256) REFERENCES supplier_dataset_imports(dataset,sha256),
 CHECK (value IS NULL OR (value >= 0 AND value < 'Infinity'::numeric
        AND (dataset <> 'delivery_reliability' OR value <= 1)))
);
CREATE TABLE active_supplier_datasets (
 dataset text PRIMARY KEY,
 sha256 text NOT NULL,
 FOREIGN KEY (dataset,sha256) REFERENCES supplier_dataset_imports(dataset,sha256)
);
