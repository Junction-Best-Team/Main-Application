import logging
from contextlib import asynccontextmanager
from secrets import token_urlsafe
from typing import Literal
from urllib.parse import quote
from uuid import UUID

from fastapi import Depends, FastAPI, Query, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse, StreamingResponse

from aimo import approval_workflow as workflow
from aimo import (
    auth,
    cancellations,
    cart_purchase,
    clock,
    conversations,
    errors,
    memory,
    orders_list,
    policy_settings,
    schedules,
    schema_state,
    upstream,
    voice,
)
from aimo.attachments import raw_file
from aimo.chat_schemas import (
    CartEditRequest,
    CartPurchaseRequest,
    CartPurchaseResponse,
    ConversationCreate,
    ConversationList,
    ConversationResponse,
    MessageRequest,
)
from aimo.config import settings
from aimo.db import Problem, close_pools, connection
from aimo.memory_schemas import (
    Kind,
    MemoryChange,
    MemoryCreate,
    MemoryDelete,
    MemoryList,
    MemoryMutationResponse,
    MemorySearch,
    MemoryUpdate,
)
from aimo.observability import RequestLoggingMiddleware, configure_logging, event
from aimo.order_schemas import CancellationResponse, OrdersResponse
from aimo.request_limits import MessageBodyLimitMiddleware
from aimo.schedule_schemas import (
    ScheduleCreateRequest,
    ScheduleDetail,
    ScheduleEditPreviewRequest,
    ScheduleList,
    SchedulePreviewRequest,
    ScheduleReplaceRequest,
    ScheduleResponse,
    ScheduleTerms,
    SubstituteCandidates,
)
from aimo.schemas import (
    CommitRequest,
    CommitResponse,
    DecisionRequest,
    DemoClockAdvance,
    DemoClockReset,
    DemoClockState,
    InboxResponse,
    LoginRequest,
    OrderResponse,
    ProposalResponse,
    SessionResponse,
)
from aimo.service import Service

CONTENT_SECURITY_POLICY = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: https://res.cloudinary.com; "
    "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
)


