"""Run inside the PR #4 image, only as an explicit Terraform setup Job."""

import os
from pathlib import Path

from psycopg import sql

from aimo.cli import migrate, seed
from aimo.config import settings
from aimo.db import connection
from aimo.ingest import download, ingest_file


runtime_url = os.environ["DATABASE_URL"]
os.environ["DATABASE_URL"] = os.environ.pop("BOOTSTRAP_DATABASE_URL")
settings.cache_clear()
migrate()  # doadmin can enable pgvector; ordinary serving credentials cannot.
seed()  # Inserts missing demo rules/identities; never overwrites credentials.

role = sql.Identifier(os.environ["RUNTIME_DATABASE_USER"])
with connection() as conn:
    conn.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
    conn.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(role))
    conn.execute(
        sql.SQL("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {}").format(role)
    )
    conn.execute(
        sql.SQL("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {}").format(role)
    )
    conn.execute(sql.SQL("REVOKE ALL ON TABLE schema_migrations FROM {}").format(role))

# Import with the same restricted role and pinned model used by the app.
os.environ["DATABASE_URL"] = runtime_url
settings.cache_clear()
catalog = Path("/tmp/valio_aimo_junction26_product_data.json")
download(catalog)
ingest_file(catalog)
print("Database setup and verified full-catalog import completed.")
