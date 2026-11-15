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
