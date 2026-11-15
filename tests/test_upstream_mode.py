"""The shipped supplier client never selects authored pricing; no network calls."""

import pytest
from supplier_fixture import runtime_client, runtime_effective_mode, runtime_startup_check

from aimo import upstream
from aimo.config import Settings
from aimo.db import Problem
from aimo.upstream import ValioClient


def use(monkeypatch, **values):
    cfg = Settings(_env_file=None, **values)
    monkeypatch.setattr(upstream, "settings", lambda: cfg)


@pytest.mark.parametrize("mode", ["live", "auto"])
@pytest.mark.parametrize("key", ["", "   ", "not-a-real-key"])
def test_application_always_selects_live_supplier(monkeypatch, mode, key):
    use(monkeypatch, upstream_mode=mode, valio_aimo_api_key=key)
    assert runtime_effective_mode() == "live"
    assert isinstance(runtime_client(), ValioClient)
    if not key.strip():
        with pytest.raises(Problem) as error:
            runtime_client().post("/api/price", {})
        assert error.value.code == "UPSTREAM_CREDENTIALS_MISSING"


def test_explicit_fixture_is_refused_by_application_startup(monkeypatch):
    use(monkeypatch, upstream_mode="fixture", valio_aimo_api_key="not-a-real-key")
    assert isinstance(runtime_client(), ValioClient)
    with pytest.raises(RuntimeError, match="fixture is test-only"):
        runtime_startup_check()
