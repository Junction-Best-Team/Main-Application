# Chat attachments

Drop files on the chat input or paste a file/image into it.
The input shows image thumbnails and file cards with names, types, sizes and remove buttons.
Send files with a message or on their own. Sent files stay with the conversation and can be
viewed or downloaded by authenticated members of the same buyer account.

Supported: PDF, Word (`.docx`), Excel (`.xlsx`), CSV, UTF-8 TXT, PNG, JPEG and WebP.
Legacy `.doc` / `.xls`, macros, encrypted documents and other formats are rejected.

- At most **3 files**, **2 MiB each**, **4 MiB combined** per message (the UI calls these MB).
- Extracted document text: at most **30,000 characters per file**. Oversized content is rejected,
  never silently truncated. PDF: at most **10 pages**, with readable text; scanned PDFs must
  be supplied as images. PDF diagrams and embedded images are not extracted.
- Excel: at most **10 sheets**, **500 rows / 50 columns per sheet**, **5,000 traversed cells**
  overall. CSV: **500 rows / 50 columns**. Formulas are read as text, never evaluated.
- Office archives: at most **200 members / 10 MiB expanded**. XML entities are disabled.
- Images: at most **16 million pixels**; model input is a JPEG with a maximum dimension of
  1,280 pixels / 512 KiB, on a white background. The original remains available for download.
- Each parser runs in a subprocess with **8 seconds wall time / 4 seconds CPU** and, on Linux,
  **512 MiB address space**. Request JSON, including chunked uploads, is capped at **6 MiB**.
- The existing conversation text-context bound remains; total model image context is separately
  capped at **6,000,000 base64 bytes**. A full conversation fails explicitly and asks for a new chat.
  Existing account message/queue limits also apply.

Files are untrusted reference data for menus, ingredient lists and purchasing questions. They
never change purchasing policy or authorize a purchase or memory write. The usual exact-revision
confirmation is still required. The configured conversational model must support vision for images.
Document text and normalized images are sent to that model provider as part of the conversation;
original Office binaries are not. Input and preparation guardrails receive bounded text excerpts,
not a separate visual inspection of pixels or a complete document security scan.

## Operations and contract

Apply additive migration `020_chat_attachments.sql` with the schema-owner credentials before
starting this code. Readiness checks the new column. No new runtime grants, object storage,
public CDN or environment variables are needed. Local Compose's frontend proxy accepts 6 MiB
JSON bodies; the API enforces the bound independently. Nothing here deploys or migrates a live database.

`MessageRequest.attachments` is an optional array of `{name, media_type, data}` where `data`
is plain base64. The authenticated message POST retains its existing Origin/CSRF checks and
binds the exact file payload into the message's idempotency hash. Validated originals and derived
model context live in `conversation_messages.attachments` JSONB, together with the durable turn.
Accepted retries reuse that parsing. Failed-turn recovery returns the exact original request.

Conversation messages expose metadata and private URLs, without file bodies. Only failed/interrupted
turns return file bodies in `retry_message`; active jobs do not repeat them over SSE. Files are served
at `/api/conversations/{id}/attachments/{message_id}/{index}` with account authorization, no-store
caching and safe Content-Disposition. Documents download; images can display inline. File contents,
parser diagnostics and base64 payloads are not logged. Files share the conversation's retention;
there is no separate file deletion or scanning service. Pending files stay in React memory until
accepted; unsent files must be reattached after a full reload. Retry keys/signatures in session storage
contain no file bodies.
