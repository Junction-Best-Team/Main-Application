"""Merge only LLM settings into the existing app Secret during authorized releases.

Credentials travel on kubectl stdin, never argv, files, stdout or error output.
No resource creation, application restart or deployment activation.
"""

import json
import os
import subprocess
from urllib.parse import urlsplit


def sync(environ=None):
    env = os.environ if environ is None else environ
    key, namespace = env.get("LLM_API_KEY", ""), env.get("NAMESPACE", "")
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
    body = json.dumps({"stringData": {
        "LLM_API_KEY": key, "LLM_BASE_URL": base_url, "LLM_MODEL": model,
    }})
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


if __name__ == "__main__":
    sync()
