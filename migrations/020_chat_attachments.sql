-- Private files live with the durable user message, never in pod-local storage or a public CDN.
ALTER TABLE conversation_messages ADD COLUMN attachments jsonb NOT NULL DEFAULT '[]'::jsonb
 CHECK (jsonb_typeof(attachments) = 'array' AND jsonb_array_length(attachments) <= 3
        AND octet_length(attachments::text) <= 8388608);
