#!/usr/bin/env python3
"""Run only schema migrations/grants in a bounded release-image Kubernetes Job."""

import json
import os
import re
import subprocess
import sys
import time
from uuid import uuid4

DEADLINE_SECONDS = 300
WAIT_SECONDS = 360
TTL_SECONDS = 86400


def job_manifest(namespace, image, name, pull_secrets):
    if not re.fullmatch(r"ghcr.io/[a-z0-9._/-]+@sha256:[a-f0-9]{64}", image):
        raise ValueError("Migration image must be an immutable GHCR digest")
    return {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {"name": name, "namespace": namespace, "labels": {"app": "aimo-migrate"}},
        "spec": {
            "backoffLimit": 0,
            "activeDeadlineSeconds": DEADLINE_SECONDS,
            "ttlSecondsAfterFinished": TTL_SECONDS,
            "template": {
                "metadata": {"labels": {"app": "aimo-migrate"}},
                "spec": {
                    "restartPolicy": "Never",
                    "automountServiceAccountToken": False,
                    "terminationGracePeriodSeconds": 10,
                    "imagePullSecrets": pull_secrets,
                    "securityContext": {
                        "runAsNonRoot": True,
                        "runAsUser": 10001,
                        "runAsGroup": 10001,
                        "fsGroup": 10001,
                        "seccompProfile": {"type": "RuntimeDefault"},
                    },
                    "containers": [
                        {
                            "name": "migrate",
                            "image": image,
                            "args": ["migrate", "--runtime-role", "$(RUNTIME_DATABASE_USER)"],
                            "env": [
                                {
                                    "name": key,
                                    "valueFrom": {
                                        "secretKeyRef": {
                                            "name": "aimo-migration",
                                            "key": key,
                                        }
                                    },
                                }
                                for key in ("DATABASE_URL", "RUNTIME_DATABASE_USER")
                            ]
                            + [
                                # Optional: `aimo migrate` also refreshes catalog-sync-only
                                # grants when the release Secret names that role.
                                {
                                    "name": "CATALOG_SYNC_DATABASE_USER",
                                    "valueFrom": {
                                        "secretKeyRef": {
                                            "name": "aimo-migration",
                                            "key": "CATALOG_SYNC_DATABASE_USER",
                                            "optional": True,
                                        }
                                    },
                                },
                                {"name": "PGOPTIONS", "value": "-c statement_timeout=240000"},
                            ],
                            "resources": {
                                "requests": {"cpu": "100m", "memory": "128Mi"},
                                "limits": {"cpu": "1", "memory": "256Mi"},
                            },
                            "securityContext": {
                                "allowPrivilegeEscalation": False,
                                "readOnlyRootFilesystem": True,
                                "capabilities": {"drop": ["ALL"]},
                            },
                            "volumeMounts": [
                                {
                                    "name": "database-ca",
                                    "mountPath": "/etc/aimo-db",
                                    "readOnly": True,
                                }
                            ],
                        }
                    ],
                    "volumes": [
                        {
                            "name": "database-ca",
                            "secret": {
                                "secretName": "aimo-database-ca",
                            },
                        }
                    ],
                },
            },
        },
    }


def kubectl(namespace, *args, payload=None):
    result = subprocess.run(
        ["kubectl", "-n", namespace, "--request-timeout=10s", *args],
        input=json.dumps(payload) if payload is not None else None,
        text=True,
        capture_output=True,
        timeout=20,
    )
    if result.returncode:
        # Do not include objects, environment values or connection details in errors.
        raise RuntimeError(f"kubectl {args[0]} failed")
    return result.stdout


def diagnostics(namespace, name):
    for args in (
        ("logs", f"job/{name}", "--all-containers=true", "--tail=100"),
        (
            "get",
            "pods",
            "-l",
            f"job-name={name}",
            "-o",
            "custom-columns=NAME:.metadata.name,PHASE:.status.phase,REASON:.status.reason",
        ),
    ):
        try:
            print(kubectl(namespace, *args), flush=True)
        except (RuntimeError, subprocess.TimeoutExpired):
            print(f"Could not collect migration {args[0]} diagnostics.", file=sys.stderr)


def run(namespace, image):
    deployment = json.loads(kubectl(namespace, "get", "deployment", "aimo-api", "-o", "json"))
    pull_secrets = deployment["spec"]["template"]["spec"].get("imagePullSecrets", [])
    # Fresh name on every invocation; never reuse a completed same-image Job.
    name = "aimo-migrate-" + uuid4().hex[:20]
    manifest = job_manifest(namespace, image, name, pull_secrets)
    terminal = successful = False
    print(f"Running migration Job {name} with {image}", flush=True)
    try:
        # Name is known before creation so an ambiguous API timeout can be cleaned up.
        kubectl(namespace, "create", "-f", "-", payload=manifest)
        deadline = time.monotonic() + WAIT_SECONDS
        while time.monotonic() < deadline:
            job = json.loads(kubectl(namespace, "get", "job", name, "-o", "json"))
            conditions = {
                c["type"]
                for c in job.get("status", {}).get("conditions", [])
                if c["status"] == "True"
            }
            if "Failed" in conditions:
                terminal = True
                reason = next(
                    (
                        c.get("reason", "Failed")
                        for c in job["status"]["conditions"]
                        if c["type"] == "Failed" and c["status"] == "True"
                    ),
                    "Failed",
                )
                raise RuntimeError(
                    f"Migration Job failed ({reason}); application images were not changed"
                )
            if "Complete" in conditions:
                terminal = successful = True
                print("Migration Job succeeded; schema and runtime grants committed.", flush=True)
                return
            time.sleep(2)
        raise RuntimeError("Migration Job timed out; application images were not changed")
    finally:
        diagnostics(namespace, name)
        if successful or not terminal:
            # Cancel pending/running Jobs on API errors or waiter timeout. The server
            # deadline still bounds execution if the runner disappears completely.
            try:
                kubectl(namespace, "delete", "job", name, "--ignore-not-found=true", "--wait=false")
            except (RuntimeError, subprocess.TimeoutExpired):
                print(
                    f"Could not delete {name}; deadline/TTL cleanup remains enabled.",
                    file=sys.stderr,
                )
        else:
            print(f"Failed Job {name} retained for diagnostics (24-hour TTL).", file=sys.stderr)


def main():
    try:
        run(os.environ["NAMESPACE"], os.environ["IMAGE"])
    except (KeyError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(f"Release migration stopped: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
