# Shared Google API helper

`src/aimo/google_api.py` exposes `google_api_request`. Copy that single file to
another Python project and install `httpx`, or import it from this app. No Google
SDK or new dependency is required. Google's key authenticates directly to Google;
it is not an OpenRouter key. Google also offers an [OpenAI-compatible chat
endpoint](https://aistudio.google.com/docs/openai), but this helper uses the native
API so chat, image generation, embeddings and decisions share one entry point.

Store `GEMINI_API_KEY` server-side in ignored `.env` or the process environment.
The helper also supports `create_live_token` (`POST /auth_tokens`) with native
`bidiGenerateContentSetup` constraints; see [voice mode](voice.md). Live audio
itself uses WebSockets rather than the helper's REST transport.
The standalone helper reads the process environment only. In this repository,
`Settings` reads `.env`; pass its key explicitly as below. Do not source the whole
`.env` in a shell or expose the key through frontend variables.

```python
import httpx

from aimo.config import settings
from aimo.google_api import GoogleAPIError, google_api_request

with httpx.Client() as client:
    def google(operation, **kwargs):
        return google_api_request(
            operation, api_key=settings().gemini_api_key, client=client, **kwargs
        )

    # Main LLM. Native tool definitions and function-call parts can be passed too.
    reply = google("generate_content", model="gemini-4-carbon", payload={
        "contents": [{"role": "user", "parts": [{"text": "Suggest a pasta dish."}]}],
        "generationConfig": {"maxOutputTokens": 1024},
    })

    # Embeddings: one recipe/product per request; use the same model, dimensions
    # and retrieval formatting when indexing and querying.
    vector = google("embed_content", model="gemini-embedding-2", payload={
        "content": {"parts": [{"text": "task: search result | query: tomato pasta"}]},
        "outputDimensionality": 768,
    })["embedding"]["values"]

    # Independent decision checks. Decisions never grant purchasing authority.
    verdict = google("decide", model="gemini-decision-1", payload={
        "input": "Please suggest a lunch recipe.",
        "questions": {"in_scope": {
            "type": "noul", "instructions": "Is the request about food or purchasing?",
        }},
    })["answers"]["in_scope"]

    # Images use generateContent too; inlineData contains MIME type/base64 bytes.
    image = google("generate_content", model="gemini-nano-banana-2.1", timeout=120, payload={
        "contents": [{"parts": [{"text": "A plated tomato pasta, natural food photography."}]}],
        "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]},
    })
```

Each example is a real billable call when executed. For a read-only credential
check, call `google("list_models", payload={"pageSize": 1000})`; follow the returned
`nextPageToken` using `pageToken` when present. Discovery does not prove that a
specific generation request will succeed under the account's quota.

Responses stay in Google's native JSON format. Preserve complete returned content
parts, including thought signatures, when replaying tool turns. Generated images
use the [recipe illustration tool](recipe-images.md) for Cloudinary storage and chat
rendering; the portable helper itself does not upload or render images.

Catch `GoogleAPIError` and inspect `code`/`status_code`. Errors never echo provider
bodies, credentials or prompt text. The helper does not log content. Redirects are
disabled, the response is capped at 32 MiB by default, and HTTPX operation timeouts
are configurable. There is no automatic retry, because an interrupted generation
may already have incurred cost. Caller-supplied clients remain open; use a context
manager for connection pooling. This is a synchronous helper; use it in workers
or a threadpool rather than blocking an async request handler.

The helper remains portable. Application adapters now use it for Google chat,
semantic checks, embeddings, relevance ranking and images. See the
[model/index cutover](google-models.md) before switching an existing installation;
products and recipes must be reindexed. Purchasing authority stays in deterministic
application code. Hackathon credentials are temporary.

Official contracts: [generateContent](https://aistudio.google.com/docs/text-generation),
[image generation](https://aistudio.google.com/docs/image-generation),
[embeddings](https://aistudio.google.com/docs/embeddings),
[decisions](https://aistudio.google.com/docs/decisions-api).
