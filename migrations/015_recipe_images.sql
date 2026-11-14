-- Optional illustrations are separate from recipe and purchase evidence.
ALTER TABLE conversation_messages ADD COLUMN image jsonb;
CREATE TABLE recipe_image_jobs (
 turn_id uuid PRIMARY KEY REFERENCES conversation_turns(id),
 buyer_id text NOT NULL REFERENCES buyers(id),
 request_hash text NOT NULL,
 public_id text NOT NULL UNIQUE,
 state text NOT NULL CHECK(state IN ('generating','generated','complete','failed')),
 image_bytes bytea CHECK(octet_length(image_bytes) <= 10485760),
 mime_type text CHECK(mime_type IN ('image/png','image/jpeg','image/webp')),
 image jsonb,
 created_at timestamptz NOT NULL DEFAULT now(),
 CHECK ((state='generated') = (image_bytes IS NOT NULL)),
 CHECK ((state='complete') = (image IS NOT NULL))
);
CREATE INDEX recipe_image_jobs_buyer_time ON recipe_image_jobs(buyer_id,created_at);
