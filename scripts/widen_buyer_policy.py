#!/usr/bin/env python3
"""Q-134 (a): widen the policy of buyers that are ALREADY seeded (demo-hotel and the tester buyers).

`aimo seed` never overwrites, so the new seed default does not reach a database that was seeded
before. This appends ONE new policy version per buyer: the same rules, the product scope widened to
every non-withdrawn product of the active catalogue (a scope is never narrowed) and overbuy "allowed".
Substitution stays "requires_approval" (a declared substitution still needs the customer's approval).

  python scripts/widen_buyer_policy.py --buyer demo-hotel --buyer rt-hotel-a            # REPORT only
  python scripts/widen_buyer_policy.py --buyer demo-hotel --buyer rt-hotel-a --apply    # write
  python scripts/widen_buyer_policy.py --buyer demo-hotel --rollback policy-backups/<file>.json

The database URL is read ONLY from the environment variable PROVISION_DATABASE_URL (the schema owner,
as provision_tester.py does; the app's runtime role cannot write policies). It is never an argument
and never printed. Run it inside the repository's Python environment (it imports aimo.policy_scope).

Safety: nothing is written without --apply. Before a write the old version number and rules are saved
to a JSON file in --backup-dir (default ./policy-backups); the write is one transaction per buyer.
Re-running is idempotent: a buyer that is already wide gets no new version. Re-run it after a catalogue
sync to add new products. Rollback appends a NEW version with the saved rules (policies are append-only,
so history keeps all versions); rolling back twice is a no-op. Not recorded in policy_changes (that
table needs a signed-in actor); the backup file and the policy version number are the record.
"""

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

ENV_NAME = "PROVISION_DATABASE_URL"


def fail(message):
    raise SystemExit(message)


def lock_current(c, buyer_id):
    buyer = c.execute("SELECT * FROM buyers WHERE id=%s FOR UPDATE", (buyer_id,)).fetchone()
    if not buyer:
        fail(f"Unknown buyer: {buyer_id}")
    row = c.execute(
        "SELECT rules FROM policies WHERE buyer_id=%s AND version=%s",
        (buyer_id, buyer["current_policy"]),
    ).fetchone()
    if not row:
        fail(f"Buyer {buyer_id} has no current policy; nothing to widen.")
    return buyer["current_policy"], row["rules"]


def append_version(c, buyer_id, rules):
    from psycopg.types.json import Jsonb

    version = c.execute(
        "SELECT coalesce(max(version),0)+1 AS n FROM policies WHERE buyer_id=%s", (buyer_id,)
    ).fetchone()["n"]
    c.execute(
        "INSERT INTO policies(buyer_id,version,rules) VALUES(%s,%s,%s)",
        (buyer_id, version, Jsonb(rules)),
    )
    c.execute("UPDATE buyers SET current_policy=%s WHERE id=%s", (version, buyer_id))
    return version


def widen(c, buyer_id, backup_dir, apply=False):
    """Widen one buyer's policy; returns what happened (or would happen without `apply`)."""
    from aimo.policy_scope import catalog_product_ids, widened_rules

    version, rules = lock_current(c, buyer_id)
    catalogue = catalog_product_ids(c)
    if not catalogue:
        fail("No active catalogue: ingest it first (the scope is built from it).")
    wide = widened_rules(rules, catalogue)
    result = {"buyer": buyer_id, "from_version": version, "to_version": None, "backup": None}
    if wide == rules:
        return result | {"action": "unchanged"}
    result["scope_before"] = len(rules.get("approved_product_ids") or [])
    result["scope_after"] = len(wide["approved_product_ids"])
    if not apply:
        return result | {"action": "would_widen"}
    backup_dir = Path(backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = backup_dir / f"policy-backup-{buyer_id}-v{version}-{stamp}.json"
    path.write_text(
        json.dumps(
            {"buyer_id": buyer_id, "version": version, "rules": rules, "saved_at": stamp}, indent=1
        )
    )
    with path.open() as handle:
        os.fsync(handle.fileno())
    return result | {
        "action": "widened",
        "to_version": append_version(c, buyer_id, wide),
        "backup": str(path),
    }


def rollback(c, buyer_id, backup_file):
    """Append the saved rules as a new current version; a no-op when they are already current."""
    saved = json.loads(Path(backup_file).read_text())
    if saved.get("buyer_id") != buyer_id:
        fail("The backup file belongs to another buyer.")
    version, rules = lock_current(c, buyer_id)
    result = {"buyer": buyer_id, "from_version": version, "to_version": None}
    if rules == saved["rules"]:
        return result | {"action": "unchanged"}
    return result | {
        "action": "rolled_back",
        "to_version": append_version(c, buyer_id, saved["rules"]),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--buyer", action="append", required=True, help="buyer id (repeatable)")
    parser.add_argument("--apply", action="store_true", help="write; without it only report")
    parser.add_argument(
        "--rollback", metavar="BACKUP_JSON", help="restore the saved rules (one buyer)"
    )
    parser.add_argument("--backup-dir", default="policy-backups")
    args = parser.parse_args(argv)
    url = os.getenv(ENV_NAME)
    if not url:
        fail(f"Set {ENV_NAME} (the schema owner's database URL) in the environment.")
    if args.rollback and len(args.buyer) != 1:
        fail("--rollback takes exactly one --buyer.")
    import psycopg
    from psycopg.rows import dict_row

    for buyer_id in args.buyer:
        try:
            with psycopg.connect(url, row_factory=dict_row) as c:  # one transaction per buyer
                result = (
                    rollback(c, buyer_id, args.rollback)
                    if args.rollback
                    else widen(c, buyer_id, args.backup_dir, apply=args.apply)
                )
        except psycopg.Error as error:  # class and primary message only, never the URL
            fail(f"{type(error).__name__}: {error.diag.message_primary or 'database error'}")
        print(json.dumps(result), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
