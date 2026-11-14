# Google model configuration and index cutover

The application now defaults to native Google APIs using one server-side
`GEMINI_API_KEY`. No OpenRouter credit is used with these settings:

| Role | Selection |
| --- | --- |
| Chat and tool selection | `LLM_PROVIDER=google`, `LLM_MODEL=gemini-4-carbon` |
| Semantic guardrails | `GUARDRAIL_PROVIDER=google`, Gemini Decision 1 |
| Product and recipe embeddings | `EMBEDDING_BACKEND=google`, Gemini Embedding 2, 768 dimensions |
| Product shortlist ranking | Gemini Decision 1, when `RERANK_ENABLED=true` |
| Recipe illustrations | Nano Banana 2.1; Cloudinary hosts the result |
| Voice interface | `VOICE_MODEL=gemini-3.8-live`; delegates requests to the same chat worker |

These are separate models with separate jobs. The existing typed agent loop,
buyer scope, commercial validation, purchase confirmation and mock-order labels
remain. The chat adapter preserves native function-call IDs and opaque thought
signatures inside a turn, without saving them in customer history. Native Google
errors and provider bodies are never shown or logged. There is no automatic
fallback to OpenRouter, local models or fake embeddings.

Decision checks keep the existing provisional probability thresholds and failure
behavior. Provider changes require fresh labeled evaluation; passing transport
tests does not establish semantic accuracy. Run `scripts/evaluate_guardrails.py`
with `GUARDRAIL_PROVIDER=google` for the synthetic evaluation. Each call costs
Google usage. Exact purchase permission always comes from deterministic code.

Embeddings use one request per document: Embedding 2 would aggregate multiple
documents if sent together as one content. Product imports keep at most four
batches in flight and cache completed batches. Both queries and documents use
Google's retrieval formatting and normalized vectors. Model/profile keys isolate
old caches, product generations and recipe corpora. A mismatched index fails
closed instead of comparing incompatible vectors.

## Existing installation cutover

This PR changes code and configuration only. It does not rebuild production
indexes, apply Terraform, merge, deploy or enable releases.

1. Retain the old configuration and active product/recipe catalog IDs for rollback.
   Suspend scheduled catalog sync during the coordinated change and drain chat
   work before activation. Existing conversations and orders stay intact.
2. Apply schema migrations through the existing authorized migration procedure.
   No new embedding migration is necessary: vector columns already support
   per-generation dimensions. The image tool still needs migration 015.
3. In the importer set `EMBEDDING_BACKEND=google` and `GEMINI_API_KEY`. Stage the
   complete product snapshot with `aimo ingest --file /private/products.json --stage`.
   This incurs Google usage for uncached documents; do not run it merely to test
   this PR. A failed stage leaves the active generation untouched.
4. Configure API readiness, worker and catalog-sync to the same `google` embedding
   backend. Supply the Google key to the worker/importer and API (the API mints
   short-lived [voice tokens](voice.md)). The frontend never receives that key.
   Terraform now defaults the shared ConfigMap to Google and allows the key in
   the dedicated catalog-sync Secret. Existing explicit `runtime_secrets` or `.env`
   backend overrides must also be changed. Keep Cloudinary credentials worker-only.
5. With serving drained, activate the staged product generation using
   `aimo activate-catalog --generation NEW_GENERATION_UUID`. Reimport the selected
   verified recipe snapshot using `aimo ingest-recipes --file /private/recipes.json
   --expected-sha256 VERIFIED_SHA256`, preserving any `--review-file`. The recipe
   importer atomically activates the complete new corpus. Imported recipes keep
   their existing source/version identities and provenance.
6. Set `LLM_PROVIDER=google`, `LLM_MODEL=gemini-4-carbon`,
   `GUARDRAIL_PROVIDER=google`, and the existing guardrail mode. Restart API/worker,
   check readiness, then test Finnish/English product and recipe queries and a
   normal chat tool round. Resume catalog sync only after its settings match.

The release secret helper selects Google chat/decisions when `GEMINI_API_KEY` is
supplied. An old OpenRouter `LLM_MODEL` release variable is replaced with Carbon;
an explicit native `gemini-*` model is honored. Cloudinary is optional for chat
and search. The helper only patches the worker Secret: it does not change the
shared embedding profile, catalog-sync Secret or existing vectors. Those remain
explicit provisioning/import steps before a coordinated rollout.

For rollback, restore matching configuration and the retained product generation
and recipe corpus together. Do not simply change the model name against a Google
index. Legacy OpenRouter adapters remain available through explicit provider
settings and credentials. Offline E5 remains available for local development;
the worker image needs `--build-arg LOCAL_EMBEDDINGS=true` to include its weights
and ML dependencies. The default Google worker avoids those downloads.

Hackathon credentials and credits are temporary. Google usage still consumes that
account's quota/credit; this change does not make model calls free.

Provider references: [Carbon](https://aistudio.google.com/docs/models/gemini-4-carbon),
[Decisions](https://aistudio.google.com/docs/decisions-api),
[Embedding 2](https://aistudio.google.com/docs/embeddings),
[function calling](https://aistudio.google.com/docs/function-calling).
