"""Durable one-image-per-turn work; a generation is never implicitly repeated."""

from datetime import timedelta
from uuid import UUID, uuid4

import httpx

from aimo.config import settings
from aimo.db import Problem, connection, fingerprint, js, now
from aimo.image_provider import cloudinary_credentials, generate_image, upload_image
from aimo.image_schemas import RecipeImage


def active_turn(c, identity):
    try:
        turn_id, attempt = UUID(identity["_turn_id"]), UUID(identity["_attempt"])
    except (KeyError, ValueError, TypeError):
        raise Problem(
            "IMAGE_TURN_REQUIRED", "Illustrations require an active chat message.", 422
        ) from None
    row = c.execute(
        """SELECT t.id FROM conversation_turns t
        JOIN conversations c ON c.id=t.conversation_id
        JOIN internal_agents a ON a.buyer_id=c.buyer_id
        WHERE t.id=%s AND t.attempt=%s AND t.state='running' AND t.lease_until>%s
        AND c.buyer_id=%s AND a.identity_id=%s""",
        (turn_id, attempt, now(), identity["buyer_id"], identity["id"]),
    ).fetchone()
    if not row:
        raise Problem("IMAGE_TURN_REQUIRED", "Illustrations require an active chat message.", 422)
    return turn_id


def generate(identity, request):
    cfg = settings()
    if not cfg.recipe_images_enabled or not cfg.gemini_api_key.strip():
        raise Problem("IMAGE_NOT_CONFIGURED", "Recipe illustrations are unavailable.", 503)
    cloudinary_credentials(cfg.cloudinary_url)  # Validate hosting before spending generation quota.
    with connection() as c:
        turn_id = active_turn(c, identity)
        c.execute("SELECT id FROM buyers WHERE id=%s FOR UPDATE", (identity["buyer_id"],))
        c.execute(
            "UPDATE recipe_image_jobs SET state='failed',image_bytes=NULL "
            "WHERE buyer_id=%s AND state='generated' AND created_at<%s",
            (identity["buyer_id"], now() - timedelta(hours=24)),
        )
        job = c.execute("SELECT * FROM recipe_image_jobs WHERE turn_id=%s", (turn_id,)).fetchone()
        if job is None:
            count = c.execute(
                "SELECT count(*) AS n FROM recipe_image_jobs WHERE buyer_id=%s AND created_at>%s",
                (identity["buyer_id"], now() - timedelta(hours=1)),
            ).fetchone()["n"]
            if count >= cfg.recipe_image_hourly_limit:
                raise Problem(
                    "IMAGE_RATE_LIMIT", "This account reached its hourly illustration limit.", 429
                )
            job = c.execute(
                """INSERT INTO recipe_image_jobs(turn_id,buyer_id,request_hash,public_id,state)
                VALUES(%s,%s,%s,%s,'generating') RETURNING *""",
                (
                    turn_id,
                    identity["buyer_id"],
                    fingerprint(request.model_dump()),
                    "aimo/recipe-illustrations/" + uuid4().hex,
                ),
            ).fetchone()
            new = True
        else:
            new = False
    if job["state"] == "complete":
        return RecipeImage.model_validate(job["image"])
    if not new and job["state"] != "generated":
        # An interrupted generation may already be billed. A new message is explicit new work.
        raise Problem(
            "IMAGE_ALREADY_REQUESTED",
            "An illustration was already attempted for this message. Continue with the recipe "
            "text; ask in a new message for a new illustration.",
            409,
        )
    with httpx.Client(follow_redirects=False) as client:
        if new:
            try:
                data, mime = generate_image(cfg, request, client)
            except Problem:
                with connection() as c:
                    c.execute(
                        "UPDATE recipe_image_jobs SET state='failed' WHERE turn_id=%s", (turn_id,)
                    )
                raise
            # Save bytes before upload so hosting failures/restarts never regenerate them.
            with connection() as c:
                c.execute(
                    "UPDATE recipe_image_jobs SET state='generated',image_bytes=%s,mime_type=%s WHERE turn_id=%s",
                    (data, mime, turn_id),
                )
        else:
            data, mime = bytes(job["image_bytes"]), job["mime_type"]
        with connection() as c:
            # A replaced worker may save bytes but must stop external work.
            active_turn(c, identity)
        image = upload_image(cfg, data, mime, job["public_id"], client)
    with connection() as c:
        c.execute(
            "UPDATE recipe_image_jobs SET state='complete',image=%s,image_bytes=NULL WHERE turn_id=%s",
            (js(image.model_dump()), turn_id),
        )
    return image
