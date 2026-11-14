# OpenRouter catalog search

This describes the retained opt-in legacy OpenRouter backend. The current default
is [Google Embedding 2 and Decision 1](google-models.md), with a separate staged
index cutover. Select `EMBEDDING_BACKEND=openrouter` explicitly to use this profile.

The hosted profile uses `qwen/qwen3-embedding-8b` at its native **4096 dimensions**,
keyword retrieval, and `qwen/qwen3-reranker-8b` on at most 30 filtered candidates.
This is a candidate for improved Finnish/English retrieval, not a claim that a
public benchmark proves it is the best model for this catalog. The local E5 backend
is available through explicit `EMBEDDING_BACKEND=sentence_transformers` selection.

Discovery text includes source names, brand, vendor, units and bounded
Finnish/English/Swedish descriptions. Descriptions never establish allergen safety
or quantity conversions. Structured dietary filters run before reranking; returned
indexes refer only to our filtered candidates. Exact product ID/GTIN matches skip
both external APIs. Live prices and stock are not embedded.

## Import and cutover

These are explicit operator steps after migration review. This PR does not deploy,
merge itself, apply Terraform or enable the release switch.

0. If the scheduled `aimo-catalog-sync` CronJob is enabled, suspend it for this
   staged cutover (`catalog_sync.suspend = true`). Otherwise a run with the new
   profile would rebuild and activate before the coordinated restart. Resume it
   only after API, worker and CronJob share the new profile
   ([catalog sync](catalog-sync.md)).
1. Run `aimo migrate` as the schema owner. Migration `005_hosted_search.sql`
   preserves old rows and removes the unused HNSW index. Vector columns can hold
   both 384- and 4096-dimensional generations; a database trigger enforces each
   generation's dimension. Exact cosine ranking stays within one materialized
   generation (4096-dimensional HNSW on `vector` is unsupported).
2. In a private importer environment set `EMBEDDING_BACKEND=openrouter` and
   `SEARCH_API_KEY` to an OpenRouter key with an appropriate spending limit.
   `LLM_API_KEY` is not reused automatically. Selected product text is sent to
   OpenRouter/providers; the raw JSON file is not uploaded.
3. Build the complete new generation without changing serving:

   ```sh
   aimo ingest --file /private/valio_aimo_junction26_product_data.json --stage
   ```

   Hash/count checks remain. Requests contain 32 texts with at most four batches
   in flight (`EMBEDDING_BATCH_SIZE`, `EMBEDDING_WORKERS`). Completed batches commit
   to the cache immediately, so an interrupted import can resume. Only one batch's
   vectors per worker stays in memory; final product insertion copies vectors
   inside PostgreSQL. Model, dimension and text-profile keys isolate caches.
   Failed/cancelled requests may still incur provider usage.
4. Save the old active generation ID for rollback. Stop accepting new turns, drain
   in-flight work, and stop the API and worker for a coordinated cutover. With the **new profile** configured, run:

   ```sh
   aimo activate-catalog --generation NEW_GENERATION_UUID
   ```

   Activation checks the profile, dimension and full row count. Configure both API and worker
   with the same backend profile, supply the search key only to the worker, and restart. The default retains the immediately
   previous active catalog for rollback. Staging does not prune old catalogs;
   unused staged rows persist until a subsequent activation/prune.
5. Check readiness and real Finnish/English queries through chat. Readiness checks
   database/profile/key presence without billable calls, so provider uptime needs
   a real search smoke test too.

In the Terraform installation, importer and worker read `aimo-worker-runtime`;
the API reads `aimo-runtime`. Private `runtime_secrets` supplies the matching
`EMBEDDING_BACKEND` to both and `SEARCH_API_KEY` only to the worker/importer.
Secret values override the legacy ConfigMap backend. Keep staging importer
overrides separate until cutover, so serving processes keep the old profile.
The release helper syncs conversational `LLM_*` fields only, not search keys.
No GPU/model server is needed. The worker image retains E5 weights for rollback
but hosted mode never loads them. The API checks profile compatibility without
model loading or provider credentials; the worker additionally checks key presence.

Rollback: stop serving, select the old backend/model settings, run
`aimo activate-catalog --generation PREVIOUS_GENERATION_UUID`, and restart with the
old profile. Reimport if the generation was pruned. Do not reverse the migration or
truncate 4096-dimensional vectors. Purchasing/conversation/audit tables are untouched.

## Failure handling and validation

HTTP operation timeouts and retries are bounded (15 seconds and two attempts by
default); only transient failures retry. Missing keys, wrong models, incomplete
batches, duplicate indexes, wrong dimensions and zero/non-finite vectors never
publish a catalog. Embedding outages return typed errors without switching models.
Reranker outages retain filtered hybrid results with `rerank_status=unavailable`.
Provider error bodies and secrets are never surfaced in errors.

Use a separate evaluation database and preserve the historical E5 report:

```sh
python scripts/evaluate_search.py --output docs/search-evaluation-openrouter.json
```

The existing 30 cases include 21 descriptions, six identifiers and three exclusions.
Labels are incomplete and curated, not an independent production benchmark. Compare
descriptive top-one/top-five results, violations, latency and reranker availability.
Expand the labeled Finnish/English set before claiming broad quality/capacity.
Production cluster latency remains an operator check because this PR does not deploy.

Recorded full-catalog runs: [final evaluation](search-evaluation-openrouter.json)
and [reranker comparison](search-reranker-comparison.json). The 8B reranker reached
20/21 descriptive top-five hits (saved E5 baseline: 17/21; 0.6B reranker: 19/21).
Two 8B runs had 12–14/21 labeled top-one hits and 2.1–2.9 second descriptive median
latency, with no filter violations or reranker outages. The Finnish flank-steak
case remains a miss. Ranking variability and incomplete labels limit these claims.

## Costs

On 2026-11-14, embedding prices start at $0.01/million tokens; our real probe routed
at **$0.04/million**. Reranking is listed at $0.20/million. Routing, text length,
retries and ingredient searches affect usage. For 17,546 products at 250–500
tokens/product, one import is roughly $0.04–$0.35 at those embedding rates.
Reranking 30 candidates of that size is about $1.50–$3 per 1,000 searches before
query/instruction overhead. These are estimates, not caps; chat, hosting and
credit-purchase fees are separate. The 8,000-character text limit is not a token limit.

References: [embedding model](https://openrouter.ai/qwen/qwen3-embedding-8b),
[reranker](https://openrouter.ai/qwen/qwen3-reranker-8b),
[embedding API](https://openrouter.ai/docs/api/api-reference/embeddings/submit-an-embedding-request),
[Qwen query formatting](https://huggingface.co/Qwen/Qwen3-Embedding-8B).
