# Supplier CSV datasets

Valio supplies two static CSVs through its [documented API](https://junction26.valioaimo.fi/docs):

| Dataset / endpoint | Columns | Meaning |
| --- | --- | --- |
| `/api/delivery-reliability/download` | `productId`, `deliveryReliability` | Historical delivered-versus-ordered performance, 0–1; not current availability or a delivery guarantee |
| `/api/carbon-footprint/download` | `productId`, `AVG kg CO2-eq/kg` | Estimated product-group average in kg CO2-eq per kg; not a measurement of the individual product |

Both files omit some products. Missing rows and blank values remain unknown; a supplied
zero remains zero. Values join to the catalog by product ID. IDs absent from the current
catalog remain in the snapshot, so refreshes cannot silently discard supplier evidence.

## Explicit operator import

Apply additive migration `026_supplier_datasets.sql` through the normal owner migration
procedure. Then, with the schema owner's private `DATABASE_URL` and server-only
`VALIO_AIMO_API_KEY` configured:

```sh
uv run aimo ingest-supplier-datasets --download --directory data/supplier
# Reuse downloaded, approved CSVs without another API request:
uv run aimo ingest-supplier-datasets --directory data/supplier
```

Only these two static files are downloaded. The existing downloader sends `X-API-Key`
on the initial request, strips it on redirects and bounds HTTPS requests, retries, size
and time. Parsing has an additional 10 MiB / 100,000-row limit. Both SHA-256 hashes,
exact headers, row counts, unique product IDs and finite nonnegative decimals are
validated before publishing either dataset. Reliability cannot exceed 1.

These snapshots were obtained from the official API on 15 November 2026. Announced
replacements require a reviewed update to the pinned `Dataset` definitions:

| Dataset | Rows | SHA-256 |
| --- | ---: | --- |
| Reliability | 4,425 | `d24dc9e17d2652e7c21ea39fcf08e55522d044313031af1d9f3424fb84b2bb72` |
| Carbon | 11,033 | `72b1ed6a22a0a40dcb7969d0c1f21229cdb5b64b5dba68b7db7fc7e947376eac` |

`supplier_dataset_imports` records source, hash, row count and import time;
`supplier_dataset_values` stores decimals by dataset/hash/product ID;
`active_supplier_datasets` selects each active snapshot. One transaction and an advisory
lock publish both. Failed imports preserve existing active snapshots. Repeated imports
reuse the same snapshots and import timestamps. The runtime role can read these tables
but cannot insert, update, delete or truncate them. The catalog-sync role retains its
existing permissions; this separate import uses the schema owner.

This is storage and operator tooling. Product responses, assistant tools, UI, search
ranking and purchase snapshots do not consume these values yet. No model call, catalog
re-embedding, price/availability lookup, policy change or mock order occurs. There is no
recurring download; Valio says files remain static unless an update is announced.

## Private hosted access

Run within the private network, or through an existing authenticated cluster tunnel
bound only to `127.0.0.1`. Keep the original private database hostname for TLS verification
(`sslmode=verify-full` with the provider CA); libpq's `hostaddr` may target the local
tunnel. No public database access, firewall change, Terraform apply or app rollout is
required. Keep owner credentials and cluster configurations in ignored, mode-0600 files;
never pass credentials as literal command arguments or print them.
