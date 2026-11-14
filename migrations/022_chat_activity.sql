-- Display-only worker progress. Never contains arguments, results or model reasoning.
ALTER TABLE conversation_turns ADD COLUMN progress jsonb NOT NULL DEFAULT '[]'::jsonb
 CHECK (jsonb_typeof(progress) = 'array' AND jsonb_array_length(progress) <= 600);
