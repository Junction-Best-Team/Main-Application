"""JNP3-IDN-005 (no MCP runtime code) and JNP3-IDN-003 (no external bearer credentials)."""

import ast
import re
import sys
import tomllib
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from wsc_support import counts

from aimo import auth
from aimo.api import create_app
from aimo.db import connection, js

ROOT = Path(__file__).resolve().parents[1]
MCP = re.compile(r"(^|[._-])mcp($|[._-])", re.IGNORECASE)


def test_source_imports_no_mcp_module():
    offenders = []
    for path in sorted((ROOT / "src").rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(), str(path))):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            offenders += [f"{path.relative_to(ROOT)}: {n}" for n in names if MCP.search(n)]
    assert offenders == []


def test_no_mcp_dependency_is_declared_or_locked():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    declared = project["project"].get("dependencies", [])
    for group in project.get("dependency-groups", {}).values():
        declared += [d for d in group if isinstance(d, str)]
    assert [d for d in declared if MCP.search(re.split(r"[<>=~! ;\[]", d)[0])] == []
    locked = tomllib.loads((ROOT / "uv.lock").read_text())
    assert [p["name"] for p in locked["package"] if MCP.search(p["name"])] == []


def test_importing_the_application_loads_no_mcp_module():
    import aimo.agent  # noqa: F401
    import aimo.api  # noqa: F401
    import aimo.cli  # noqa: F401
    import aimo.service  # noqa: F401
    import aimo.worker  # noqa: F401

    assert [m for m in sys.modules if MCP.search(m) and not m.startswith('test_')] == []


def test_app_registers_no_mcp_or_agent_api_route(service):
    app = create_app(service)
    paths = [getattr(route, "path", "") for route in app.routes]
    assert [p for p in paths if p.startswith(("/mcp", "/api/agent"))] == []
    assert [p for p in app.openapi()["paths"] if "mcp" in p.lower() or "/agent" in p] == []


# --- IDN-003: bearer credentials are never accepted ----------------------------

PUBLIC = {"/health/live", "/health/ready", "/docs", "/openapi.json", "/api/login"}


def test_valid_looking_bearer_token_is_ignored_on_every_route(service):
    token = "externally-provisioned-" + uuid4().hex
    with connection() as c:  # the removed scheme: sha256(token) as the credential of an agent
        c.execute(
            "INSERT INTO identities VALUES('external-agent','demo-hotel','agent',true,%s,%s)",
            (auth.digest(token), js({"currency": "EUR", "autonomous_limit": "1500"})),
        )
    app = create_app(service)
    before = counts()
    with TestClient(app) as client:
        for path, operations in app.openapi()["paths"].items():
            if path in PUBLIC:
                continue
            url = re.sub(r"\{[^}]+\}", str(uuid4()), path)
            for method in operations:
                send = getattr(client, method)
                kwargs = {"json": {}} if method in ("post", "put", "patch") else {}
                plain = send(url, **kwargs)
                bearer = send(url, headers={"Authorization": f"Bearer {token}"}, **kwargs)
                assert bearer.status_code == plain.status_code, (method, path)
                assert not 200 <= bearer.status_code < 300, (method, path)
                assert bearer.status_code < 500, (method, path)
        # An agent identity cannot sign in with the token or its hash either.
        for secret in (token, auth.digest(token)):
            login = client.post(
                "/api/login",
                headers={"Origin": "http://testserver"},
                json={"username": "external-agent", "password": secret},
            )
            assert login.status_code == 401 and login.json()["error"]["code"] == "LOGIN_FAILED"
        for path in ("/mcp", "/mcp/", "/api/agent/prepare_order", "/api/agent/purchase-policy"):
            assert client.get(path, headers={"Authorization": f"Bearer {token}"}).status_code == 404
    assert counts() == before


@pytest.mark.parametrize("username", ["demo-agent", "external-agent"])
def test_agent_identities_cannot_sign_in(service, username):
    with connection() as c:
        c.execute(
            "INSERT INTO identities VALUES('external-agent','demo-hotel','agent',true,%s,%s) "
            "ON CONFLICT DO NOTHING",
            (auth.digest("t"), js({"currency": "EUR", "autonomous_limit": "1500"})),
        )
    with TestClient(create_app(service)) as client:
        response = client.post(
            "/api/login",
            headers={"Origin": "http://testserver"},
            json={"username": username, "password": "t"},
        )
    assert response.status_code == 401
