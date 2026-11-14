#!/usr/bin/env python3
"""Create private Kubernetes inputs from provisioned cloud outputs; never applies."""

import argparse
import json
import os
import secrets
import subprocess
from pathlib import Path


# Shared interface for every cloud provisioning stack. Cloud-specific resource
# IDs and API tokens never cross this boundary into the Kubernetes deployment.
REQUIRED_CLOUD_OUTPUTS = (
    "kubeconfig",
    "database_url",
    "bootstrap_database_url",
    "database_user",
    "database_ca",
)
# Optional pair: a dedicated catalog-sync role for the scheduled ingestion Job. A stack that
# omits both still works; the CronJob then stays disabled until an operator supplies one.
OPTIONAL_CLOUD_OUTPUTS = ("catalog_sync_database_url", "catalog_sync_database_user")


def read_cloud_outputs(raw):
    data = json.loads(raw)
    outputs = {}
    for name in REQUIRED_CLOUD_OUTPUTS + OPTIONAL_CLOUD_OUTPUTS:
        if name in OPTIONAL_CLOUD_OUTPUTS and name not in data:
            continue
        value = data[name]["value"]
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Cloud output must be a nonempty string")
        outputs[name] = value
    if sum(name in outputs for name in OPTIONAL_CLOUD_OUTPUTS) == 1:
        raise ValueError("Catalog sync outputs must be provided together")
    return outputs


def write_private(path, content):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write(content)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cloud-directory", type=Path, required=True)
    parser.add_argument("--image", required=True, help="API image")
    parser.add_argument("--worker-image", required=True)
    parser.add_argument("--frontend-image", required=True)
    parser.add_argument("--hostname", required=True)
    parser.add_argument("--acme-email", required=True)
    args = parser.parse_args()
    runtime = Path(__file__).resolve().parents[1] / "kubernetes"
    config = runtime / "kubeconfig.generated.yaml"
    inputs = runtime / "runtime.auto.tfvars.json"
    if config.exists() or inputs.exists():
        parser.error("Private runtime inputs already exist; preserve credentials and edit them explicitly.")
    result = subprocess.run(
        ["terraform", f"-chdir={args.cloud_directory.resolve()}", "output", "-json"],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        parser.error("Cannot read cloud outputs; provision the approved cloud plan first.")
    try:
        outputs = read_cloud_outputs(result.stdout)
        values = {
            "kubeconfig_path": str(config),
            "image": args.image,
            "worker_image": args.worker_image,
            "frontend_image": args.frontend_image,
            "hostname": args.hostname,
            "acme_email": args.acme_email,
            "database_url": outputs["database_url"],
            "database_ca": outputs["database_ca"],
            "session_secret": secrets.token_urlsafe(48),
            "app_replicas": 0,
            "migration_credentials": {
                "database_url": outputs["bootstrap_database_url"],
                "database_user": outputs["database_user"],
            },
            "bootstrap_generation": None,
            "bootstrap_credentials": {
                "database_url": outputs["bootstrap_database_url"],
                "database_user": outputs["database_user"],
                "buyer_password": secrets.token_urlsafe(24),
            },
        }
        if "catalog_sync_database_url" in outputs:
            role = outputs["catalog_sync_database_user"]
            values["catalog_sync_database_url"] = outputs["catalog_sync_database_url"]
            values["migration_credentials"]["catalog_sync_database_user"] = role
            values["bootstrap_credentials"]["catalog_sync_database_user"] = role
        kubeconfig = outputs["kubeconfig"]
    except (ValueError, KeyError, TypeError):
        parser.error("Invalid portable cloud outputs; see infra/README.md for the required contract.")
    write_private(config, kubeconfig)
    write_private(inputs, json.dumps(values, indent=2) + "\n")
    print("Created private kubeconfig and runtime.auto.tfvars.json (0600); no resources changed.")


if __name__ == "__main__":
    main()