def create_app(service=None):
    service = service or Service()

    @asynccontextmanager
    async def lifespan(app):
        import anyio

        configure_logging()
        upstream.check_supplier_startup()  # a hosted deployment must not start without the key
        event("api.started", upstream_mode=upstream.effective_mode())
        try:
            yield
        finally:
            await anyio.to_thread.run_sync(close_pools)
            event("api.stopped")

    app = FastAPI(
        title="Aimo chat purchasing",
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        # Q-72: no /openapi.json unless API_DOCS_ENABLED. app.openapi() still builds the contract
        # for scripts/export_schema.py, which generates the committed file the typed client uses.
        openapi_url="/openapi.json" if settings().api_docs_enabled else None,
    )
    app.state.service = service

    if settings().api_docs_enabled:

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
            ).replace(
                "style-src 'self'", "style-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'"
            )
            return HTMLResponse(
                html.replace("<script", f'<script nonce="{nonce}"'),
                headers={"Content-Security-Policy": policy, "Cache-Control": "no-store"},
            )

    errors.install(app)  # one error body for every failure (TCT-008)

    @app.middleware("http")
    async def security_headers(request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        if settings().secure_cookies:  # an HTTPS deployment; local HTTP development sends no HSTS
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        if request.url.path != "/docs" or response.status_code != 200:
            response.headers["Content-Security-Policy"] = CONTENT_SECURITY_POLICY
        if request.url.path.startswith("/api"):
            response.headers["Cache-Control"] = "no-store"
        return response

    app.add_middleware(MessageBodyLimitMiddleware)
    app.add_middleware(RequestLoggingMiddleware)

    def buyer(request: Request):
        return auth.browser_identity(request.cookies.get("aimo_session"))[0]

    @app.get("/health/live")
    async def live():
        return {"status": "ok"}

    # Monitors often probe with HEAD. Not part of the published contract.
    @app.head("/health/live", include_in_schema=False)
    async def live_head():
        return Response(status_code=200)

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
        pending = schema_state.missing_migrations()
        if pending:
            # The names go to the server log only; the response says nothing internal.
            logging.getLogger(__name__).error("Database is missing migrations: %s", pending)
            raise Problem(
                "SCHEMA_NOT_READY",
                "The database schema is not up to date; run the migrations.",
                503,
            )
        # A bare status (Q-72): the embedding model and the supplier mode are in the startup log
        # (api.started), not in a public response.
        return {"status": "ready"}

    @app.head("/health/ready", include_in_schema=False)
    def ready_head():
        ready()  # same checks and same 503 as GET; only the body is dropped
        return Response(status_code=200)

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
        return {
            "username": identity["id"],
            "buyer_id": identity["buyer_id"],
            "csrf_token": csrf,
            "role": identity["role"],
            "scheduler_demo_mode": settings().scheduler_demo_mode,
        }

    @app.get("/api/session", response_model=SessionResponse)
    def session(request: Request):
        identity, data = auth.browser_identity(request.cookies.get("aimo_session"))
        return {
            "username": identity["id"],
            "buyer_id": identity["buyer_id"],
            "csrf_token": data["csrf"],
            "role": identity["role"],
            "scheduler_demo_mode": settings().scheduler_demo_mode,
        }

    @app.post("/api/logout", status_code=204)
    def logout(request: Request, response: Response, identity=Depends(buyer)):
        auth.csrf_check(
            identity, request.headers.get("x-csrf-token"), request.headers.get("origin")
        )
        _, data = auth.browser_identity(request.cookies.get("aimo_session"))
        with connection() as c:
            c.execute("DELETE FROM sessions WHERE token_hash=%s", (auth.digest(data["token"]),))
        response.delete_cookie(
            "aimo_session",
            path="/",
            httponly=True,
            secure=settings().secure_cookies,
            samesite="strict",
        )

    @app.get("/api/approvals", response_model=InboxResponse)
    def inbox(
        offset: int = Query(0, ge=0, le=10000),
        limit: int = Query(20, ge=1, le=50),
        identity=Depends(buyer),
    ):
        return workflow.list_approvals(identity, offset, limit)

    @app.get("/api/settings/policy", response_model=policy_settings.PolicySettings)
    def get_policy_settings(identity=Depends(buyer)):
        return policy_settings.get(identity)

    @app.put("/api/settings/policy", response_model=policy_settings.PolicySettings)
    def save_policy_settings(
        body: policy_settings.PolicyUpdate, request: Request, identity=Depends(buyer)
    ):
        auth.csrf_check(
            identity, request.headers.get("x-csrf-token"), request.headers.get("origin")
        )
        return policy_settings.update(identity, body)

    @app.get("/api/approvals/{approval_id}", response_model=ProposalResponse)
    def detail(approval_id: UUID, identity=Depends(buyer)):
        return workflow.approval_detail(identity, approval_id)

    @app.get("/api/purchases/{proposal_id}", response_model=ProposalResponse)
    def current_purchase(
        proposal_id: UUID,
        revision: int | None = Query(
            None, ge=1, description="An earlier revision of this proposal; default the current one."
        ),
        identity=Depends(buyer),
    ):
        return workflow.get_proposal(identity, proposal_id, revision)

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

    @app.get("/api/purchases/{proposal_id}/receipt", response_model=OrderResponse)
    def purchase_receipt(proposal_id: UUID, identity=Depends(buyer)):
        # The stored mock receipt of this buyer's own proposal; 404 NO_RECEIPT until it is ordered.
        return workflow.get_receipt(identity, proposal_id)

    # Demo clock (owner Q-115): customer controls that exist only while DEMO_CLOCK_ENABLED is on and
    # the supplier is not live; every route answers 404 otherwise. Never an agent tool.
    @app.get("/api/demo/clock", response_model=DemoClockState)
    def demo_clock_state(identity=Depends(buyer)):
        return clock.state(identity["buyer_id"])

    @app.post("/api/demo/clock/advance", response_model=DemoClockState)
    def demo_clock_advance(body: DemoClockAdvance, request: Request, identity=Depends(buyer)):
        auth.csrf_check(
            identity, request.headers.get("x-csrf-token"), request.headers.get("origin")
        )
        return clock.advance(
            identity["buyer_id"],
            identity["id"],
            days=body.days,
            to=body.to,
            idempotency_key=body.idempotency_key,
        )

    @app.post("/api/demo/clock/reset", response_model=DemoClockState)
    def demo_clock_reset(body: DemoClockReset, request: Request, identity=Depends(buyer)):
        auth.csrf_check(
            identity, request.headers.get("x-csrf-token"), request.headers.get("origin")
        )
        return clock.reset(
            identity["buyer_id"], identity["id"], idempotency_key=body.idempotency_key
        )

    @app.get("/api/memories", response_model=MemoryList)
    def memory_list(
        scope: Literal["all", "buyer", "self"] = "all",
        kind: Kind | None = None,
        q: str | None = Query(None, min_length=1, max_length=200),
        offset: int = Query(0, ge=0, le=100),
        limit: int = Query(20, ge=1, le=50),
        identity=Depends(buyer),
    ):
        request = MemorySearch(query=q, scope=scope, kind=kind, offset=offset, limit=limit)
        return memory.search(memory.browser_actor(identity), request)

    @app.post("/api/memories", response_model=MemoryMutationResponse)
    def memory_create(body: MemoryCreate, request: Request, identity=Depends(buyer)):
        auth.csrf_check(
            identity, request.headers.get("x-csrf-token"), request.headers.get("origin")
        )
        change = MemoryChange(
            action="save",
            scope=body.scope,
            key=body.key,
            value=body.value,
            description=body.description,
        )
        return memory.mutate(memory.browser_actor(identity), change, body.idempotency_key)

    @app.put("/api/memories/{memory_id}", response_model=MemoryMutationResponse)
    def memory_update(
        memory_id: UUID, body: MemoryUpdate, request: Request, identity=Depends(buyer)
    ):
        auth.csrf_check(
            identity, request.headers.get("x-csrf-token"), request.headers.get("origin")
        )
        change = MemoryChange(
            action="update",
            memory_id=memory_id,
            expected_revision=body.expected_revision,
            value=body.value,
            description=body.description,
        )
        return memory.mutate(memory.browser_actor(identity), change, body.idempotency_key)

    @app.post("/api/memories/{memory_id}/delete", response_model=MemoryMutationResponse)
    def memory_delete(
        memory_id: UUID, body: MemoryDelete, request: Request, identity=Depends(buyer)
    ):
        auth.csrf_check(
            identity, request.headers.get("x-csrf-token"), request.headers.get("origin")
        )
        change = MemoryChange(
            action="delete", memory_id=memory_id, expected_revision=body.expected_revision
        )
        return memory.mutate(memory.browser_actor(identity), change, body.idempotency_key)

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

    @app.get("/api/conversations/{conversation_id}/attachments/{message_id}/{index}")
    def conversation_attachment(
        conversation_id: UUID, message_id: int, index: int, identity=Depends(buyer)
    ):
        item = conversations.attachment(identity, conversation_id, message_id, index)
        disposition = "inline" if item["media_type"].startswith("image/") else "attachment"
        return Response(
            raw_file(item),
            media_type=item["media_type"],
            headers={
                "Content-Disposition": f"{disposition}; filename*=UTF-8''{quote(item['name'], safe='')}",
                "Cache-Control": "no-store",
            },
        )

    @app.post(
        "/api/conversations/{conversation_id}/prepare-from-cart",
        response_model=CartPurchaseResponse,
    )
    def conversation_prepare_from_cart(
        conversation_id: UUID,
        body: CartPurchaseRequest,
        request: Request,
        identity=Depends(buyer),
    ):
        """Prepare the cart's matched items as a basket, without the assistant. Nothing is ordered:
        the customer still confirms the exact revision."""
        auth.csrf_check(
            identity, request.headers.get("x-csrf-token"), request.headers.get("origin")
        )
        return cart_purchase.prepare_from_cart(identity, conversation_id, body, service)

    @app.put("/api/conversations/{conversation_id}/cart", response_model=CartPurchaseResponse)
    def conversation_edit_cart(
        conversation_id: UUID,
        body: CartEditRequest,
        request: Request,
        identity=Depends(buyer),
    ):
        """The customer's own pack-count edit of products already in the cart; prepares the basket
        again. Nothing is ordered."""
        auth.csrf_check(
            identity, request.headers.get("x-csrf-token"), request.headers.get("origin")
        )
        return cart_purchase.edit_cart(identity, conversation_id, body, service)

    @app.post("/api/conversations/{conversation_id}/messages", response_model=ConversationResponse)
    def send_message(
        conversation_id: UUID, body: MessageRequest, request: Request, identity=Depends(buyer)
    ):
        auth.csrf_check(
            identity, request.headers.get("x-csrf-token"), request.headers.get("origin")
        )
        return conversations.enqueue(identity, conversation_id, body)

    @app.post("/api/conversations/{conversation_id}/cancel", response_model=ConversationResponse)
    def cancel_conversation(conversation_id: UUID, request: Request, identity=Depends(buyer)):
        auth.csrf_check(
            identity, request.headers.get("x-csrf-token"), request.headers.get("origin")
        )
        return conversations.cancel_turn(identity, conversation_id)

    @app.post(
        "/api/conversations/{conversation_id}/voice-session", response_model=voice.VoiceSession
    )
    def voice_session(conversation_id: UUID, request: Request, identity=Depends(buyer)):
        auth.csrf_check(
            identity, request.headers.get("x-csrf-token"), request.headers.get("origin")
        )
        return voice.create_session(identity, conversation_id)

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

    @app.post("/api/purchases/{proposal_id}/cancel", response_model=CancellationResponse)
    def cancel_purchase(proposal_id: UUID, request: Request, identity=Depends(buyer)):
        auth.csrf_check(
            identity, request.headers.get("x-csrf-token"), request.headers.get("origin")
        )
        # CNF-035: an append-only cancellation of a pending request; a placed order is refused.
        return cancellations.cancel_my_request(identity, proposal_id)

    @app.get("/api/orders", response_model=OrdersResponse)
    def orders(
        offset: int = Query(0, ge=0, le=10000),
        limit: int = Query(20, ge=1, le=50),
        status: str | None = Query(
            None,
            max_length=80,
            description="Comma list of scheduled, pending, placed, cancelled; empty means all",
        ),
        q: str | None = Query(
            None,
            max_length=200,
            description="Search: trimmed, at most 80 characters, case-insensitive substring over "
            "titles, order and proposal ids, destination, delivery date, line names, product ids",
        ),
        identity=Depends(buyer),
    ):
        statuses = [s.strip() for s in (status or "").split(",") if s.strip()]
        return orders_list.orders_page(identity, offset, limit, statuses=statuses, query=q)

    def csrf(identity, request: Request):
        auth.csrf_check(
            identity, request.headers.get("x-csrf-token"), request.headers.get("origin")
        )

    # Standing orders (CNF-022 to CNF-037). Reads need the session; every POST also needs CSRF and
    # a same-origin request. The customer functions require the approver role themselves.
    @app.get("/api/schedules", response_model=ScheduleList)
    def schedule_list(
        offset: int = Query(0, ge=0, le=10000),
        limit: int = Query(20, ge=1, le=50),
        status: str | None = Query(None, description="Comma list of schedule statuses"),
        identity=Depends(buyer),
    ):
        wanted = tuple(x.strip() for x in status.split(",") if x.strip()) if status else ()
        return schedules.list_schedules(identity, offset, limit, wanted)

    # Registered before /api/schedules/{schedule_id}, or "substitute-candidates" is parsed as an id.
    @app.get("/api/schedules/substitute-candidates", response_model=SubstituteCandidates)
    def schedule_substitute_candidates(
        product_id: str = Query(min_length=1, max_length=40), identity=Depends(buyer)
    ):
        return schedules.substitute_candidates(identity, product_id, service)

    @app.post("/api/schedules/preview", response_model=ScheduleTerms)
    def schedule_preview(body: SchedulePreviewRequest, request: Request, identity=Depends(buyer)):
        csrf(identity, request)
        return schedules.preview(identity, body, service)

    @app.post("/api/schedules", response_model=ScheduleResponse)
    def schedule_create(body: ScheduleCreateRequest, request: Request, identity=Depends(buyer)):
        csrf(identity, request)
        return schedules.create(identity, body, service)

    @app.get("/api/schedules/{schedule_id}", response_model=ScheduleDetail)
    def schedule_detail(
        schedule_id: UUID,
        runs_offset: int = Query(0, ge=0, le=10000),
        identity=Depends(buyer),
    ):
        return schedules.get(identity, schedule_id, runs_offset)

    @app.post("/api/schedules/{schedule_id}/preview", response_model=ScheduleTerms)
    def schedule_edit_preview(
        schedule_id: UUID,
        body: ScheduleEditPreviewRequest,
        request: Request,
        identity=Depends(buyer),
    ):
        csrf(identity, request)
        return schedules.preview_edit(identity, schedule_id, body, service)

    @app.post("/api/schedules/{schedule_id}/replace", response_model=ScheduleResponse)
    def schedule_replace(
        schedule_id: UUID,
        body: ScheduleReplaceRequest,
        request: Request,
        identity=Depends(buyer),
    ):
        csrf(identity, request)
        return schedules.replace(identity, schedule_id, body, service)

    @app.post("/api/schedules/{schedule_id}/cancel", response_model=ScheduleResponse)
    def schedule_cancel(schedule_id: UUID, request: Request, identity=Depends(buyer)):
        csrf(identity, request)
        return schedules.cancel(identity, schedule_id)

    @app.post("/api/schedules/{schedule_id}/run-now", response_model=ScheduleResponse)
    def schedule_run_now(schedule_id: UUID, request: Request, identity=Depends(buyer)):
        csrf(identity, request)
        # DEMO ONLY (CNF-038): 403 SCHEDULE_DEMO_DISABLED unless SCHEDULER_DEMO_MODE is on.
        return schedules.run_now(identity, schedule_id, service)

    @app.post("/api/schedules/{schedule_id}/pause", response_model=ScheduleResponse)
    def schedule_pause(schedule_id: UUID, request: Request, identity=Depends(buyer)):
        csrf(identity, request)
        return schedules.pause(identity, schedule_id)

    @app.post("/api/schedules/{schedule_id}/resume", response_model=ScheduleResponse)
    def schedule_resume(schedule_id: UUID, request: Request, identity=Depends(buyer)):
        csrf(identity, request)
        return schedules.resume(identity, schedule_id)

    return app


app = create_app()
