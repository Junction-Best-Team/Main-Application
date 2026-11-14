import pytest

from aimo import upstream
from aimo.config import Settings
from aimo.db import Problem
from aimo.upstream import FixtureClient, ValioClient


def use(monkeypatch, **values):
    cfg = Settings(_env_file=None, **values)
    monkeypatch.setattr(upstream, "settings", lambda: cfg)


def test_auto_without_key_falls_back_to_labelled_fixtures(monkeypatch):
    use(monkeypatch, upstream_mode="auto", valio_aimo_api_key="")
    assert upstream.effective_mode() == "fixture"
    assert isinstance(upstream.client(), FixtureClient)
    assert upstream.client().mode == "fixture"


def test_auto_with_key_uses_live_client(monkeypatch):
    use(monkeypatch, upstream_mode="auto", valio_aimo_api_key="not-a-real-key")
    assert upstream.effective_mode() == "live"
    assert isinstance(upstream.client(), ValioClient)


def test_explicit_fixture_ignores_a_configured_key(monkeypatch):
    use(monkeypatch, upstream_mode="fixture", valio_aimo_api_key="not-a-real-key")
    assert upstream.effective_mode() == "fixture"
    assert isinstance(upstream.client(), FixtureClient)


def test_explicit_live_without_key_fails_closed(monkeypatch):
    use(monkeypatch, upstream_mode="live", valio_aimo_api_key="")
    assert upstream.effective_mode() == "live"
    with pytest.raises(Problem) as error:
        upstream.client().post("/api/price", {})
    assert error.value.code == "UPSTREAM_CREDENTIALS_MISSING"
