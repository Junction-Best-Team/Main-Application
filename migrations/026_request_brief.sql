-- Reviewed request facts are kept per customer turn, including exploration without a cart.
ALTER TABLE conversation_turns ADD COLUMN request_brief jsonb;
