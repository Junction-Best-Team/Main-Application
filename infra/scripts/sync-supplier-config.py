"""Configure live supplier lookups during an authorized release; never print credentials.

The API revalidates purchases and the worker prepares them, so both need the same
Valio key. Secret payloads travel only on kubectl stdin. Fixture mode stays available
for local tests; the release workflow requires live pricing.
"""

import base64
import json
import os
import subprocess

SECRETS = ("aimo-runtime", "aimo-worker-runtime")
LIVE = {"UPSTREAM_MODE": "live", "DEMO_CLOCK_ENABLED": "false"}


def kubectl(namespace, *args, payload=None):
    try:
        result = subprocess.run(
            ["kubectl", "-n", namespace, *args, "--request-timeout=30s"],
            input=json.dumps(payload) if payload is not None else None,
            text=True,
            capture_output=True,
            check=False,
            timeout=45,
        )
        if result.returncode:
            raise ValueError()
        return json.loads(result.stdout)
    except (OSError, subprocess.TimeoutExpired, ValueError):
        # kubectl errors and timeout exceptions may contain the submitted Secret.
        raise SystemExit("Could not configure live supplier access; credentials omitted.") from None


def sync(environ=None):
    env = os.environ if environ is None else environ
    key, namespace = env.get("VALIO_AIMO_API_KEY", "").strip(), env.get("NAMESPACE", "").strip()
    if not key or not namespace:
        raise SystemExit(
            "Set NAMESPACE and the VALIO_AIMO_API_KEY repository secret before deploying."
        )
    encoded = base64.b64encode(key.encode()).decode()
    desired = {"VALIO_AIMO_API_KEY": encoded}
    # Read every resource before changing any: a missing Secret must not leave one
    # consumer configured while the other is still using invented prices.
    config = kubectl(namespace, "get", "configmap", "aimo-config", "-o", "json")
    secrets = {name: kubectl(namespace, "get", "secret", name, "-o", "json") for name in SECRETS}
    for component, secret in zip(("api", "worker"), SECRETS):
        deployment = kubectl(namespace, "get", "deployment", f"aimo-{component}", "-o", "json")
        for container in deployment["spec"]["template"]["spec"]["containers"]:
            for entry in container.get("env", []):
                name = entry["name"]
                expected = (
                    {"name": name, "value": LIVE[name]}
                    if name in LIVE
                    else {
                        "name": name,
                        "valueFrom": {"secretKeyRef": {"name": secret, "key": name}},
                    }
                )
                if name in (*LIVE, "VALIO_AIMO_API_KEY") and entry != expected:
                    raise SystemExit(
                        f"Remove the conflicting supplier environment override in aimo-{component}."
                    )
    changed = False
    for name, current in secrets.items():
        data = current.get("data", {})
        patch = {k: v for k, v in desired.items() if data.get(k) != v}
        # envFrom Secrets override ConfigMaps. Remove any stale mode overrides.
        patch.update({k: None for k in LIVE if k in data})
        if patch:
            kubectl(
                namespace,
                "patch",
                "secret",
                name,
                "--type=merge",
                "--patch-file=/dev/stdin",
                "-o",
                "json",
                payload={"data": patch},
            )
            changed = True
    if any(config.get("data", {}).get(k) != v for k, v in LIVE.items()):
        # Enable live only after both consumers have the key. The demo clock is
        # incompatible with live supplier validity dates and must be disabled.
        kubectl(
            namespace,
            "patch",
            "configmap",
            "aimo-config",
            "--type=merge",
            "--patch-file=/dev/stdin",
            "-o",
            "json",
            payload={"data": LIVE},
        )
        changed = True
    # Verify writes without emitting Secret bodies or key hashes.
    config = kubectl(namespace, "get", "configmap", "aimo-config", "-o", "json")
    verified = all(config.get("data", {}).get(k) == v for k, v in LIVE.items())
    for name in SECRETS:
        data = kubectl(namespace, "get", "secret", name, "-o", "json").get("data", {})
        verified = (
            verified
            and data.get("VALIO_AIMO_API_KEY") == encoded
            and not any(k in data for k in LIVE)
        )
    if not verified:
        raise SystemExit("Live supplier configuration did not verify; credentials omitted.")
    print("Verified live supplier configuration for the API and worker.")
    return changed


if __name__ == "__main__":
    changed = sync()
    if output := os.environ.get("GITHUB_OUTPUT"):
        with open(output, "a") as stream:
            stream.write(f"changed={str(changed).lower()}\n")
