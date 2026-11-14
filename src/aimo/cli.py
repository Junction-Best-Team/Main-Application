import argparse
import json
import os
import secrets
from pathlib import Path

from aimo.auth import hasher
from aimo.db import connection, fingerprint, js
from aimo.observability import configure_logging
from aimo.schemas import PolicyRules

ROOT = Path(__file__).resolve().parents[2]


def migrate(runtime_role=None, catalog_role=None):
    if catalog_role and catalog_role == runtime_role:
        raise ValueError("The catalog sync role must differ from the runtime role")
    with connection() as c:
        # Serialize ledger checks, DDL and grants in one atomic transaction.
        # Keep this key stable across bootstrap, CLI and release Job callers.
        c.execute("SELECT pg_advisory_xact_lock(893018)")
        c.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations(version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
        )
        paths = sorted((ROOT / "migrations").glob("*.sql"))
        if not paths:
            raise RuntimeError("No packaged migration files found")
        for path in paths:
            if not c.execute(
                "SELECT 1 FROM schema_migrations WHERE version=%s", (path.name,)
            ).fetchone():
                print(f"Applying migration {path.name}", flush=True)
                c.execute(path.read_text())
                c.execute("INSERT INTO schema_migrations(version) VALUES(%s)", (path.name,))
            else:
                print(f"Skipping applied migration {path.name}", flush=True)
        if runtime_role:
            from aimo.permissions import configure_runtime_role

            configure_runtime_role(c, runtime_role)
        if catalog_role:
            from aimo.permissions import configure_catalog_sync_role

            configure_catalog_sync_role(c, catalog_role)
    grants = [
        name for name, role in (("runtime", runtime_role), ("catalog sync", catalog_role)) if role
    ]
    print(
        "Migrations committed" + (f" with {' and '.join(grants)} grants." if grants else "."),
        flush=True,
    )


def seed():
    from dotenv import load_dotenv

    load_dotenv()
    password = os.getenv("DEMO_BUYER_PASSWORD")
    if not password or len(password) < 12:
        raise ValueError("Set private DEMO_BUYER_PASSWORD (12+) before seed")
    rules = {
        "currency": "EUR",
        "destinations": ["hotel-helsinki"],
        "substitution": "requires_approval",
        "overbuy": "requires_approval",
        "whole_sales_units": True,
        "approved_product_ids": ["464306"],
    }
    with connection() as c:
        c.execute("INSERT INTO buyers VALUES('demo-hotel','123',1) ON CONFLICT DO NOTHING")
        c.execute("SELECT id FROM buyers WHERE id='demo-hotel' FOR UPDATE")
        c.execute(
            "INSERT INTO policies(buyer_id,version,rules) VALUES('demo-hotel',1,%s) ON CONFLICT DO NOTHING",
            (js(rules),),
        )
        c.execute(
            "INSERT INTO identities VALUES('demo-agent','demo-hotel','agent',true,%s,%s) ON CONFLICT DO NOTHING",
            (
                "!retained-demo-agent-no-bearer-login",
                js({}),
            ),
        )
        c.execute(
            """INSERT INTO identities(id,buyer_id,role,active,credential_hash,authority)
            SELECT 'internal:' || md5(id),id,'agent',true,'!internal-no-bearer-login',
            '{}'::jsonb FROM buyers
            WHERE id='demo-hotel' ON CONFLICT DO NOTHING"""
        )
        c.execute(
            """INSERT INTO internal_agents SELECT buyer_id,id FROM identities
            WHERE id='internal:' || md5('demo-hotel') ON CONFLICT DO NOTHING"""
        )
        c.execute(
            "INSERT INTO identities VALUES('buyer','demo-hotel','approver',true,%s,%s) ON CONFLICT DO NOTHING",
            (
                hasher.hash(password),
                js(
                    {
                        "currency": "EUR",
                        "max_gross": "5000.00",
                        "exceptions": ["substitution", "overbuy"],
                    }
                ),
            ),
        )


def set_product_scope(buyer_id, product_ids):
    """Privileged provisioning only; no browser/agent policy-editing surface."""
    with connection() as c:
        buyer = c.execute("SELECT * FROM buyers WHERE id=%s FOR UPDATE", (buyer_id,)).fetchone()
        if not buyer:
            raise ValueError("Unknown buyer")
        policy = c.execute(
            "SELECT * FROM policies WHERE buyer_id=%s AND version=%s",
            (buyer_id, buyer["current_policy"]),
        ).fetchone()
        current = {k: v for k, v in policy["rules"].items() if k != "autonomous_limit"}
        rules = current | {"approved_product_ids": sorted(set(product_ids))}
        PolicyRules.model_validate(rules)
        if rules == current:
            return policy["version"]
        version = c.execute(
            "SELECT max(version)+1 AS version FROM policies WHERE buyer_id=%s", (buyer_id,)
        ).fetchone()["version"]
        c.execute(
            "INSERT INTO policies(buyer_id,version,rules) VALUES(%s,%s,%s)",
            (buyer_id, version, js(rules)),
        )
        c.execute("UPDATE buyers SET current_policy=%s WHERE id=%s", (version, buyer_id))
        return version


def configure():
    path = Path(".env")
    if path.exists():
        raise ValueError(".env exists; preserve its settings and configure missing keys explicitly")
    data = (
        Path(".env.example")
        .read_text()
        .replace("APPROVAL_SESSION_SECRET=", "APPROVAL_SESSION_SECRET=" + secrets.token_urlsafe(48))
        .replace("DEMO_BUYER_PASSWORD=", "DEMO_BUYER_PASSWORD=" + secrets.token_urlsafe(24))
    )
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(data)
    print("Private local credentials written to .env (mode 0600); values are not printed.")


