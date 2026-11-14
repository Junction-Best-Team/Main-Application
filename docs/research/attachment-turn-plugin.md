# Research: Attachment plug-in points (messages, SSE, run_turn)

Ticket: [#182](https://github.com/Junction-Best-Team/Main-Application/issues/182)  
Map: [#24](https://github.com/Junction-Best-Team/Main-Application/issues/24)  
Date: 2026-11-14  
Scope: primary sources in this repo only (code, migrations, docs). No product implementation.

Destination: chat **Attachment** = file bound to a chat message; agent must ingest usable content in the **same send turn** (vision for images; text/table extract for PDF/XLSX; no OCR v1). Caps from the map: 10MB/file, ≤3/message; bind on send; soft warning if extract fails.

Related ship ticket [#184](https://github.com/Junction-Best-Team/Main-Application/issues/184) is out of scope here. Durable upload/storage primitives are [#183](https://github.com/Junction-Best-Team/Main-Application/issues/183).

## Verdict

Buyer Attachments have **no** schema, API field, or agent-history path today. The only message-level `image` field is an **assistant** recipe illustration (`RecipeImage`), not a buyer upload. SSE already re-emits full `ConversationResponse` snapshots from `conversations.detail`, so Attachment metadata must land on the persisted message / detail shape once; it will then appear on GET and SSE together. Same-turn agent use requires binding files in `enqueue` **before** the worker builds history for `run_turn`, then injecting usable content into that history—today history is **text-only** and `run_turn` rejects non-string `content`.

## 1. Message schema and persistence

### Table `conversation_messages`

Created in `migrations/003_chat_purchasing.sql`:

```28:34:migrations/003_chat_purchasing.sql
CREATE TABLE conversation_messages (
 id bigserial PRIMARY KEY, conversation_id uuid NOT NULL REFERENCES conversations(id),
 turn_id uuid NOT NULL REFERENCES conversation_turns(id),
 role text NOT NULL CHECK(role IN ('user','assistant')), text text NOT NULL,
 meal_plan jsonb, proposal_id uuid REFERENCES proposals(id),
 created_at timestamptz NOT NULL DEFAULT now(), UNIQUE(turn_id,role)
);
```

Migration `015_recipe_images.sql` adds only optional assistant illustration JSON:

```1:2:migrations/015_recipe_images.sql
-- Optional illustrations are separate from recipe and purchase evidence.
ALTER TABLE conversation_messages ADD COLUMN image jsonb;
```

**Gap:** no Attachment table, no buyer file columns, no extract-status columns. Migrations under `migrations/` never mention attachments/uploads for chat.

### API contracts (`src/aimo/chat_schemas.py`)

Send body is text + idempotency (+ optional POL-008 constraints):

```87:94:src/aimo/chat_schemas.py
class MessageRequest(Model):
    text: str = Field(min_length=1, max_length=4000)
    idempotency_key: str = Field(min_length=8, max_length=120)
    constraints: MessageConstraints | None = Field(
        default=None,
        description="Optional hard limits set by the customer (budget, dietary toggles). They "
        "stay in force for the rest of the conversation until a later message changes them.",
    )
```

Returned message shape:

```118:125:src/aimo/chat_schemas.py
class ChatMessage(Model):
    id: int
    role: Literal["user", "assistant"]
    text: str
    created_at: datetime
    meal_plan: MealPlan | None = None
    proposal_id: str | None = None
    image: RecipeImage | None = None
```

`RecipeImage` (`src/aimo/image_schemas.py`) is a hosted Cloudinary URL + dimensions for **assistant** illustrations—not buyer Attachment bytes or extracts.

### Write path: `enqueue`

`POST /api/conversations/{id}/messages` → `conversations.enqueue` (`src/aimo/api.py` ~351–358).

Idempotency hash covers **text and constraints only**:

```119:122:src/aimo/conversations.py
        records = body.constraints.records() if body.constraints else None
        # The hash covers the text and, when present, the customer's limits (POL-008), so a retry
        # with the same key and another record is a conflict. Without limits it is unchanged.
        digest = fingerprint({"text": body.text} | ({"constraints": records} if records else {}))
```

User row insert is text-only:

```157:160:src/aimo/conversations.py
            c.execute(
                """INSERT INTO conversation_messages(conversation_id,turn_id,role,text)
                VALUES(%s,%s,'user',%s) ON CONFLICT(turn_id,role) DO NOTHING""",
                (cid, tid, body.text),
            )
```

**Plug-in (send / bind):** extend `MessageRequest` with Attachment references (or complete multipart bind in the same request—storage design is #183). On accept:

1. Validate allowlist/caps (`.png`/`.jpg`/`.jpeg`/`.xlsx`/`.pdf`, ≤10MB, ≤3).
2. Include Attachment identity (stable ids / content hashes) in `payload_hash` so retries cannot silently swap files.
3. Persist the user message **and** bind Attachment rows to that `turn_id` / message id in the same transaction as today’s user insert, so the worker always sees bindings for the claimed turn.

Do **not** reuse `conversation_messages.image` / `RecipeImage` for buyer files: that column is written only on the assistant insert and documented as recipe illustration hosting (`docs/recipe-images.md`).

### Read path: `detail`

```70:74:src/aimo/conversations.py
        messages = c.execute(
            """SELECT id,role,text,created_at,meal_plan,proposal_id,image FROM conversation_messages
            WHERE conversation_id=%s ORDER BY id""",
            (cid,),
        ).fetchall()
```

**Plug-in (metadata for UI/SSE):** join or second query for Attachment metadata (filename, mime, size, extract status/warning). Expose on `ChatMessage` (e.g. `attachments: [...]`). Prefer metadata + extract summary in the snapshot; raw bytes belong behind authenticated download (open product question on #24: whether SSE carries bytes, extract text, or references).

## 2. Conversation SSE snapshots

```369:416:src/aimo/api.py
    @app.get(
        "/api/conversations/{conversation_id}/events",
        ...
                "description": "SSE event 'conversation' carries ConversationResponse JSON; 'expired' carries an empty object. Comments are heartbeats.",
...
                    data = await anyio.to_thread.run_sync(
                        conversations.detail, current, conversation_id
                    )
...
                if value != previous:
                    yield f"event: conversation\ndata: {value}\n\n"
```

Frontend opens that stream with `EventSource` (`frontend/src/features/chat/api/chatApi.ts`) and replaces local conversation state from full snapshots (`useChat.ts`).

**Plug-in:** none separate from `ConversationResponse` / `detail`. Once Attachment metadata (and soft-warning state) appear on messages in `detail`, SSE clients receive them on the next changed snapshot. No second SSE event type is required for v1 metadata.

**Gap:** composer Attach control is inert UI only (`ChatComposer.tsx` `InertButton` “Attach file”). `sendMessage` posts JSON `MessageRequest` with `{ text, idempotency_key }` only (`useChat.ts` ~165–168)—no files.

## 3. Agent history construction (`execute_turn` → `run_turn`)

Worker loads the conversation via `detail`, then builds OpenAI-style history as **role + string content**:

```299:310:src/aimo/conversations.py
        data = detail(identity, cid)
        with connection() as c:
            limits = customer_constraints(c, cid, tid)
        history = [{"role": m["role"], "content": m["text"]} for m in data["messages"]]
        # Structured persisted plans and status survive refresh, restarts and a provider context reset.
        for index, msg in enumerate(data["messages"]):
            if msg["meal_plan"]:
                history[index]["content"] += "\nStored meal plan: " + str(msg["meal_plan"])
            if msg["image"]:
                history[index]["content"] += (
                    "\nAn AI-generated recipe illustration was attached to this reply."
                )
```

That history is passed into `run_turn` on the same turn the buyer just queued (claim → execute). Recipe `image` only appends a **sentence**; it does not pass pixels to the chat model.

`run_turn` re-copies string contents into the provider transcript and validates string-only content:

```209:229:src/aimo/agent.py
def validate_context(identity, messages):
    ...
        or any(
            not isinstance(message, dict)
            or message.get("role") not in ("user", "assistant")
            or not isinstance(message.get("content"), str)
            for message in messages
        )
    ):
        raise Problem("INVALID_CONVERSATION", "Only persisted user/assistant text is allowed.", 422)
```

```268:268:src/aimo/agent.py
    history += [{"role": m["role"], "content": m["content"]} for m in messages]
```

OpenAI-compatible provider sends `messages` as-is (`agent_provider.py` `complete`). Google adapter maps user content to text parts only:

```72:72:src/aimo/google_chat.py
                native_role, parts = "user", [{"text": message["content"]}]
```

**Plug-in (same-turn ingest):** in `execute_turn`, after loading messages for the claimed turn (and before `run_turn`):

1. Resolve Attachments bound to each user message (especially the latest user row for this `turn_id`).
2. For PDF/XLSX: extract text/tables (no OCR); append bounded extract into that user `content` string (fits current `validate_context` / providers). On failure, record soft warning on Attachment/message metadata (visible via `detail`/SSE) and still run the turn with text-only buyer message so the buyer can interrupt and re-attach.
3. For images: either (a) run a vision/describe step and append text into `content` (keeps string-only history), or (b) extend history + `validate_context` + `google_chat.contents` / OpenAI message shape to multimodal parts. Option (a) matches today’s contracts with less blast radius; (b) is true vision-in-the-chat-model.
4. Do this **inside the worker for the claimed attempt**, using files already bound at enqueue time, so ingest happens in the send turn without waiting for a second buyer message.

**Gap:** text-only history; no extract/vision step; string-only validation; Google/OpenAI paths have no buyer-image part construction.

## 4. Contrast: existing “image” path (do not confuse)

| Concern | Recipe illustration today | Buyer Attachment (needed) |
| --- | --- | --- |
| Role | Assistant tool output | User file on send |
| Column | `conversation_messages.image` jsonb | New binding (not this column) |
| Bytes | `recipe_image_jobs.image_bytes` then Cloudinary | #183 storage; bind to message/turn |
| Agent history | One English sentence | Usable content same turn |
| Frontend | Renders `message.image` | Attach control still inert |

Documented in `docs/recipe-images.md` and findings `F-IMAGE-001` (`docs/findings.md`).

## 5. Frontend send surface (context for ship)

- `frontend/src/features/chat/api/chatApi.ts`: JSON POST only.
- `frontend/src/features/chat/hooks/useChat.ts`: pending key stores `{ text, idempotency_key }`—must also cover Attachment ids when shipping bind-on-send.
- `frontend/src/features/chat/components/ChatComposer.tsx`: attach button inert.

Ship work for UI + upload belongs to #184 / storage research #183; listed so turn-plugin contracts stay aligned with the client.

## 6. Recommended plug-in checklist for #184

1. **Schema:** Attachment rows (or equivalent) keyed to `conversation_messages` / `conversation_turns`; never overload `image` jsonb.
2. **`MessageRequest` + `enqueue`:** accept/bind ≤3 allowlisted files; fold ids into `payload_hash`; insert user text + bindings atomically.
3. **`ChatMessage` + `detail`:** surface Attachment metadata + extract warning for GET and SSE.
4. **`execute_turn` history:** inject extract text and/or vision-derived usable content for the current user message before `run_turn`.
5. **`run_turn` / providers:** keep string `content` if using extract/describe; only widen to multimodal if product chooses in-model vision.
6. **Idempotency / retry:** same key + different files = conflict; extract failure = soft warning, not silent success as “live ingested.”

## Evidence (commands / sources)

- Read migrations `003_chat_purchasing.sql`, `015_recipe_images.sql`; grepped `migrations/` for attachment/upload (none for buyer chat).
- Read `src/aimo/chat_schemas.py`, `conversations.py` (`detail`, `enqueue`, `execute_turn`), `api.py` SSE handler, `agent.py` (`validate_context`, `run_turn`), `agent_provider.py`, `google_chat.py`.
- Read frontend `chatApi.ts`, `useChat.ts`, `ChatComposer.tsx`.
- Issue bodies #182 / #24 / #183 / #184 via `gh-axi issue view`.

## Out of scope (explicit)

- No feature code, no merge, no work on ship #184.
- Upload/blob primitives → #183.
- Product choices still open on #24 (SSE bytes vs references; exact vision/extract libraries; retention/malware scanning) are noted as open, not decided here.
