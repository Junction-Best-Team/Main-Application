# Buyer purchasing settings

The owner's 2026-11-14 simplification replaces the earlier manager-only editor.
After sign-in, every active human buyer can edit `/settings`. Agents cannot edit.
The page contains an account spending cap, alternatives/extra-quantity rules and
whole-sales-unit rounding under Advanced. Product codes, delivery destinations,
change history, version numbers and personal approval permissions are not shown.

The optional `max_order_gross` is a shared account cap including tax and charges.
Blank clears the cap; zero permits only a zero-total basket. Existing accounts
without the field gain no new limit. Above-cap baskets are denied during both
preparation and commit revalidation. Each person's separately provisioned approval
amount/exception permissions and each request's hard budget still apply. A cap
never grants approval authority or automatic purchasing: every order needs an
explicit authenticated confirmation of its exact revision.

Alternatives include declared replacements and products outside the standing
approved product scope. Extra quantities are derived from requested versus
purchasable pack quantities. Each rule is Allow, Ask me first or Don't allow.
Supplier minimums and pack increments always apply.

`GET /api/settings/policy` retains the current policy, version and audit history.
`PUT` accepts `expected_version` plus `rules` containing only `max_order_gross`,
`substitution`, `overbuy` and `whole_sales_units`. Product/destination scopes and
personal authority cannot be written through this endpoint. They are preserved
server-side, including a missing product scope (which still blocks purchasing).
All writes require the buyer session, exact Origin and session-bound CSRF token.

Apply additive migration `022_buyer_settings.sql` and reapply runtime grants with
the setup role before running the new API. Its restricted `save_buyer_settings`
function locks the buyer before identities, rechecks the active human role,
limits writable keys, merges existing policy, and atomically appends a version
and actor/time. Runtime identities/provisioning remain read only. The historical
manager grants and old save function are retained; the browser no longer uses them.
No existing policy, identity, approval or order is rewritten by this migration.

Stale saves return 409 and preserve the draft until an explicit reload. Unchanged
saves create no version. Changed policy invalidates pending confirmations; baskets
need fresh review and confirmation. This feature does not deploy or migrate a cluster.

## Demo policy data (Q-134 a)

Only data changed; no rule in `approval_policy.py` did. `aimo seed` now lists every non-withdrawn
product of the active catalogue in `approved_product_ids` (there is no "all products" form) and sets
`overbuy` to `allowed`; with no catalogue yet it keeps the old single product `464306`, and it still
never overwrites an existing policy. Buyers that were seeded earlier (demo-hotel and the tester buyers)
get the same change from `scripts/widen_buyer_policy.py`: report by default, `--apply` writes one new
policy version, the old rules are saved to a JSON file first, `--rollback FILE` appends them again.
Re-run it after a catalogue sync to add new products. `provision_tester.py` copies demo-hotel's current
policy, so tester buyers made afterwards inherit it.

What this loosens: a product that is not on the old one-product list no longer makes the customer
approve a "substitution", and a pack larger than the need (rounding up to whole packs) no longer needs
an overbuy approval. What stays: a line the agent declares as a substitution still needs approval,
a product outside the catalogue or withdrawn is still refused, the spending caps and the customer's
own confirmation are unchanged, and the agent cannot edit the policy (the scope is not writable
through the settings API). The scope is a list, so it grows stale when the catalogue gains products
until the script is re-run, and it makes the policy JSON large (about 17,500 ids on the full catalogue).

