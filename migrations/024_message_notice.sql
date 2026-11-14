-- Q-108: a chat turn that fails because the model provider fails stores one plain assistant notice.
-- `notice` marks such a message (for example 'provider_unavailable') so the UI can show it as a
-- notice and the model's history can skip it. Additive: one nullable column, no default, no data
-- change; every existing message keeps NULL.
ALTER TABLE conversation_messages ADD COLUMN notice text;
