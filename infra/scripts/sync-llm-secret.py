"""Merge only LLM settings into the existing app Secret during authorized releases.

Credentials travel on kubectl stdin, never argv, files, stdout or error output.
No resource creation, application restart or deployment activation.
"""

import base64
import json
import os
import subprocess
from urllib.parse import urlsplit


def sync(environ=None):
    env = os.environ if environ is None else environ
    key, namespace = env.get("LLM_API_KEY", ""), env.get("NAMESPACE", "")
    if not key.strip():
        print("No LLM credential supplied; preserving existing runtime settings.")
        return False
    base_url = env.get("LLM_BASE_URL", "https://openrouter.ai/api/v1")
    model = env.get("LLM_MODEL", "openai/gpt-4.1-mini")
    try:
        url = urlsplit(base_url)
        valid_url = url.scheme == "https" and url.hostname and not (
            url.username or url.password or url.query or url.fragment
        )
        _ = url.port
    except ValueError:
        valid_url = False
    if not key.strip() or not namespace.strip() or not model.strip() or not valid_url:
        raise SystemExit("Set NAMESPACE, LLM_API_KEY, a valid HTTPS LLM_BASE_URL and LLM_MODEL.")
    desired = {"LLM_API_KEY": key, "LLM_BASE_URL": base_url, "LLM_MODEL": model}
    try:
        current = subprocess.run([
            "kubectl", "-n", namespace, "get", "secret", "aimo-runtime", "-o", "json",
            "--request-timeout=30s",
        ], text=True, capture_output=True, check=False, timeout=45)
        if current.returncode:
            raise ValueError()
        data = json.loads(current.stdout).get("data", {})
        if all(data.get(k) == base64.b64encode(v.encode()).decode() for k, v in desired.items()):
            print("Runtime LLM settings are unchanged.")
            return False
    except (OSError, subprocess.TimeoutExpired, ValueError, AttributeError):
        raise SystemExit("Could not read the existing runtime Secret; provider omitted.") from None
    body = json.dumps({"stringData": desired})
    try:
        result = subprocess.run([
            "kubectl", "-n", namespace, "patch", "secret", "aimo-runtime", "--type=merge",
            "--patch-file=/dev/stdin", "--request-timeout=30s",
        ], input=body, text=True, capture_output=True, check=False, timeout=45)
    except (OSError, subprocess.TimeoutExpired):
        raise SystemExit("Runtime Secret update failed or timed out; provider omitted.") from None
    if result.returncode:
        # A kubectl/API error can contain the submitted object; never relay it.
        raise SystemExit("Could not configure the existing aimo-runtime Secret; provider omitted.")
    print("Configured server-side LLM settings in the existing runtime Secret.")
    return True


if __name__ == "__main__":
    changed = sync()
    if output := os.environ.get("GITHUB_OUTPUT"):
        with open(output, "a") as stream:
            stream.write(f"changed={str(changed).lower()}\n")
