"""JNP3-TCT-006: the purchasing tools run in-process, through the Service layer, with no tool server.

Evidence for the claim in docs/separate-apps.md: the tools are plain Python calls inside the
worker (and the API's own Service), never an HTTP hop between the agent runner and the tools.
The agent runner legitimately uses HTTP for exactly two things, the LLM provider and the
guardrail classifier; the scan below pins that and fails if the tool path ever gains a client.
"""

import ast
import re
import socket
from datetime import date, timedelta
from pathlib import Path

import pytest

from aimo.agent_tools import ToolSession
from aimo.api import create_app
from aimo.schemas import SearchResponse

SRC = Path(__file__).resolve().parents[1] / "src" / "aimo"
HTTP_LIBRARIES = {
    "httpx",
    "requests",
    "urllib",
    "urllib3",
    "aiohttp",
    "http",
    "socket",
    "socketserver",
    "uvicorn",
    "fastapi",
    "starlette",
    "websockets",
    "grpc",
    "xmlrpc",
    "subprocess",
}
URL_TEXT = re.compile(r"https?://|wss?://|localhost|127\.0\.0\.1|0\.0\.0\.0", re.IGNORECASE)
# Modules that may start a listening server or define HTTP handlers: the API app, its error
# handlers (errors.py, TCT-008), the worker's internal health probe and the `aimo serve` command.
# Nothing else may import a server framework.
SERVER_MODULES = {"api.py", "errors.py", "cli.py", "worker.py"}
SERVER_IMPORTS = {"uvicorn", "fastapi", "starlette", "socketserver", "http.server", "aiohttp"}


def parse(module):
    return ast.parse((SRC / module).read_text())


def imported_roots(tree):
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def imported_names(tree):
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def string_constants(tree):
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef)):
            first = node.body[0] if node.body else None
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                docstrings.add(id(first.value))
    return [
        n.value
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docstrings
    ]


# ---- static: the tool module itself ------------------------------------------------------


def test_agent_tools_imports_no_http_client_or_server():
    tree = parse("agent_tools.py")
    assert imported_roots(tree) & HTTP_LIBRARIES == set()


def test_agent_tools_has_no_url_or_host_strings():
    assert [s for s in string_constants(parse("agent_tools.py")) if URL_TEXT.search(s)] == []


def test_first_party_modules_used_by_agent_tools_do_no_networking():
    """Everything agent_tools.py imports from aimo.* is free of HTTP libraries too."""
    first_party = {
        name.split(".")[1] + ".py"
        for name in imported_names(parse("agent_tools.py"))
        if name.startswith("aimo.")
    }
    assert first_party >= {
        "db.py",
        "schemas.py",
        "recipe_schemas.py",
    }  # config.py left with the flag (PR #103)
    offenders = {m: imported_roots(parse(m)) & HTTP_LIBRARIES for m in first_party}
    assert {m: libs for m, libs in offenders.items() if libs} == {}


def test_tool_handlers_reach_the_service_only_as_direct_method_calls():
    """self.service is only stored once and then called as self.service.<method>(...)."""
    tree = parse("agent_tools.py")
    calls, bare = [], []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if (
                isinstance(func, ast.Attribute)
                and isinstance(func.value, ast.Attribute)
                and func.value.attr == "service"
            ):
                calls.append(func.attr)
    parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == "service":
            parent = parents[node]
            direct_call = isinstance(parent, ast.Attribute) and isinstance(
                parents.get(parent), ast.Call
            )
            stored = isinstance(parent, ast.Assign) or isinstance(parents.get(node), ast.Tuple)
            if not (direct_call or stored):
                bare.append(node.lineno)
    assert calls, "expected handlers to call self.service.<method>(...) directly"
    assert bare == [], f"self.service used other than as a direct method call: lines {bare}"
    dynamic = {
        n.func.id
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id in {"getattr", "eval", "exec", "__import__", "setattr"}
    }
    assert dynamic == set(), "dynamic dispatch would hide the Service call from this scan"


# ---- static: the runner that drives the tools -------------------------------------------


def test_agent_runner_http_client_never_reaches_the_tools():
    """agent.py imports httpx for the LLM provider and guardrails only; the tool path has none."""
    tree = parse("agent.py")
    assert "httpx" in imported_roots(tree), "scan premise changed: re-check where HTTP is used"
    assert [s for s in string_constants(tree) if URL_TEXT.search(s)] == []
    clients, tool_calls = [], []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            callee = ast.unparse(node.func)
            args = [ast.unparse(a) for a in node.args] + [
                ast.unparse(k.value) for k in node.keywords
            ]
            if callee in {"ToolSession"} or callee.startswith("session."):
                tool_calls.append((callee, args))
            if "client" in args:
                clients.append(callee)
    assert tool_calls, "expected run_turn to build a ToolSession and call session.invoke"
    assert all("client" not in "".join(args) for _, args in tool_calls), tool_calls
    # The HTTP client goes to exactly the provider and the guardrail classifier.
    assert sorted(clients) == ["ChatProvider", "Guardrails"]
    # Tool execution is session.invoke(name, arguments): a local method, no URL or client.
    invokes = [
        ast.unparse(n)
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and ast.unparse(n.func) == "session.invoke"
    ]
    assert invokes == ["session.invoke(name, call.function.arguments)"]


