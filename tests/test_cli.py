"""Command-line entry points: configure, migrate, seed and the argument dispatch of main()."""

import hashlib
import json
import shutil
import stat
import sys
from pathlib import Path

import pytest

import aimo.cli as cli
from aimo.auth import hasher
from aimo.db import connection
from aimo.fixtures import fixture_facts

ROOT = Path(cli.__file__).resolve().parents[2]


def run_main(monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", ["aimo", *argv])
    cli.main()


# --- configure -----------------------------------------------------------------------------------


@pytest.fixture
def workdir(tmp_path, monkeypatch):
    shutil.copy(ROOT / ".env.example", tmp_path / ".env.example")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_configure_writes_private_env_with_generated_secrets(workdir, capsys):
    cli.configure()
    env = workdir / ".env"
    assert stat.S_IMODE(env.stat().st_mode) == 0o600
    values = dict(line.split("=", 1) for line in env.read_text().splitlines() if "=" in line)
    assert len(values["APPROVAL_SESSION_SECRET"]) >= 48
    assert "DEMO_AGENT_TOKEN" not in values  # no external agent credential any more
    assert len(values["DEMO_BUYER_PASSWORD"]) >= 12
    assert values["VALIO_AIMO_API_KEY"] == ""  # never invented
    out = capsys.readouterr().out
    assert "mode 0600" in out
    assert values["DEMO_BUYER_PASSWORD"] not in out  # values are not printed


def test_configure_generates_distinct_secrets_each_time(workdir):
    cli.configure()
    first = (workdir / ".env").read_text()
    (workdir / ".env").unlink()
    cli.configure()
    assert (workdir / ".env").read_text() != first


def test_configure_refuses_to_overwrite_an_existing_env(workdir):
    (workdir / ".env").write_text("DEMO_BUYER_PASSWORD=mine\n")
    with pytest.raises(ValueError, match=r"\.env exists"):
        cli.configure()
    assert (workdir / ".env").read_text() == "DEMO_BUYER_PASSWORD=mine\n"


# --- migrate -------------------------------------------------------------------------------------


def applied():
    with connection() as c:
        return [
            r["version"]
            for r in c.execute("SELECT version FROM schema_migrations ORDER BY version")
        ]


def test_migrate_is_idempotent():
    expected = sorted(p.name for p in (ROOT / "migrations").glob("*.sql"))
    assert applied() == expected
    cli.migrate()
    cli.migrate()
    assert applied() == expected


def test_migrate_applies_a_new_migration_exactly_once(tmp_path, monkeypatch):
    (tmp_path / "migrations").mkdir()
    (tmp_path / "migrations" / "999_probe.sql").write_text(
        "CREATE TABLE cov95_probe(n int); INSERT INTO cov95_probe VALUES(1);"
    )
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    try:
        cli.migrate()
        cli.migrate()  # already recorded: must not run (and fail on CREATE TABLE) again
        with connection() as c:
            assert c.execute("SELECT count(*) AS n FROM cov95_probe").fetchone()["n"] == 1
            assert (
                c.execute(
                    "SELECT count(*) AS n FROM schema_migrations WHERE version='999_probe.sql'"
                ).fetchone()["n"]
                == 1
            )
    finally:
        with connection() as c:
            c.execute("DROP TABLE IF EXISTS cov95_probe")
            c.execute("DELETE FROM schema_migrations WHERE version='999_probe.sql'")


# --- seed ----------------------------------------------------------------------------------------


@pytest.mark.parametrize("password", ["short-pw", ""])
def test_seed_rejects_weak_or_missing_credentials(monkeypatch, password):
    monkeypatch.setenv("DEMO_BUYER_PASSWORD", password)
    with pytest.raises(ValueError, match="DEMO_BUYER_PASSWORD"):
        cli.seed()


def test_seed_is_idempotent_and_does_not_rotate_existing_credentials(monkeypatch):
    def state():
        with connection() as c:
            return (
                c.execute("SELECT id,credential_hash FROM identities ORDER BY id").fetchall(),
                c.execute("SELECT count(*) AS n FROM policies").fetchone()["n"],
            )

    before = state()
    monkeypatch.setenv("DEMO_BUYER_PASSWORD", "a-completely-different-password")
    cli.seed()
    assert state() == before


def test_seed_stores_hashes_never_plaintext():
    with connection() as c:
        rows = c.execute("SELECT id,role,credential_hash FROM identities").fetchall()
        mapped = c.execute("SELECT buyer_id,identity_id FROM internal_agents").fetchall()
    by_id = {r["id"]: r for r in rows}
    internal = "internal:" + hashlib.md5(b"demo-hotel").hexdigest()
    assert set(by_id) == {"demo-agent", "buyer", internal}
    assert hasher.verify(by_id["buyer"]["credential_hash"], "test-buyer-password-only")
    # Neither agent identity can ever log in with a bearer value.
    assert by_id["demo-agent"]["credential_hash"].startswith("!")
    assert by_id[internal]["credential_hash"].startswith("!")
    assert [(m["buyer_id"], m["identity_id"]) for m in mapped] == [("demo-hotel", internal)]


# --- main() dispatch -----------------------------------------------------------------------------


@pytest.mark.parametrize("command", ["configure", "migrate", "seed"])
def test_main_dispatches_simple_commands(monkeypatch, command):
    calls = []
    monkeypatch.setattr(cli, command, lambda: calls.append(command))
    run_main(monkeypatch, command)
    assert calls == [command]


def test_main_requires_a_command(monkeypatch, capsys):
    with pytest.raises(SystemExit) as stop:
        run_main(monkeypatch)
    assert stop.value.code == 2
    assert "required" in capsys.readouterr().err


def test_main_rejects_an_unknown_command(monkeypatch):
    with pytest.raises(SystemExit) as stop:
        run_main(monkeypatch, "launch-missiles")
    assert stop.value.code == 2


def test_main_serve_runs_uvicorn_on_all_interfaces(monkeypatch):
    import uvicorn

    seen = {}
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: seen.update(app=app, **kw))
    run_main(monkeypatch, "serve")
    from aimo.config import settings

    # Proxy headers are trusted only from the configured addresses (default: loopback).
    assert seen == {
        "app": "aimo.api:app",
        "host": "0.0.0.0",
        "port": 8000,
        "forwarded_allow_ips": settings().forwarded_allow_ips,
    }


