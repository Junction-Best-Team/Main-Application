# Supplier comparison metrics

`get_product` and `search_products` expose `supplier_metrics` from the imported
Valio datasets. This is a database join by product ID, independent of embeddings
and live supplier price/availability calls. The assistant can compare the values
in chat; there is no second product list or new purchase authority.

| Dataset | Value | Meaning and limits |
| --- | --- | --- |
| `delivery_reliability` | 0–1 ratio | Historical delivered-versus-ordered performance. Not current stock, an on-time probability or a delivery guarantee. |
| `carbon_footprint` | kg CO2-eq/kg | Estimated product-group average, not an individual product measurement or a basket total. |

Each metric carries its unit, basis and active `dataset_sha256`. Missing or invalid
values stay `null`; a recorded zero remains zero. Neither metric establishes price,
availability, dietary suitability, purchasing eligibility or permission.

Search accepts optional `sort_by=lower_carbon|higher_delivery_reliability`.
It first retrieves relevant candidates and applies dietary/origin exclusions, then
sorts that shortlist by the chosen metric. Unknowns come last and relevance breaks
ties. This does not find a catalog-wide optimum or treat unknowns as worse products.
Default relevance search retains its ranking and includes both metrics.

The assistant uses these values when asked or when they explain a meaningful choice.
It may ask one relevant optional preference question. It must not ask every customer,
delay a list for that answer, infer a preference, or make it a purchasing requirement.
`record_request.product_preferences` retains explicit choices across turns. One saved
preference automatically applies to subsequent product searches; with both preferences,
the assistant explains trade-offs instead of inventing a combined score.

## Storage and rollout

Migration `027_supplier_metrics.sql` adopts existing `supplier_dataset_imports`,
`supplier_dataset_values` and `active_supplier_datasets` tables without replacing
their contents. It creates empty tables for fresh installations. An empty installation
returns unknown metrics until an operator loads data. **No importer is included.**
Values join the active version on **both dataset and SHA-256**, so inactive imports
cannot leak into comparisons. API/worker runtime grants are read-only for all three
tables; dataset import/activation remains an operator task. Apply migrations and runtime
grants through the existing release migration process before serving this version.

Regression tests use explicitly authored small metric fixtures. Opt-in Google
evaluations compare products and retain a preference using those same isolated
fixtures; they do not verify hosted row counts or live supplier data.
