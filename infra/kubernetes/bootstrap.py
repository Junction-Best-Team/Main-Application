"""Run in the worker image, only as an explicit Terraform setup Job.

Migrates with the setup role, seeds missing demo identities/policies and applies the
restricted runtime and catalog-sync grants. It does not import the catalog: the first
catalog population is a run of the same `aimo-catalog-sync` Job template (infra/README.md).
"""

import os

from aimo.cli import migrate, seed
from aimo.config import settings


def main():
    os.environ["DATABASE_URL"] = os.environ.pop("BOOTSTRAP_DATABASE_URL")
    settings.cache_clear()
    # doadmin can enable pgvector; ordinary serving credentials cannot. Grants commit
    # atomically with the schema.
    migrate(
        runtime_role=os.environ["RUNTIME_DATABASE_USER"],
        catalog_role=os.environ.get("CATALOG_SYNC_DATABASE_USER") or None,
    )
    seed()  # Inserts missing demo rules/identities; never overwrites credentials.
    print("Database setup completed. Populate the catalog with the aimo-catalog-sync Job.")


if __name__ == "__main__":
    main()
