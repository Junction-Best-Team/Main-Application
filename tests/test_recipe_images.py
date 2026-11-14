"""Authored food/image fixtures and HTTP transports; no paid provider calls."""

import base64
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from aimo import auth, conversations, image_provider, recipe_images
from aimo.agent_tools import ToolSession
from aimo.chat_schemas import AgentTurn, ConversationCreate, MessageRequest
from aimo.db import Problem, connection, now
from aimo.image_schemas import RecipeImage, RecipeImageRequest

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII="
)
PUBLIC_ID = "aimo/recipe-illustrations/" + "a" * 32
IMAGE = RecipeImage(
    url=f"https://res.cloudinary.com/test-cloud/image/upload/v123/{PUBLIC_ID}.png",
    width=1024,
    height=768,
)
REQUEST = RecipeImageRequest(dish="Tomato pasta", description="Pasta with tomato sauce and basil.")


@pytest.fixture
def image_cfg(monkeypatch):
    cfg = SimpleNamespace(
        gemini_api_key="synthetic-google",
        cloudinary_url="cloudinary://test-key:test-secret@test-cloud",
        recipe_images_enabled=True,
        recipe_image_model="gemini-nano-banana-2.1",
        recipe_image_timeout_seconds=45,
        recipe_image_hourly_limit=5,
    )
    monkeypatch.setattr(recipe_images, "settings", lambda: cfg)
    return cfg


def new_turn(buyer):
    cid = conversations.create(buyer, ConversationCreate(idempotency_key=str(uuid4())))["id"]
    conversations.enqueue(
        buyer, cid, MessageRequest(text="Show tomato pasta", idempotency_key=str(uuid4()))
    )
    turn = conversations.claim_turn(cid)
    return auth.internal_agent(buyer) | {
        "_turn_id": str(turn["id"]),
        "_attempt": str(turn["attempt"]),
    }, turn


@pytest.fixture
def providers(monkeypatch):
    calls = {"generate": 0, "upload": 0}

    def generate(*args):
        calls["generate"] += 1
        return PNG, "image/png"

    def upload(*args):
        calls["upload"] += 1
        return IMAGE

    monkeypatch.setattr(recipe_images, "generate_image", generate)
    monkeypatch.setattr(recipe_images, "upload_image", upload)
    return calls


def test_tool_result_persists_with_text_and_refresh_and_accepted_retry_reuses_it(
    buyer,
    service,
    image_cfg,
    providers,
):
    actor, turn = new_turn(buyer)

    def runner(actor, history, service):
        session = ToolSession(actor, service)
        for _ in range(2):
            session.invoke("generate_recipe_image", REQUEST.model_dump_json())
        return session.result("Here is the tomato pasta illustration.")

    saved = conversations.execute_turn(turn, service, runner)
    refreshed = conversations.detail(buyer, turn["conversation_id"])
    reply = refreshed["messages"][-1]
    assert reply["text"] == saved["messages"][-1]["text"]
    assert reply["image"] == IMAGE.model_dump()
    assert reply["meal_plan"] is None and reply["proposal_id"] is None
    with connection() as c:
        row = c.execute(
            "SELECT * FROM recipe_image_jobs WHERE turn_id=%s", (turn["id"],)
        ).fetchone()
        assert row["state"] == "complete" and row["image_bytes"] is None
    conversations.enqueue(
        buyer,
        turn["conversation_id"],
        MessageRequest(
            text="Show tomato pasta",
            idempotency_key=turn["key"],
        ),
    )
    assert providers == {"generate": 1, "upload": 1}


def test_same_turn_reuses_completed_image_after_worker_restart(buyer, image_cfg, providers):
    actor, _ = new_turn(buyer)
    assert recipe_images.generate(actor, REQUEST) == IMAGE
    changed = RecipeImageRequest(dish="Another dish", description="A different visual brief")
    assert recipe_images.generate(actor, changed) == IMAGE
    assert providers == {"generate": 1, "upload": 1}


def test_uploaded_image_is_recovered_when_restarted_runner_returns_only_text(
    buyer,
    service,
    image_cfg,
    providers,
):
    actor, turn = new_turn(buyer)
    recipe_images.generate(actor, REQUEST)  # The earlier worker uploaded, then stopped.
    result = conversations.execute_turn(
        turn, service, lambda *args: AgentTurn(text="Your saved illustration was recovered.")
    )
    assert result["messages"][-1]["image"] == IMAGE.model_dump()
    assert providers == {"generate": 1, "upload": 1}


