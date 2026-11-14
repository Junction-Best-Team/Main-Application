# Buyer policy settings

The owner's 2026-11-14 request replaces command-line product-scope management with
`/settings`, reached through Account Settings in the desktop sidebar or mobile menu.
This supersedes the earlier provisioning-only policy-editor deferral.
Agents still read `get_purchase_policy`; they cannot change policies or permissions.

Signed-in buyers can view their account's current rules, personal approval authority
and recent policy changes. A designated policy manager can save approved catalog
product codes, allowed destinations, substitution/overbuy behavior and whole-sales-unit
rounding. Currency stays EUR. An empty approved list has no standing approved products;
all products follow the substitution rule. Missing scope blocks purchasing.

`GET` / `PUT /api/settings/policy` derive the account and actor from the browser session.
Writes require the same Origin and session CSRF protections as purchase confirmation.
Only active human approvers listed in `policy_managers` may save. This permission is
separate from spending authority: Settings cannot edit personal spending limits or
exception permissions. A policy edit never grants purchase confirmation.

Migration 014 creates manager grants and append-only `policy_changes` attribution.
It designates the existing `buyer` of `demo-hotel`; `seed` does the same for fresh setup.
Other manager grants remain privileged operator provisioning; permission maintenance
must take the buyer lock before changing manager or identity rows. Apply the migration and
runtime grants with the setup role before releasing the new API. Readiness probes
check its tables, immutable change trigger and save function. No reset or catalog
import is needed. No cluster migration or deployment is part of this feature task.

The runtime role retains no direct policy, identity, manager-grant or buyer-provisioning
write permission. A restricted `SECURITY DEFINER` function saves policy versions, locks
the buyer before identities, rechecks the active manager and records actor/time. Its
search path is fixed to the installation schema and `pg_temp`; PUBLIC cannot execute
it. The browser handler validates typed rules and checks product codes against the
active catalog. The function is not an agent tool.

Saves include the expected current version. Stale saves return 409 without overwriting
changes; the page preserves the draft until the buyer reloads. Identical current-version
saves create no new version. Changed rules append a new immutable policy and attribution
row atomically with the buyer's current-version pointer. Old revisions and orders remain
intact. Existing purchasing checks reject old policy confirmations and require a refreshed
basket revision with a new explicit customer confirmation.

The product-scope CLI is removed. Initial account/identity seeding and administrative
approval-permission setup remain operator operations.