def main():
    configure_logging()
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("configure", "seed", "serve", "worker", "fixture-catalog", "cache-model"):
        sub.add_parser(name)
    migration = sub.add_parser("migrate")
    migration.add_argument("--runtime-role", help="Reapply restricted runtime grants atomically")
    migration.add_argument(
        "--catalog-role",
        default=os.getenv("CATALOG_SYNC_DATABASE_USER") or None,
        help="Reapply catalog-sync-only grants (default: $CATALOG_SYNC_DATABASE_USER)",
    )
    scope = sub.add_parser(
        "set-product-scope", help="Privileged provisioning: version a buyer's approved product IDs"
    )
    scope.add_argument("--buyer", required=True)
    scope.add_argument("--product-id", action="append", required=True)
    recipes = sub.add_parser("ingest-recipes", help="Explicit versioned UniTools recipe import")
    recipes.add_argument("--file", type=Path, required=True)
    recipes.add_argument("--expected-sha256", required=True)
    recipes.add_argument("--review-file", type=Path)
    evidence = sub.add_parser(
        "import-recipe-product-evidence", help="Privileged reviewed product annotations"
    )
    evidence.add_argument("--file", type=Path, required=True)
    ing = sub.add_parser("ingest")
    ing.add_argument("--file", type=Path, required=True)
    ing.add_argument("--download", action="store_true")
    ing.add_argument(
        "--stage", action="store_true", help="Import without replacing the active catalog"
    )
    purge = sub.add_parser(
        "purge-proposals",
        help="Remove proposals and approvals that never became orders (CNF-021); orders are kept",
    )
    purge.add_argument(
        "--older-than-days",
        type=int,
        help="Days after the current revision expired (default: $UNFINISHED_PROPOSAL_RETENTION_DAYS, 30)",
    )
    purge.add_argument("--dry-run", action="store_true", help="Count only; delete nothing")
    activation = sub.add_parser("activate-catalog", help="Explicit catalog cutover or rollback")
    activation.add_argument("--generation", required=True)
    from aimo.ingest import CATALOG_PRODUCT_COUNT, CATALOG_SHA256

    ing.add_argument("--expected-count", type=int, default=CATALOG_PRODUCT_COUNT)
    ing.add_argument("--expected-sha256", default=CATALOG_SHA256)
    sync = sub.add_parser(
        "sync-catalog",
        help="Unattended: obtain the approved snapshot, skip if current, else import and activate",
    )
    sync.add_argument("--file", type=Path, help="Use a local snapshot instead of downloading")
    sync.add_argument("--expected-count", type=int, default=CATALOG_PRODUCT_COUNT)
    sync.add_argument("--expected-sha256", default=CATALOG_SHA256)
    args = parser.parse_args()
    if args.command == "configure":
        configure()
    elif args.command == "migrate":
        migrate(runtime_role=args.runtime_role, catalog_role=args.catalog_role)
    elif args.command == "seed":
        seed()
    elif args.command == "set-product-scope":
        print(
            json.dumps(
                {
                    "buyer_id": args.buyer,
                    "policy_version": set_product_scope(args.buyer, args.product_id),
                }
            )
        )
    elif args.command == "purge-proposals":
        from datetime import timedelta

        from aimo import approval_workflow
        from aimo.config import settings

        if args.older_than_days is not None and args.older_than_days < 1:
            parser.error("--older-than-days must be at least 1")
        days = args.older_than_days or settings().unfinished_proposal_retention_days
        print(
            json.dumps(
                approval_workflow.purge_unfinished_proposals(
                    timedelta(days=days), dry_run=args.dry_run
                )
            )
        )
    elif args.command == "activate-catalog":
        from aimo.ingest import activate_catalog

        print(json.dumps(activate_catalog(args.generation)))
    elif args.command == "serve":
        import uvicorn

        from aimo.config import settings

        uvicorn.run(
            "aimo.api:app",
            host="0.0.0.0",
            port=8000,
            forwarded_allow_ips=settings().forwarded_allow_ips,
            access_log=False,
        )
    elif args.command == "worker":
        from aimo.worker import main as worker_main

        worker_main()
    elif args.command == "cache-model":
        from aimo.search import model

        model()
        print("Pinned model cached.")
    elif args.command == "fixture-catalog":
        from aimo.fixtures import fixture_facts
        from aimo.ingest import publish

        data = fixture_facts()
        print(json.dumps(publish(data, "authored-fixtures-v1", fingerprint(data))))
    elif args.command == "ingest-recipes":
        from aimo.recipe_import import ingest_recipes

        print(json.dumps(ingest_recipes(args.file, args.expected_sha256, args.review_file)))
    elif args.command == "import-recipe-product-evidence":
        from aimo.recipe_import import import_product_evidence

        print(json.dumps(import_product_evidence(args.file)))
    elif args.command == "sync-catalog":
        from aimo.ingest import run_sync

        result, code = run_sync(
            file=args.file, expected_sha=args.expected_sha256, expected_count=args.expected_count
        )
        print(json.dumps(result), flush=True)
        if code:
            raise SystemExit(code)
    elif args.command == "ingest":
        from aimo.ingest import download, ingest_file

        if args.download:
            download(args.file)
        print(
            json.dumps(
                ingest_file(
                    args.file, args.expected_count, args.expected_sha256, activate=not args.stage
                )
            )
        )


if __name__ == "__main__":
    main()