def test_old_pending_bytes_are_discarded_without_another_generation(
    buyer,
    image_cfg,
    providers,
    monkeypatch,
):
    actor, turn = new_turn(buyer)
    monkeypatch.setattr(
        recipe_images,
        "upload_image",
        lambda *args: (_ for _ in ()).throw(
            Problem("IMAGE_UPLOAD_UNAVAILABLE", "Hosting unavailable", 503)
        ),
    )
    with pytest.raises(Problem):
        recipe_images.generate(actor, REQUEST)
    with connection() as c:
        c.execute(
            "UPDATE recipe_image_jobs SET created_at=%s WHERE turn_id=%s",
            (now() - timedelta(hours=25), turn["id"]),
        )
    with pytest.raises(Problem) as caught:
        recipe_images.generate(actor, REQUEST)
    assert caught.value.code == "IMAGE_ALREADY_REQUESTED"
    with connection() as c:
        row = c.execute(
            "SELECT state,image_bytes FROM recipe_image_jobs WHERE turn_id=%s", (turn["id"],)
        ).fetchone()
        assert row == {"state": "failed", "image_bytes": None}
    assert providers["generate"] == 1


def test_hosting_failure_keeps_bytes_and_retry_does_not_generate_again(
    buyer,
    image_cfg,
    providers,
    monkeypatch,
):
    actor, turn = new_turn(buyer)
    upload = recipe_images.upload_image
    monkeypatch.setattr(
        recipe_images,
        "upload_image",
        lambda *a: (_ for _ in ()).throw(
            Problem("IMAGE_UPLOAD_UNAVAILABLE", "Hosting unavailable", 503)
        ),
    )
    with pytest.raises(Problem, match="Hosting"):
        recipe_images.generate(actor, REQUEST)
    with connection() as c:
        row = c.execute(
            "SELECT * FROM recipe_image_jobs WHERE turn_id=%s", (turn["id"],)
        ).fetchone()
        assert row["state"] == "generated" and bytes(row["image_bytes"]) == PNG
    monkeypatch.setattr(recipe_images, "upload_image", upload)
    assert recipe_images.generate(actor, REQUEST) == IMAGE
    assert providers == {"generate": 1, "upload": 1}


def test_ambiguous_generation_failure_never_retries(buyer, image_cfg, providers, monkeypatch):
    actor, _ = new_turn(buyer)
    calls = []

    def fail(*args):
        calls.append(1)
        raise Problem("IMAGE_GENERATION_UNAVAILABLE", "Unavailable", 503)

    monkeypatch.setattr(recipe_images, "generate_image", fail)
    with pytest.raises(Problem):
        recipe_images.generate(actor, REQUEST)
    with pytest.raises(Problem) as caught:
        recipe_images.generate(actor, REQUEST)
    assert caught.value.code == "IMAGE_ALREADY_REQUESTED"
    assert len(calls) == 1 and providers["upload"] == 0


def test_concurrent_calls_spend_once(buyer, image_cfg, providers, monkeypatch):
    actor, _ = new_turn(buyer)
    entered, release = Event(), Event()

    def slow(*args):
        providers["generate"] += 1
        entered.set()
        assert release.wait(5)
        return PNG, "image/png"

    monkeypatch.setattr(recipe_images, "generate_image", slow)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(recipe_images.generate, actor, REQUEST)
        try:
            assert entered.wait(5)
            with pytest.raises(Problem) as caught:
                recipe_images.generate(actor, REQUEST)
            assert caught.value.code == "IMAGE_ALREADY_REQUESTED"
        finally:
            release.set()
        assert future.result() == IMAGE
    assert providers == {"generate": 1, "upload": 1}


def test_hourly_limit_binds_to_buyer_across_conversations(buyer, image_cfg, providers):
    image_cfg.recipe_image_hourly_limit = 1
    actor, _ = new_turn(buyer)
    recipe_images.generate(actor, REQUEST)
    other, _ = new_turn(buyer)
    with pytest.raises(Problem) as caught:
        recipe_images.generate(other, REQUEST)
    assert caught.value.code == "IMAGE_RATE_LIMIT"
    assert providers["generate"] == 1


