import hashlib
import secrets
from datetime import timedelta

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from itsdangerous import BadSignature, URLSafeTimedSerializer

from aimo.config import settings
from aimo.db import Problem, connection, now

hasher = PasswordHasher()
DUMMY_HASH = hasher.hash("not-a-valid-account-password")


def digest(secret):
    return hashlib.sha256(secret.encode()).hexdigest()


def agent_identity(authorization: str | None):
    if not authorization or not authorization.startswith("Bearer "):
        raise Problem("UNAUTHENTICATED", "A scoped agent bearer credential is required.", 401)
    with connection() as c:
        identity = c.execute(
            "SELECT * FROM identities WHERE role='agent' AND active AND credential_hash=%s",
            (digest(authorization[7:]),),
        ).fetchone()
    if not identity:
        raise Problem("UNAUTHENTICATED", "Invalid agent credential.", 401)
    return identity


def signer():
    secret = settings().approval_session_secret
    if len(secret) < 32:
        raise Problem(
            "SESSION_NOT_CONFIGURED", "Set a private session secret of at least 32 characters.", 503
        )
    return URLSafeTimedSerializer(secret, salt="aimo-buyer-session-v1")


def login(username, password, remote):
    current = now()
    key = digest(remote + ":" + username)
    # Persist the limiter before password verification, including failed login attempts.
    with connection() as c:
        row = c.execute(
            """INSERT INTO login_attempts(key,attempts,window_start) VALUES(%s,1,%s)
          ON CONFLICT(key) DO UPDATE SET attempts=CASE WHEN login_attempts.window_start < %s THEN 1 ELSE login_attempts.attempts+1 END,
          window_start=CASE WHEN login_attempts.window_start < %s THEN %s ELSE login_attempts.window_start END RETURNING attempts""",
            (key, current, current - timedelta(minutes=5), current - timedelta(minutes=5), current),
        ).fetchone()
    if row["attempts"] > 10:
        raise Problem("LOGIN_RATE_LIMIT", "Too many attempts. Try again after five minutes.", 429)
    with connection() as c:
        identity = c.execute(
            "SELECT * FROM identities WHERE id=%s AND role='approver' AND active", (username,)
        ).fetchone()
        try:
            valid = hasher.verify(identity["credential_hash"] if identity else DUMMY_HASH, password)
        except VerificationError:
            valid = False
        if not identity or not valid:
            raise Problem("LOGIN_FAILED", "Username or password is incorrect.", 401)
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        c.execute(
            "INSERT INTO sessions VALUES(%s,%s,%s,%s)",
            (digest(token), username, digest(csrf), current + timedelta(hours=8)),
        )
    return identity, signer().dumps({"token": token, "csrf": csrf}), csrf


def browser_identity(cookie: str | None):
    try:
        data = signer().loads(cookie or "", max_age=8 * 3600)
        with connection() as c:
            row = c.execute(
                """SELECT i.*,s.csrf_hash FROM sessions s JOIN identities i ON i.id=s.identity_id
                WHERE s.token_hash=%s AND s.expires_at>%s AND i.active AND i.role='approver' """,
                (digest(data["token"]), now()),
            ).fetchone()
        if not row:
            raise BadSignature("inactive")
        return row, data
    except (BadSignature, KeyError):
        raise Problem("UNAUTHENTICATED", "Log in to the buyer inbox.", 401) from None


def check_origin(origin):
    if origin != settings().public_base_url.rstrip("/"):
        raise Problem("ORIGIN_REJECTED", "A same-origin browser request is required.", 403)


def csrf_check(identity, token, origin):
    check_origin(origin)
    if not token or not secrets.compare_digest(digest(token), identity["csrf_hash"]):
        raise Problem("CSRF_REJECTED", "Refresh the page before making a decision.", 403)
