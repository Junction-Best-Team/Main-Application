# Voice conversations

Click **Voice** beside the request composer, allow the microphone and speak.
Gemini 3.8 Live listens and speaks; the existing Aimo worker handles each request.
The recognized words and reviewed assistant reply are saved in the normal chat.
Mute pauses microphone input. End voice, navigation, sign-out and backgrounding
release the microphone, queued playback and connection. Accepted requests keep
running in the durable chat queue after voice ends.

The interface uses the existing Nordic UI tokens: teal controls, lime listening
indicator and a compact white panel above the composer, stacked at mobile widths.
Statuses identify listening, working and speaking without relying on animation.
Keyboard focus, 44px touch controls and the text conversation remain available.

## Configuration and credentials

`VOICE_ENABLED=true` and `VOICE_MODEL=gemini-3.8-live` are the defaults. Set
`VOICE_ENABLED=false` to disable token issuance without changing text chat.
The API needs the same private `GEMINI_API_KEY` as the worker. Compose forwards
it explicitly; Kubernetes selects only that key from `aimo-worker-runtime`, not
the worker's Cloudinary or legacy provider credentials. Existing releases already
populate that Secret; no new credential, schema migration or index rebuild is
needed specifically for voice. PR #132's Google index cutover still applies.
When release credentials rotate, both API and worker restart to pick up the new
key; the frontend never receives it.

The authenticated, Origin/CSRF-protected
`POST /api/conversations/{id}/voice-session` checks conversation ownership and
refuses unfinished/retryable chat work. It uses the portable `google_api_request`
helper to mint a single-use token, valid for a five-minute voice session and only
60 seconds for establishing a connection. The entire native setup is locked to
the model, system instruction, audio settings and one `ask_aimo` function.
Five token requests per buyer per five minutes are allowed, shared across API
replicas through the existing counter table. Provider failures never expose keys
or provider bodies and never silently fall back to another service.

The browser connects directly to Google's constrained WebSocket endpoint using
that temporary token. The long-lived key never reaches the browser. Tokens and
raw audio are not stored in application tables, local/session storage or logs.
The UI discloses that audio goes to Google and the voice is AI-generated. Google
processing/retention is subject to the configured Google account/API terms.
Production needs HTTPS and microphone permission. The frontend CSP permits only
the specific Google WSS host alongside existing same-origin connections; the
microphone worklet is a separate same-origin asset, without data/blob scripts.

## Chat and purchasing boundary

Live has no product, policy, approval or order tools. Its one function delegates
the accumulated input transcription to the existing authenticated `/messages`
route, using the normal stable retry key and existing queue limits. Model-authored
function arguments cannot rewrite the transcript. Duplicate call IDs are ignored.
The bridge waits for the saved assistant reply before permitting audio playback;
unsolicited model audio before a saved reply is discarded. The Live model is
instructed to read the returned reply faithfully, rather than invent facts.
The saved text and exact basket remain authoritative; speech rendering is still
model output and is not a new source of product or purchasing evidence.

Each request uses the current typed tools, deterministic purchasing controls and
semantic guardrails in the normal worker. The microphone pauses while that
request is processing; during spoken playback the user can interrupt. Voice
never calls the confirmation API. Spoken agreement, including “confirm that,” is
ordinary chat text. The customer still reviews and confirms the exact revision
on screen. Orders remain explicitly labelled demo mocks.

Connection failures release audio resources and leave the saved conversation
usable. There is no automatic paid reconnect or replay. Sessions end after five
minutes and can be restarted explicitly. Worker latency remains part of voice
latency; this change does not bypass the durable queue or stream unchecked model
tokens. Browser regressions use fake microphone devices and authored Google
WebSocket responses; live verification is separate and synthetic only.

Protocol references: [Live API](https://aistudio.google.com/docs/live-api),
[native setup and token constraints](https://aistudio.google.com/api-reference/live),
[ephemeral tokens](https://aistudio.google.com/docs/live-api/ephemeral-tokens).