def test_main_cache_model_loads_the_pinned_model(monkeypatch, capsys):
    import aimo.search as search

    loaded = []
    monkeypatch.setattr(search, "model", lambda: loaded.append(True))
    run_main(monkeypatch, "cache-model")
    assert loaded == [True]
    assert "Pinned model cached." in capsys.readouterr().out


def test_main_fixture_catalog_publishes_authored_fixtures(monkeypatch, capsys):
    import aimo.ingest as ingestion

    seen = {}

    def fake_publish(data, source, source_hash):
        seen.update(count=len(data), source=source, hash=source_hash)
        return {"products": len(data)}

    monkeypatch.setattr(ingestion, "publish", fake_publish)
    run_main(monkeypatch, "fixture-catalog")
    assert seen["source"] == "authored-fixtures-v1" and seen["count"] == len(fixture_facts())
    assert len(seen["hash"]) == 64
    assert json.loads(capsys.readouterr().out) == {"products": len(fixture_facts())}


def test_main_ingest_passes_options_and_skips_download_by_default(monkeypatch, capsys):
    import aimo.ingest as ingestion

    calls = []
    monkeypatch.setattr(ingestion, "download", lambda path: calls.append(("download", path)))
    monkeypatch.setattr(
        ingestion,
        "ingest_file",
        lambda path, count, sha: calls.append(("ingest", path, count, sha)) or {"ok": True},
    )
    run_main(
        monkeypatch,
        "ingest",
        "--file",
        "snap.json",
        "--expected-count",
        "7",
        "--expected-sha256",
        "abc",
    )
    assert calls == [("ingest", Path("snap.json"), 7, "abc")]
    assert json.loads(capsys.readouterr().out) == {"ok": True}


def test_main_ingest_download_flag_downloads_first_with_default_expectations(monkeypatch):
    import aimo.ingest as ingestion

    calls = []
    monkeypatch.setattr(ingestion, "download", lambda path: calls.append(("download", path)))
    monkeypatch.setattr(
        ingestion,
        "ingest_file",
        lambda path, count, sha: calls.append(("ingest", count, sha)) or {},
    )
    run_main(monkeypatch, "ingest", "--file", "snap.json", "--download")
    assert calls == [
        ("download", Path("snap.json")),
        ("ingest", 17546, ingestion.CATALOG_SHA256),
    ]


def test_main_ingest_requires_a_file(monkeypatch):
    with pytest.raises(SystemExit) as stop:
        run_main(monkeypatch, "ingest")
    assert stop.value.code == 2
