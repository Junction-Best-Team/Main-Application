"""Application defaults, official supplier destination and missing-key failures."""

import re
from pathlib import Path

import pytest
from supplier_fixture import runtime_client, runtime_startup_check

from aimo import upstream
from aimo.config import Settings
from aimo.upstream import ValioClient

ROOT = Path(__file__).resolve().parents[1]


def configured(monkeypatch, **values):
    monkeypatch.delenv("UPSTREAM_MODE", raising=False)
    cfg = Settings(_env_file=None, **values)
    monkeypatch.setattr(upstream, "settings", lambda: cfg)
    return cfg


def test_code_env_and_compose_default_to_live(monkeypatch):
    cfg = configured(monkeypatch)
    assert cfg.upstream_mode == "live"
    assert cfg.valio_aimo_base_url == "https://junction26.valioaimo.fi"
    assert re.search(r"^UPSTREAM_MODE=live\s*$", (ROOT / ".env.example").read_text(), re.M)
    assert "${UPSTREAM_MODE:-live}" in (ROOT / "compose.yaml").read_text()
    assert isinstance(runtime_client(), ValioClient)


@pytest.mark.parametrize("secure", [False, True])
@pytest.mark.parametrize("mode", ["live", "auto"])
def test_missing_key_fails_startup_locally_and_when_hosted(monkeypatch, secure, mode):
    configured(monkeypatch, upstream_mode=mode, secure_cookies=secure, valio_aimo_api_key=" ")
    with pytest.raises(RuntimeError, match="VALIO_AIMO_API_KEY"):
        runtime_startup_check()


@pytest.mark.parametrize("url", ["http://junction26.valioaimo.fi", "https://wrong.example"])
def test_startup_refuses_the_wrong_supplier_target(monkeypatch, url):
    configured(monkeypatch, valio_aimo_api_key="not-a-real-key", valio_aimo_base_url=url)
    with pytest.raises(RuntimeError, match="VALIO_AIMO_BASE_URL") as error:
        runtime_startup_check()
    assert "not-a-real-key" not in str(error.value)


def test_official_target_with_key_passes_without_a_lookup(monkeypatch):
    configured(monkeypatch, valio_aimo_api_key="not-a-real-key")
    runtime_startup_check()


def test_unknown_mode_is_rejected(monkeypatch):
    with pytest.raises(ValueError):
        configured(monkeypatch, upstream_mode="sandbox")
