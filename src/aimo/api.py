from contextlib import asynccontextmanager
from pathlib import Path
from secrets import token_urlsafe
from uuid import UUID

from fastapi import Depends, FastAPI, Header, Query, Request, Response
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from aimo import approval_workflow as workflow
from aimo import auth, upstream
from aimo.config import settings
from aimo.db import Problem, close_pools, connection
from aimo.mcp_adapter import build_mcp
from aimo.schemas import (
    CommitRequest,
    CommitResponse,
    DecisionRequest,
    InboxResponse,
    LoginRequest,
    LookupRequest,
    LookupResponse,
    OrderResponse,
    PolicyResponse,
    PrepareRequest,
    ProductResponse,
    ProposalResponse,
    SearchRequest,
    SearchResponse,
    SessionResponse,
)
from aimo.service import Service

CONTENT_SECURITY_POLICY = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
)


def create_app(service=None):
    service = service or Service()
    mcp = build_mcp(service)
    transport = mcp.streamable_http_app()

    @asynccontextmanager
    async def lifespan(app):
        import anyio

        try:
            async with mcp.session_manager.run():
                yield
        finally:
            await anyio.to_thread.run_sync(close_pools)

    app = FastAPI(
        title="Valio Aimo purchasing gateway",
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
    )
    app.state.service = service

    @app.get("/docs", include_in_schema=False)
    def docs():
        nonce = token_urlsafe(32)
        html = get_swagger_ui_html(
            openapi_url=app.openapi_url,
            title=f"{app.title} — API documentation",
            swagger_favicon_url="data:,",
            swagger_ui_parameters={"validatorUrl": None},
        ).body.decode()
        policy = CONTENT_SECURITY_POLICY.replace(
            "script-src 'self'", f"script-src 'self' 'nonce-{nonce}'"
        ).replace("style-src 'self'", "style-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'")
        return HTMLResponse(
            html.replace("<script", f'<script nonce="{nonce}"'),
            headers={"Content-Security-Policy": policy, "Cache-Control": "no-store"},
        )

    @app.exception_handler(Problem)
    async def problem_handler(request, exc):
        return JSONResponse(
            {"error": {"code": exc.code, "message": exc.message}},
            status_code=exc.status,
            headers={"Retry-After": str(exc.retry_after)} if exc.retry_after is not None else None,
        )

    @app.middleware("http")
    async def security_headers(request, call_next):
        # Apply agent auth to MCP discovery as well as every tool invocation.
        if request.url.path.startswith("/mcp"):
            try:
                import anyio

                request.state.agent_identity = await anyio.to_thread.run_sync(
                    auth.agent_identity, request.headers.get("authorization")
                )
            except Problem as exc:
                return await problem_handler(request, exc)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        if request.url.path != "/docs" or response.status_code != 200:
            response.headers["Content-Security-Policy"] = CONTENT_SECURITY_POLICY
        if request.url.path.startswith(("/api", "/mcp")):
            response.headers["Cache-Control"] = "no-store"
        return response

    def agent(authorization: str | None = Header(default=None)):
        return auth.agent_identity(authorization)

    def buyer(request: Request):
        return auth.browser_identity(request.cookies.get("aimo_session"))[0]

    @app.get("/health/live")
    async def live():
        return {"status": "ok"}

    @app.get("/health/ready")
    def ready():
        from aimo.search import model, model_key

        with connection() as c:
            active = c.execute(
                "SELECT g.model_key FROM active_catalog a JOIN catalog_generations g ON g.id=a.generation"
            ).fetchone()
        if not active or active["model_key"] != model_key():
            raise Problem(
                "INDEX_NOT_READY", "Ingest with the configured model before serving.", 503
            )
        if settings().embedding_backend == "sentence_transformers":
            model()
        return {
            "status": "ready",
            "model": active["model_key"],
            "upstream_mode": upstream.effective_mode(),
        }

    @app.post("/api/login", response_model=SessionResponse)
    def login(body: LoginRequest, request: Request, response: Response):
        auth.check_origin(request.headers.get("origin"))
        identity, cookie, csrf = auth.login(
            body.username, body.password, request.client.host if request.client else "unknown"
        )
        response.set_cookie(
            "aimo_session",
            cookie,
            httponly=True,
            secure=settings().secure_cookies,
            samesite="strict",
            max_age=8 * 3600,
            path="/",
        )
        return {"username": identity["id"], "buyer_id": identity["buyer_id"], "csrf_token": csrf}

    @app.get("/api/session", response_model=SessionResponse)
    def session(request: Request):
        identity, data = auth.browser_identity(request.cookies.get("aimo_session"))
        return {
            "username": identity["id"],
            "buyer_id": identity["buyer_id"],
            "csrf_token": data["csrf"],
        }

    @app.post("/api/logout", status_code=204)
    def logout(request: Request, response: Response, identity=Depends(buyer)):
        auth.csrf_check(
            identity, request.headers.get("x-csrf-token"), request.headers.get("origin")
        )
        _, data = auth.browser_identity(request.cookies.get("aimo_session"))
        with connection() as c:
            c.execute("DELETE FROM sessions WHERE token_hash=%s", (auth.digest(data["token"]),))
        response.delete_cookie("aimo_session", path="/")

    @app.get("/api/approvals", response_model=InboxResponse)
    def inbox(
        offset: int = Query(0, ge=0, le=10000),
        limit: int = Query(20, ge=1, le=50),
        identity=Depends(buyer),
    ):
        return workflow.list_approvals(identity, offset, limit)

    @app.get("/api/approvals/{approval_id}", response_model=ProposalResponse)
    def detail(approval_id: UUID, identity=Depends(buyer)):
        return workflow.approval_detail(identity, approval_id)

    @app.get("/api/purchases/{proposal_id}", response_model=ProposalResponse)
    def current_purchase(proposal_id: UUID, identity=Depends(buyer)):
        return workflow.get_proposal(identity, proposal_id)

    @app.post("/api/approvals/{approval_id}/decision", response_model=ProposalResponse)
    def decision(
        approval_id: UUID, body: DecisionRequest, request: Request, identity=Depends(buyer)
    ):
        auth.csrf_check(
            identity, request.headers.get("x-csrf-token"), request.headers.get("origin")
        )
        return workflow.record_human_decision(identity, approval_id, body)

    @app.post("/api/agent/search_products", response_model=SearchResponse)
    def search(body: SearchRequest, identity=Depends(agent)):
        return service.search_products(identity, body)

    @app.get("/api/agent/products/{product_id}", response_model=ProductResponse)
    def product(product_id: str, identity=Depends(agent)):
        return service.get_product(identity, product_id)

    @app.get("/api/agent/purchase-policy", response_model=PolicyResponse)
    def policy(identity=Depends(agent)):
        return service.get_purchase_policy(identity)

    @app.post("/api/agent/check_price_and_availability", response_model=LookupResponse)
    def lookup(body: LookupRequest, identity=Depends(agent)):
        return service.check_price_and_availability(identity, body)

    @app.post("/api/agent/prepare_order", response_model=ProposalResponse)
    def prepare(body: PrepareRequest, identity=Depends(agent)):
        return service.prepare_order(identity, body)

    @app.get("/api/agent/proposals/{proposal_id}", response_model=ProposalResponse)
    def proposal(proposal_id: UUID, identity=Depends(agent)):
        return service.get_proposal(identity, proposal_id)

    @app.post("/api/agent/commit_order", response_model=CommitResponse)
    def commit(body: CommitRequest, identity=Depends(agent)):
        return service.commit_order(identity, body)

    @app.get("/api/agent/orders/{order_id}", response_model=OrderResponse)
    def order(order_id: UUID, identity=Depends(agent)):
        return service.get_order(identity, order_id)

    app.mount("/mcp", transport)
    dist = Path(settings().frontend_dist)
    if (dist / "assets").exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/", include_in_schema=False)
    @app.get("/login", include_in_schema=False)
    @app.get("/approvals", include_in_schema=False)
    @app.get("/approvals/{approval_id}", include_in_schema=False)
    @app.get("/purchases/{proposal_id}", include_in_schema=False)
    def frontend():
        if not (dist / "index.html").exists():
            return JSONResponse(
                {"error": "Build the frontend: cd frontend && npm ci && npm run build"},
                status_code=503,
            )
        return FileResponse(dist / "index.html", headers={"Cache-Control": "no-cache"})

    return app


app = create_app()