@pytest.mark.parametrize("change", ["scope", "attempt", "expired"])
def test_invalid_turn_cannot_generate_or_retrieve_images(buyer, image_cfg, providers, change):
    actor, turn = new_turn(buyer)
    if change == "scope":
        actor["buyer_id"] = "other-buyer"
    elif change == "attempt":
        actor["_attempt"] = str(uuid4())
    else:
        with connection() as c:
            c.execute(
                "UPDATE conversation_turns SET lease_until=%s WHERE id=%s",
                (now() - timedelta(seconds=1), turn["id"]),
            )
    with pytest.raises(Problem) as caught:
        recipe_images.generate(actor, REQUEST)
    assert caught.value.code == "IMAGE_TURN_REQUIRED"
    assert providers == {"generate": 0, "upload": 0}


@pytest.mark.parametrize(
    "field,value",
    [
        ("recipe_images_enabled", False),
        ("gemini_api_key", ""),
        ("cloudinary_url", "cloudinary://invalid"),
    ],
)
def test_missing_configuration_never_spends(buyer, image_cfg, providers, field, value):
    setattr(image_cfg, field, value)
    actor, _ = new_turn(buyer)
    with pytest.raises(Problem) as caught:
        recipe_images.generate(actor, REQUEST)
    assert caught.value.code == "IMAGE_NOT_CONFIGURED"
    assert providers == {"generate": 0, "upload": 0}


def test_google_image_bytes_only_and_no_conversation_fields(image_cfg):
    def handler(request):
        assert request.url.host == "generativelanguage.googleapis.com"
        assert request.headers["x-goog-api-key"] == "synthetic-google"
        body = json.loads(request.content)
        assert body["generationConfig"]["imageConfig"] == {"aspectRatio": "4:3", "imageSize": "1K"}
        assert set(body) == {"contents", "generationConfig"}
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "finishReason": "STOP",
                        "content": {
                            "parts": [
                                {"text": "ignored provider prose"},
                                {
                                    "inlineData": {
                                        "mimeType": "image/png",
                                        "data": base64.b64encode(PNG).decode(),
                                    }
                                },
                            ],
                        },
                    }
                ]
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert image_provider.generate_image(image_cfg, REQUEST, client) == (PNG, "image/png")


@pytest.mark.parametrize(
    "parts,finish",
    [
        ([{"text": "No image"}], "STOP"),
        ([{"inlineData": {"mimeType": "image/svg+xml", "data": "secret"}}], "STOP"),
        ([{"inlineData": {"mimeType": "image/png", "data": "bad-base64"}}], "STOP"),
        (
            [{"inlineData": {"mimeType": "image/png", "data": base64.b64encode(PNG).decode()}}],
            "SAFETY",
        ),
    ],
)
def test_missing_blocked_or_invalid_image_is_a_safe_error(image_cfg, parts, finish):
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(
                200,
                json={
                    "candidates": [{"finishReason": finish, "content": {"parts": parts}}],
                },
            )
        )
    ) as client:
        with pytest.raises(Problem) as caught:
            image_provider.generate_image(image_cfg, REQUEST, client)
    assert caught.value.code == "IMAGE_NOT_RETURNED"
    assert "secret" not in caught.value.message


def test_cloudinary_upload_is_signed_and_uses_our_delivery_url(image_cfg, monkeypatch):
    monkeypatch.setattr(image_provider.time, "time", lambda: 123)
    signature = hashlib.sha256(
        f"overwrite=true&public_id={PUBLIC_ID}&timestamp=123test-secret".encode()
    ).hexdigest()

    def handler(request):
        assert str(request.url) == "https://api.cloudinary.com/v1_1/test-cloud/image/upload"
        assert signature.encode() in request.content
        assert b"test-secret" not in request.content
        assert PNG in request.content
        return httpx.Response(
            200,
            json={
                "public_id": PUBLIC_ID,
                "version": 123,
                "format": "png",
                "width": 1024,
                "height": 768,
                "secure_url": "https://attacker.example/tracking.png",
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = image_provider.upload_image(image_cfg, PNG, "image/png", PUBLIC_ID, client)
    assert result.url.startswith("https://res.cloudinary.com/test-cloud/image/upload/")
    assert "attacker" not in result.url


@pytest.mark.parametrize("status", [302, 401, 429, 500])
def test_upload_errors_are_safe_and_never_redirect_or_retry(image_cfg, status):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            status, text="test-secret", headers={"Location": "https://attacker.example"}
        )

    with httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True) as client:
        with pytest.raises(Problem) as caught:
            image_provider.upload_image(image_cfg, PNG, "image/png", PUBLIC_ID, client)
    assert caught.value.code == "IMAGE_UPLOAD_UNAVAILABLE"
    assert "test-secret" not in str(caught.value)
    assert len(calls) == 1
