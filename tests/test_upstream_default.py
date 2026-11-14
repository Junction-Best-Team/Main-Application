"""JNP3-SUP-005: fixture mode only in tests and explicit offline runs; live otherwise.

Owner decision 2026-11-14: the deployment default must be LIVE. On develop `efedf8f` the code and
`.env.example` default to `auto` (live with a key, labelled fixture without one); whether a
deployment without a key may fall back to fixtures is an open owner question, so it is not decided
here. The Kubernetes default is still an explicit `fixture` and belongs to person 1: that check is a
strict xfail that turns into an error when it changes (remove the marker then). No supplier call.
"""

import re
from pathlib import Path

import pytest

from aimo import upstream
from aimo.config import Settings
from aimo.db import Problem
from aimo.service import Service
from aimo.upstream import FixtureClient, ValioClient

ROOT = Path(__file__).resolve().parents[1]
WAITING = "SUP-005: infra default is an explicit fixture; waiting for person 1 to change it"


def configured(monkeypatch, **values):
    monkeypatch.delenv("UPSTREAM_MODE", raising=False)
    cfg = Settings(_env_file=None, **values)
    monkeypatch.setattr(upstream, "settings", lambda: cfg)
    return cfg


@pytest.mark.xfail(strict=True, reason=WAITING)
def test_kubernetes_variable_default_is_not_an_explicit_fixture():
    """Deployment default must not be an explicit fixture (owner: live; `auto` is undecided)."""
    block = re.search(
        r'variable "upstream_mode" \{(.*?)\n\}',
        (ROOT / "infra/kubernetes/variables.tf").read_text(),
        re.S,
    )
    assert block and not re.search(r'default\s*=\s*"fixture"', block.group(1))


def test_code_and_env_example_default_to_auto_not_fixture(monkeypatch):
    """Records the state on develop `efedf8f`; whether `auto` is acceptable is the owner's call."""
    assert configured(monkeypatch).upstream_mode == "auto"
    assert re.search(r"^UPSTREAM_MODE=auto\s*$", (ROOT / ".env.example").read_text(), re.M)


def test_auto_without_a_key_is_logged_and_every_result_is_labelled_fixture(monkeypatch, caplog):
    configured(monkeypatch, upstream_mode="auto", valio_aimo_api_key="")
    with caplog.at_level("WARNING", logger="aimo.upstream"):
        service = Service()
    assert "FIXTURE" in caplog.text
    from datetime import date, timedelta

    from aimo.schemas import LookupRequest

    identity = {"id": "demo-agent", "buyer_id": "demo-hotel", "role": "agent"}
    result = service.check_price_and_availability(
        identity,
        LookupRequest(product_ids=["464306"], delivery_date=date.today() + timedelta(days=2)),
    )
    assert result["mode"] == "fixture" and result["products"]["464306"]["mode"] == "fixture"


def test_unset_mode_never_resolves_to_fixture_when_a_key_is_configured(monkeypatch):
    configured(monkeypatch, valio_aimo_api_key="not-a-real-key")
    assert upstream.effective_mode() == "live"
    assert isinstance(upstream.client(), ValioClient)


def test_fixture_is_chosen_only_by_explicit_setting_or_a_missing_key(monkeypatch):
    configured(monkeypatch, upstream_mode="fixture", valio_aimo_api_key="not-a-real-key")
    assert upstream.effective_mode() == "fixture"
    assert isinstance(upstream.client(), FixtureClient)


def test_live_without_a_key_fails_closed_never_falls_back_to_fixtures(monkeypatch):
    configured(monkeypatch, upstream_mode="live", valio_aimo_api_key="")
    assert isinstance(upstream.client(), ValioClient)
    with pytest.raises(Problem) as error:
        upstream.client().post("/api/price", {})
    assert error.value.code == "UPSTREAM_CREDENTIALS_MISSING"


def test_an_unknown_mode_value_is_rejected_by_settings(monkeypatch):
    monkeypatch.delenv("UPSTREAM_MODE", raising=False)
    with pytest.raises(ValueError):
        Settings(_env_file=None, upstream_mode="sandbox")


@pytest.fixture
def hosted_env(monkeypatch):
    """Environment variables only, so any implementation that reads `settings()` sees them."""
    from aimo.config import settings

    monkeypatch.setenv("UPSTREAM_MODE", "auto")
    monkeypatch.setenv("VALIO_AIMO_API_KEY", "")
    monkeypatch.setenv("SECURE_COOKIES", "true")  # .env.example: hosted deployments MUST use true
    settings.cache_clear()
    yield
    monkeypatch.undo()
    settings.cache_clear()


@pytest.mark.xfail(
    strict=True,
    reason="Owner answer Q-01: a hosted deployment must have a key and fail at startup without "
    "one; waiting for person 1 (config.py / api.py). ASSUMPTION: hosted == SECURE_COOKIES=true; "
    "adapt the signal if person 1 adds an explicit one.",
)
def test_hosted_deployment_without_a_key_fails_at_startup(hosted_env):
    from fastapi.testclient import TestClient

    from aimo.api import create_app

    with pytest.raises(Exception):  # noqa: B017 - the exact type is person 1's choice
        with TestClient(create_app()):  # entering the client runs the app lifespan (startup)
            pass


def test_local_run_without_a_key_still_starts_on_labelled_fixtures(monkeypatch):
    """The other half of Q-01: local runs (SECURE_COOKIES=false) stay on auto with fixtures."""
    from fastapi.testclient import TestClient

    from aimo.api import create_app
    from aimo.config import settings

    monkeypatch.setenv("UPSTREAM_MODE", "auto")
    monkeypatch.setenv("VALIO_AIMO_API_KEY", "")
    monkeypatch.setenv("SECURE_COOKIES", "false")
    settings.cache_clear()
    try:
        with TestClient(create_app()) as client:
            assert client.get("/health/live").status_code == 200
        assert upstream.effective_mode() == "fixture"
    finally:
        monkeypatch.undo()
        settings.cache_clear()
