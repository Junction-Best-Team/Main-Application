"""API and worker must reject missing credentials and test-only supplier mode."""

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from supplier_fixture import runtime_startup_check

from aimo import upstream
from aimo.api import create_app
from aimo.config import settings
from aimo.worker import check_readiness

ROOT = Path(__file__).resolve().parents[1]
KEY = "synthetic-supplier-key-never-real"


@pytest.fixture(autouse=True)
def production_startup_guard(monkeypatch):
    monkeypatch.setattr(upstream, "check_supplier_startup", runtime_startup_check)


@pytest.fixture
def env(monkeypatch):
    def set_env(cookies, mode, key):
        monkeypatch.setenv("SECURE_COOKIES", cookies)
        monkeypatch.setenv("UPSTREAM_MODE", mode)
        monkeypatch.setenv("VALIO_AIMO_API_KEY", key)
        monkeypatch.setenv("LLM_API_KEY", "synthetic-worker-provider-key")
        settings.cache_clear()

    yield set_env
    monkeypatch.undo()
    settings.cache_clear()


def start_api():
    with TestClient(create_app()):  # entering the client runs the lifespan (startup)
        pass


def test_hosted_live_or_auto_without_a_key_fails_the_api_at_startup(env):
    for mode in ("live", "auto"):
        env("true", mode, "")
        with pytest.raises(RuntimeError) as error:
            start_api()
        message = str(error.value)
        assert "VALIO_AIMO_API_KEY" in message and "no fixture fallback" in message


def test_hosted_live_or_auto_without_a_key_fails_the_worker_readiness_check(env):
    for mode in ("live", "auto"):
        env("true", mode, "   ")  # a blank key counts as missing
        with pytest.raises(RuntimeError, match="VALIO_AIMO_API_KEY"):
            check_readiness()


@pytest.mark.parametrize(
    "cookies,mode,key",
    [
        ("true", "live", KEY),
        ("true", "auto", KEY),
        ("false", "live", KEY),
        ("false", "auto", KEY),
    ],
)
def test_every_other_configuration_still_starts(env, cookies, mode, key):
    env(cookies, mode, key)
    start_api()
    check_readiness()


def test_the_error_never_contains_the_key(env):
    env("true", "live", "")
    with pytest.raises(RuntimeError) as error:
        start_api()
    assert KEY not in str(error.value)


def test_importing_the_app_module_never_runs_the_check():
    """scripts/export_schema.py imports aimo.api with default settings (secure cookies on, auto,
    no key); a guard that raised at import would break it and the types job."""
    environment = {
        **os.environ,
        "SECURE_COOKIES": "true",
        "UPSTREAM_MODE": "auto",
        "VALIO_AIMO_API_KEY": "",
        "PYTHONPATH": str(ROOT / "src"),
    }
    result = subprocess.run(
        [sys.executable, "-c", "import aimo.api"],
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr[-400:]


# --- the configuration shape of the real deployments (static checks) -----------------------------


def test_terraform_deployment_passes_the_mode_and_the_key_to_the_api_and_the_worker():
    main = (ROOT / "infra/kubernetes/main.tf").read_text()
    variables = (ROOT / "infra/kubernetes/variables.tf").read_text()
    assert 'SECURE_COOKIES            = "true"' in main  # a hosted deployment...
    assert "UPSTREAM_MODE             = var.upstream_mode" in main
    # ...rejects fixture configuration at provisioning as well as at startup.
    assert 'var.upstream_mode == "live"' in variables
    # the API secret carries every runtime secret except the worker-only ones; the worker's list
    # names the supplier key: so `live` has the key in both processes
    api_secret = re.search(r'resource "kubernetes_secret_v1" "runtime".*?\n}\n', main, re.S).group(
        0
    )
    excluded = re.search(r"!contains\((\[.*?\]), key\)", api_secret, re.S).group(1)
    assert "VALIO_AIMO_API_KEY" not in excluded  # the API secret carries the supplier key
    worker_secret = re.search(r'resource "kubernetes_secret_v1" "worker".*?\n}\n', main, re.S)
    assert '"VALIO_AIMO_API_KEY"' in worker_secret.group(0)


def test_compose_runs_locally_with_live_supplier_and_without_secure_cookies():
    compose = (ROOT / "compose.yaml").read_text()
    assert "UPSTREAM_MODE: ${UPSTREAM_MODE:-live}" in compose
    assert "SECURE_COOKIES: ${SECURE_COOKIES:-false}" in compose


def test_the_template_manifest_takes_its_mode_from_the_config_map():
    """deploy/kubernetes.yaml sets neither SECURE_COOKIES nor UPSTREAM_MODE: both come from the
    `aimo-config` ConfigMap, so that ConfigMap must select live and carry the key."""
    manifest = (ROOT / "deploy/kubernetes.yaml").read_text()
    assert "UPSTREAM_MODE" not in manifest and "SECURE_COOKIES" not in manifest
    assert "configMapRef: {name: aimo-config}" in manifest


@pytest.mark.parametrize("cookies", ["true", "false"])
@pytest.mark.parametrize("mode", ["live", "auto", "fixture"])
def test_api_and_worker_refuse_missing_key_in_every_configuration(env, cookies, mode):
    env(cookies, mode, "")
    for start in (start_api, check_readiness):
        with pytest.raises(RuntimeError, match="VALIO_AIMO_API_KEY"):
            start()


def test_api_and_worker_refuse_explicit_fixture_even_with_a_key(env):
    env("false", "fixture", KEY)
    for start in (start_api, check_readiness):
        with pytest.raises(RuntimeError, match="test-only"):
            start()


@pytest.mark.parametrize("mode,reason", [("fixture", "test-only"), ("auto", "VALIO_AIMO_API_KEY")])
def test_plain_application_process_has_no_fixture_supplier(mode, reason):
    code = """
import sys
from aimo import upstream
assert 'supplier_fixture' not in sys.modules
assert not hasattr(upstream, 'FixtureClient')
assert upstream.client().mode == 'live'
upstream.check_supplier_startup()
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env={**os.environ, "UPSTREAM_MODE": mode, "VALIO_AIMO_API_KEY": "",
             "PYTHONPATH": str(ROOT / "src")},
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode != 0
    assert reason in result.stderr
    assert "AssertionError" not in result.stderr
