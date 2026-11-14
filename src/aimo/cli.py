import argparse
import json
import os
import secrets
from pathlib import Path

from aimo.auth import digest, hasher
from aimo.db import connection, fingerprint, js

ROOT = Path(__file__).resolve().parents[2]


def migrate():
    with connection() as c:
        c.execute("SELECT pg_advisory_xact_lock(893018)")
        c.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations(version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
        )
        for path in sorted((ROOT / "migrations").glob("*.sql")):
            if not c.execute(
                "SELECT 1 FROM schema_migrations WHERE version=%s", (path.name,)
            ).fetchone():
                c.execute(path.read_text())
                c.execute("INSERT INTO schema_migrations(version) VALUES(%s)", (path.name,))


def seed():
    from dotenv import load_dotenv

    load_dotenv()
    token, password = os.getenv("DEMO_AGENT_TOKEN"), os.getenv("DEMO_BUYER_PASSWORD")
    if not token or not password or len(token) < 24 or len(password) < 12:
        raise ValueError(
            "Set private DEMO_AGENT_TOKEN (24+) and DEMO_BUYER_PASSWORD (12+) before seed"
        )
    rules = {
        "currency": "EUR",
        "autonomous_limit": "1500.00",
        "destinations": ["hotel-helsinki"],
        "substitution": "requires_approval",
        "overbuy": "requires_approval",
        "whole_sales_units": True,
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
            (digest(token), js({"currency": "EUR", "autonomous_limit": "1500.00"})),
        )
        c.execute(
            "INSERT INTO identities VALUES('buyer','demo-hotel','approver',true,%s,%s) ON CONFLICT DO NOTHING",
            (
                hasher.hash(password),
                js(
                    {
                        "currency": "EUR",
                        "max_gross": "5000.00",
                        "exceptions": ["spend", "substitution", "overbuy"],
                    }
                ),
            ),
        )


def configure():
    path = Path(".env")
    if path.exists():
        raise ValueError(".env exists; preserve its settings and configure missing keys explicitly")
    data = (
        Path(".env.example")
        .read_text()
        .replace("APPROVAL_SESSION_SECRET=", "APPROVAL_SESSION_SECRET=" + secrets.token_urlsafe(48))
        .replace("DEMO_AGENT_TOKEN=", "DEMO_AGENT_TOKEN=" + secrets.token_urlsafe(32))
        .replace("DEMO_BUYER_PASSWORD=", "DEMO_BUYER_PASSWORD=" + secrets.token_urlsafe(24))
    )
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(data)
    print("Private local credentials written to .env (mode 0600); values are not printed.")


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("configure", "migrate", "seed", "serve", "fixture-catalog", "cache-model"):
        sub.add_parser(name)
    ing = sub.add_parser("ingest")
    ing.add_argument("--file", type=Path, required=True)
    ing.add_argument("--download", action="store_true")
    ing.add_argument("--expected-count", type=int, default=17546)
    from aimo.ingest import CATALOG_SHA256

    ing.add_argument("--expected-sha256", default=CATALOG_SHA256)
    args = parser.parse_args()
    if args.command == "configure":
        configure()
    elif args.command == "migrate":
        migrate()
    elif args.command == "seed":
        seed()
    elif args.command == "serve":
        import uvicorn

        uvicorn.run("aimo.api:app", host="0.0.0.0", port=8000)
    elif args.command == "cache-model":
        from aimo.search import model

        model()
        print("Pinned model cached.")
    elif args.command == "fixture-catalog":
        from aimo.fixtures import fixture_facts
        from aimo.ingest import publish

        data = fixture_facts()
        print(json.dumps(publish(data, "authored-fixtures-v1", fingerprint(data))))
    elif args.command == "ingest":
        from aimo.ingest import download, ingest_file

        if args.download:
            download(args.file)
        print(json.dumps(ingest_file(args.file, args.expected_count, args.expected_sha256)))


if __name__ == "__main__":
    main()