def test_provider_sends_the_tool_definitions_but_never_calls_them():
    """agent_provider.py's only HTTP target is the LLM chat/completions URL built from config."""
    tree = parse("agent_provider.py")
    # "localhost" is only the loopback check on the configured LLM_BASE_URL, not a tool endpoint.
    urls = [s for s in string_constants(tree) if URL_TEXT.search(s) and s != "localhost"]
    assert urls == []
    text = (SRC / "agent_provider.py").read_text()
    assert text.count("self.client.stream(") == 1
    assert 'self.url = config.llm_base_url.rstrip("/") + "/chat/completions"' in text
    assert "agent_tools" not in imported_names(tree)


def test_only_api_cli_and_worker_import_a_server_framework():
    importing = {}
    for path in sorted(SRC.glob("*.py")):
        names = imported_names(ast.parse(path.read_text())) | imported_roots(
            ast.parse(path.read_text())
        )
        hit = names & SERVER_IMPORTS
        if hit:
            importing[path.name] = hit
    assert set(importing) <= SERVER_MODULES, importing
    assert {"agent.py", "agent_tools.py", "agent_provider.py", "service.py"}.isdisjoint(importing)


def test_worker_listens_on_one_health_only_server():
    """The worker's only listener is its probe: /health/live and /health/ready, 404 otherwise."""
    tree = parse("worker.py")
    servers = [
        n for n in ast.walk(tree) if isinstance(n, ast.Call) and "HTTPServer" in ast.unparse(n.func)
    ]
    assert [ast.unparse(s.func) for s in servers] == ["ThreadingHTTPServer"]
    paths = sorted({s for s in string_constants(tree) if s.startswith("/")})
    assert paths == ["/health/live", "/health/ready"], paths
    assert "invoke" not in (SRC / "worker.py").read_text()


# ---- runtime ------------------------------------------------------------------------------


class StubService:
    """Stands in for Service; counts direct calls."""

    def __init__(self):
        self.calls = []

    def search_products(self, identity, request):
        self.calls.append(("search_products", identity["id"], request.query))
        return SearchResponse(
            products=[], generation="g", model="m", strategy="keyword", note="stub"
        ).model_dump(mode="json")


@pytest.fixture
def no_network(monkeypatch):
    """Any Python-level attempt to open a connection fails the test."""
    attempts = []

    def refuse(*args, **kwargs):
        attempts.append((args, kwargs))
        raise AssertionError("network access attempted by a purchasing tool")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    return attempts


def tool_session(service):
    identity = {"id": "internal:x", "buyer_id": "demo-hotel", "role": "agent", "_turn_id": "t-1"}
    return ToolSession(identity, service)


def test_guard_actually_blocks_sockets(no_network):
    """Control: without this the passing test below could be vacuous."""
    with pytest.raises(AssertionError, match="network access attempted"):
        socket.create_connection(("127.0.0.1", 9))
    with pytest.raises(AssertionError, match="network access attempted"):
        socket.socket().connect(("127.0.0.1", 9))
    assert len(no_network) == 2


def test_tool_invocation_is_a_direct_service_call_with_the_network_blocked(no_network):
    stub = StubService()
    result = tool_session(stub).invoke("search_products", '{"query": "milk"}')
    assert result["strategy"] == "keyword" and result["products"] == []
    assert stub.calls == [("search_products", "internal:x", "milk")]
    assert no_network == []


def test_every_registered_tool_is_a_bound_session_method_not_a_remote_call(monkeypatch):
    """Registry handlers are methods or lambdas defined in agent_tools.py, nothing remote."""
    session = tool_session(StubService())
    for name, spec in session.registry.items():
        handler = spec.handler
        assert handler.__module__ == "aimo.agent_tools", name
        assert getattr(handler, "__self__", session) is session, name


def test_real_service_tool_call_works_with_the_network_blocked(agent, service, no_network):
    """Real Service and PostgreSQL (libpq, not Python sockets), fixture upstream, no HTTP hop."""
    identity = dict(agent) | {"_turn_id": "t-real"}
    session = ToolSession(identity, service)
    policy = session.invoke("get_purchase_policy", "{}")
    assert policy["buyer_id"] == identity["buyer_id"]
    delivery = (date.today() + timedelta(days=2)).isoformat()
    lookup = session.invoke(
        "check_price_and_availability",
        '{"product_ids": ["464306"], "delivery_date": "' + delivery + '"}',
    )
    assert "464306" in lookup["products"]
    assert no_network == []


# ---- the API registers no tool route -----------------------------------------------------


def test_api_app_registers_no_tool_route_or_mount(monkeypatch):
    names = set(tool_session(StubService()).registry) | {
        "search_recipes",
        "get_recipe",
        "scale_recipe",
        "get_recipe_plan",
        "match_ingredient",
    }
    app = create_app(service=StubService())
    paths = [getattr(r, "path", "") for r in app.routes]
    assert paths, "expected the API to register routes"
    assert [type(r).__name__ for r in app.routes if type(r).__name__ == "Mount"] == []
    forbidden = ("tool", "mcp", "agent", "rpc", "invoke", "function")
    assert [p for p in paths if any(word in p.lower() for word in forbidden)] == []
    segments = {seg for p in paths for seg in p.strip("/").split("/")}
    assert segments.isdisjoint(names), segments & names
    assert all(p.startswith(("/api", "/health")) or p in {"/docs", "/openapi.json"} for p in paths)
    assert set(app.openapi()["paths"]) == {p for p in paths if p not in {"/docs", "/openapi.json"}}
