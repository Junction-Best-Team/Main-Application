#!/usr/bin/env python3
"""Create private Kubernetes inputs from provisioned cloud outputs; never applies."""

import argparse
import json
import os
import secrets
import subprocess
from pathlib import Path


def write_private(path, content):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write(content)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cloud-directory", type=Path, required=True)
    parser.add_argument("--image", required=True)
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
        outputs = {key: entry["value"] for key, entry in json.loads(result.stdout).items()}
        values = {
            "kubeconfig_path": str(config),
            "image": args.image,
            "hostname": args.hostname,
            "acme_email": args.acme_email,
            "database_url": outputs["database_url"],
            "database_ca": outputs["database_ca"],
            "session_secret": secrets.token_urlsafe(48),
            "app_replicas": 0,
            "bootstrap_generation": None,
            "bootstrap_credentials": {
                "database_url": outputs["bootstrap_database_url"],
                "database_user": outputs["database_user"],
                "agent_token": secrets.token_urlsafe(32),
                "buyer_password": secrets.token_urlsafe(24),
            },
        }
        kubeconfig = outputs["kubeconfig"]
    except (ValueError, KeyError, TypeError):
        parser.error("Missing portable cloud outputs; see infra/README.md for the required contract.")
    write_private(config, kubeconfig)
    write_private(inputs, json.dumps(values, indent=2) + "\n")
    print("Created private kubeconfig and runtime.auto.tfvars.json (0600); no resources changed.")


if __name__ == "__main__":
    main()
