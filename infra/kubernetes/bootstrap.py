"""Run inside the PR #4 image, only as an explicit Terraform setup Job."""

import os
from pathlib import Path

from aimo.cli import migrate, seed
from aimo.config import settings
from aimo.db import connection
from aimo.ingest import download, ingest_file
from aimo.permissions import configure_runtime_role


def main():
    runtime_url = os.environ["DATABASE_URL"]
    os.environ["DATABASE_URL"] = os.environ.pop("BOOTSTRAP_DATABASE_URL")
    settings.cache_clear()
    migrate()  # doadmin can enable pgvector; ordinary serving credentials cannot.
    seed()  # Inserts missing demo rules/identities; never overwrites credentials.
    with connection() as conn:
        configure_runtime_role(conn, os.environ["RUNTIME_DATABASE_USER"])

    # Import with the same restricted role and pinned model used by the app.
    os.environ["DATABASE_URL"] = runtime_url
    settings.cache_clear()
    catalog = Path("/tmp/valio_aimo_junction26_product_data.json")
    download(catalog)
    ingest_file(catalog)
    print("Database setup and verified full-catalog import completed.")


if __name__ == "__main__":
    main()
