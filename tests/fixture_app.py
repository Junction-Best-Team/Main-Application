"""Explicit offline API test harness. This module is not shipped in app images.

Run with UPSTREAM_MODE=fixture and uvicorn --app-dir tests fixture_app:app.
"""

from supplier_fixture import install

from aimo.config import settings

if settings().upstream_mode != "fixture":
    raise RuntimeError("The fixture test harness requires UPSTREAM_MODE=fixture.")
install()

from aimo.api import app  # noqa: E402, F401
