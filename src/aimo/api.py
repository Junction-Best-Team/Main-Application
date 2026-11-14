from contextlib import asynccontextmanager
from secrets import token_urlsafe
from uuid import UUID

from fastapi import Depends, FastAPI, Query, Request, Response
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

from aimo import approval_workflow as workflow
from aimo import auth, conversations
from aimo.chat_schemas import (
    ConversationCreate,
    ConversationList,
    ConversationResponse,
    MessageRequest,
)
from aimo.config import settings
from aimo.db import Problem, close_pools, connection
from aimo.schemas import (
    CommitRequest,
    CommitResponse,
    DecisionRequest,
    InboxResponse,
    LoginRequest,
    ProposalResponse,
    SessionResponse,
)
from aimo.service import Service

CONTENT_SECURITY_POLICY = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
)


def create_app(service=None):
    service = service or Service()

    @asynccontextmanager
    async def lifespan(app):
        import anyio

        try:
            yield
        finally:
            await anyio.to_thread.run_sync(close_pools)

    app = FastAPI(
        title="Aimo chat purchasing",
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
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        if request.url.path != "/docs" or response.status_code != 200:
            response.headers["Content-Security-Policy"] = CONTENT_SECURITY_POLICY
        if request.url.path.startswith("/api"):
            response.headers["Cache-Control"] = "no-store"
        return response

    def buyer(request: Request):
        return auth.browser_identity(request.cookies.get("aimo_session"))[0]

    @app.get("/health/live")
    async def live():
        return {"status": "ok"}

    @app.get("/health/ready")
    def ready():
        from aimo.search import dimensions, model_key

        with connection() as c:
            active = c.execute(
                "SELECT g.model_key,g.embedding_dimensions FROM active_catalog a JOIN catalog_generations g ON g.id=a.generation"
            ).fetchone()
        if (
            not active
            or active["model_key"] != model_key()
            or active["embedding_dimensions"] != dimensions()
        ):
            raise Problem(
                "INDEX_NOT_READY", "Ingest with the configured model before serving.", 503
            )
        with connection() as c:
            c.execute("SELECT requested_by FROM conversation_turns LIMIT 0")
        return {
            "status": "ready",
            "model": active["model_key"],
            "upstream_mode": settings().upstream_mode,
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

    @app.get("/api/purchases", response_model=InboxResponse)
    def purchase_history(
        offset: int = Query(0, ge=0, le=10000),
        limit: int = Query(20, ge=1, le=50),
        identity=Depends(buyer),
    ):
        return conversations.purchases(identity, offset, limit)

    @app.post("/api/purchases/{proposal_id}/confirm", response_model=CommitResponse)
    def confirm_purchase(
        proposal_id: UUID, body: CommitRequest, request: Request, identity=Depends(buyer)
    ):
        auth.csrf_check(
            identity, request.headers.get("x-csrf-token"), request.headers.get("origin")
        )
        return conversations.confirm(identity, proposal_id, body, service)

    @app.get("/api/conversations", response_model=ConversationList)
    def conversation_list(
        offset: int = Query(0, ge=0, le=10000),
        limit: int = Query(20, ge=1, le=50),
        identity=Depends(buyer),
    ):
        return conversations.listing(identity, offset, limit)

    @app.post("/api/conversations", response_model=ConversationResponse)
    def conversation_create(body: ConversationCreate, request: Request, identity=Depends(buyer)):
        auth.csrf_check(
            identity, request.headers.get("x-csrf-token"), request.headers.get("origin")
        )
        return conversations.create(identity, body)

    @app.get("/api/conversations/{conversation_id}", response_model=ConversationResponse)
    def conversation_detail(conversation_id: UUID, identity=Depends(buyer)):
        return conversations.detail(identity, conversation_id)

    @app.post("/api/conversations/{conversation_id}/messages", response_model=ConversationResponse)
    def send_message(
        conversation_id: UUID, body: MessageRequest, request: Request, identity=Depends(buyer)
    ):
        auth.csrf_check(
            identity, request.headers.get("x-csrf-token"), request.headers.get("origin")
        )
        return conversations.enqueue(identity, conversation_id, body)

    @app.get(
        "/api/conversations/{conversation_id}/events",
        response_class=StreamingResponse,
        responses={
            200: {
                "description": "SSE event 'conversation' carries ConversationResponse JSON; 'expired' carries an empty object. Comments are heartbeats.",
                "content": {"text/event-stream": {"schema": {"type": "string"}}},
            }
        },
    )
    def conversation_events(conversation_id: UUID, request: Request, identity=Depends(buyer)):
        conversations.detail(identity, conversation_id)  # Authenticate before streaming headers.
        cookie = request.cookies.get("aimo_session")

        async def stream():
            import asyncio
            import json
            import time

            import anyio
            from fastapi.encoders import jsonable_encoder

            deadline, previous = time.monotonic() + 25, None
            while time.monotonic() < deadline and not await request.is_disconnected():
                # Revocation/session expiry continues to apply after connection establishment.
                try:
                    current, _ = await anyio.to_thread.run_sync(auth.browser_identity, cookie)
                    data = await anyio.to_thread.run_sync(
                        conversations.detail, current, conversation_id
                    )
                except Problem:
                    yield "event: expired\ndata: {}\n\n"
                    return
                value = json.dumps(jsonable_encoder(data), separators=(",", ":"))
                if value != previous:
                    yield f"event: conversation\ndata: {value}\n\n"
                    previous = value
                else:
                    yield ": keep-alive\n\n"
                await asyncio.sleep(2)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-store",
                "X-Accel-Buffering": "no",
            },
        )


    return app


app = create_app()
