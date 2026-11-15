# Verification

## 2026-11-15: Sent message reappears in the composer

Reproduced on `5872b32` with a fixture-backed browser test using
"i would like to cook 200 carbonara". The first conversation GET can include
`busy=true` and `retry_message` for the accepted text-only turn. Initial loading
restored that metadata as a draft even while the assistant was working.

The loader now restores retry drafts only when the conversation is idle.
The new regression failed before the fix and passed afterward, including a
refresh during the running turn. All eight selected send, queue and recovery
browser tests passed. `npm run build` passed (lint, types and production build).
Changed-file formatting passed; `npm run check` stopped on pre-existing
formatting in `ConversationTranscript.tsx` and `conversation.spec.ts`.
Browser responses were authored fixtures; no live supplier or model was called.

## 2026-11-15: Repeated basket errors and duplicate product lists

The assistant's final text appended every per-product purchasing reason after its
recipe reply. Automatic cart preparation was also absent from its instructions,
so it could ask for delivery details while the server staged a basket. The reply
now points to the retained purchasing checks once, and the prompt describes the
existing automatic delivery defaults. Recipe quantities are collapsed when the
same message has a basket. SKU cards use the server's nullable net amount instead
of converting missing gross/tax values into a zero price.

Validation: 106 agent unit tests and 28 cart/conversation integration tests passed
against an isolated fixture database. Python lint and the frontend lint/type/build
passed. The chat browser suite passed 51 of 59 tests; all eight failures reproduced
on unchanged `93a1138` (composer height, navigation visibility and retry alert).
`npm run check` stopped on existing formatting in `ChatComposer.tsx` and
`chat-activity.spec.ts`; changed-file formatting passed. Browser responses were
authored fixtures; no model or supplier was called by these checks.
