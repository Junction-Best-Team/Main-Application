# OpenRouter catalog search

The hosted profile uses `qwen/qwen3-embedding-8b` at its native **4096 dimensions**,
keyword retrieval, and `qwen/qwen3-reranker-0.6b` on at most 30 filtered candidates.
This is a candidate for improved Finnish/English retrieval, not a claim that a
public benchmark proves it is the best model for this catalog. The local E5 backend
remains the default so deploying code alone cannot invalidate an existing index or
start paid calls.

Discovery text includes source names, brand, vendor, units and bounded
Finnish/English/Swedish descriptions. Descriptions never establish allergen safety
or quantity conversions. Structured dietary filters run before reranking; returned
indexes refer only to our filtered candidates. Exact product ID/GTIN matches skip
both external APIs. Live prices and stock are not embedded.

## Import and cutover

These are explicit operator steps after migration review. This PR does not deploy,
merge itself, apply Terraform or enable the release switch.

1. Run `aimo migrate` as the schema owner. Migration `004_hosted_search.sql`
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
4. Save the old active generation ID for rollback. Stop serving for a coordinated
   cutover. With the **new profile** configured, run:

   ```sh
   aimo activate-catalog --generation NEW_GENERATION_UUID
   ```

   Activation checks the profile, dimension and full row count. Configure serving
   with the same backend/key and restart. The default retains the immediately
   previous active catalog for rollback. Staging does not prune old catalogs;
   unused staged rows persist until a subsequent activation/prune.
5. Check readiness and real Finnish/English queries through chat. Readiness checks
   database/profile/key presence without billable calls, so provider uptime needs
   a real search smoke test too.

In the Terraform installation, both importer and app read `aimo-runtime`. Set the
backend/key through private `runtime_secrets`; Secret values override the legacy
ConfigMap backend. Keep importer overrides separate until cutover, so an old app
does not restart with the new profile. The release helper syncs conversational
`LLM_*` fields only, not search keys. No GPU/model server is needed. The existing
image retains E5 weights for rollback but hosted mode never loads them.

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

## Costs

On 2026-11-14, embedding prices start at $0.01/million tokens; our real probe routed
at **$0.04/million**. Reranking is listed at $0.20/million. Routing, text length,
retries and ingredient searches affect usage. For 17,546 products at 250–500
tokens/product, one import is roughly $0.04–$0.35 at those embedding rates.
Reranking 30 candidates of that size is about $1.50–$3 per 1,000 searches before
query/instruction overhead. These are estimates, not caps; chat, hosting and
credit-purchase fees are separate. The 8,000-character text limit is not a token limit.

References: [embedding model](https://openrouter.ai/qwen/qwen3-embedding-8b),
[reranker](https://openrouter.ai/qwen/qwen3-reranker-0.6b),
[embedding API](https://openrouter.ai/docs/api/api-reference/embeddings/submit-an-embedding-request),
[Qwen query formatting](https://huggingface.co/Qwen/Qwen3-Embedding-8B).
