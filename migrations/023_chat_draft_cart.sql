-- Display-only selected plan, separate from sanitized activity and purchasing records.
ALTER TABLE conversation_turns ADD COLUMN draft_cart jsonb
 CHECK (draft_cart IS NULL OR jsonb_typeof(draft_cart) = 'object');
