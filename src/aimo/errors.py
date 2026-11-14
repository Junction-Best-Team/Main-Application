"""One error body for every HTTP error: {"error": {"code", "message", "details"?}} (TCT-008).

`install(app)` registers the handlers and declares the envelope in the OpenAPI document. Nothing
the client submitted (`input`, `ctx`) and nothing internal (exception text, traceback) is sent.
"""

from http import HTTPStatus

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response

from aimo.db import Problem
from aimo.observability import event
from aimo.schemas import ErrorResponse

# Stable codes for the statuses the framework and our routes use; others derive from the phrase.
CODES = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    413: "PAYLOAD_TOO_LARGE",
    415: "UNSUPPORTED_MEDIA_TYPE",
    422: "UNPROCESSABLE_ENTITY",
    429: "TOO_MANY_REQUESTS",
    500: "INTERNAL_ERROR",
    502: "BAD_GATEWAY",
    503: "SERVICE_UNAVAILABLE",
    504: "GATEWAY_TIMEOUT",
}
MESSAGES = {
    404: "Not found.",
    405: "Method not allowed.",
    413: "Request body too large.",
    500: "The service hit an unexpected error. Try again.",
}
CLIENT_ERROR = "The request could not be processed."
SERVER_ERROR = "The service could not complete this request. Try again."
LOCATIONS = {"body", "query", "path", "header", "cookie"}


def status_code_name(status: int) -> str:
    if status in CODES:
        return CODES[status]
    try:
        return (
            HTTPStatus(status).phrase.upper().replace("'", "").replace(" ", "_").replace("-", "_")
        )
    except ValueError:
        return f"HTTP_{status}"


def envelope(code: str, message: str, details=None) -> dict:
    error = {"code": code, "message": message}
    if details is not None:
        error["details"] = details
    return {"error": error}


def http_message(exc: StarletteHTTPException) -> str:
    """A route's own plain-text detail; the framework's default phrase and non-text details are replaced."""
    try:
        default = HTTPStatus(exc.status_code).phrase
    except ValueError:
        default = ""
    if isinstance(exc.detail, str) and exc.detail and exc.detail != default:
        return exc.detail
    return MESSAGES.get(exc.status_code, SERVER_ERROR if exc.status_code >= 500 else CLIENT_ERROR)


def validation_summary(errors: list[dict]) -> str:
    first = errors[0]
    if first["type"] == "json_invalid":
        return "The request body is not valid JSON."
    path = [str(part) for part in first["loc"] if part not in LOCATIONS]
    field = ".".join(path) or "request body"
    text = f"{field} is required." if first["type"] == "missing" else f"{field} is invalid."
    if len(errors) > 1:
        text = f"{text[:-1]} (and {len(errors) - 1} more)."
    return text[0].upper() + text[1:] if text.startswith("request body") else text


def install(app: FastAPI) -> None:
    """Register the handlers and the default 4XX/5XX responses. Call before adding routes."""

    @app.exception_handler(Problem)
    async def problem_handler(request: Request, exc: Problem):
        event("http.problem", error_code=exc.code, status=exc.status, retry_after=exc.retry_after)
        return JSONResponse(
            {"error": exc.body() if hasattr(exc, "body") else envelope(exc.code, exc.message)},
            status_code=exc.status,
            headers={"Retry-After": str(exc.retry_after)} if exc.retry_after is not None else None,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):
        # type/loc/msg only: never the submitted `input` (a password, or the whole body for a
        # missing field) or `ctx` (which can carry the parser's error text).
        errors = [
            {"type": error["type"], "loc": list(error["loc"]), "msg": error["msg"]}
            for error in exc.errors()
        ]
        return JSONResponse(
            envelope("VALIDATION_ERROR", validation_summary(errors), jsonable_encoder(errors)),
            status_code=422,
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        headers = getattr(exc, "headers", None)
        if exc.status_code in (204, 304) or exc.status_code < 200:  # no body allowed
            return Response(status_code=exc.status_code, headers=headers)
        return JSONResponse(
            envelope(status_code_name(exc.status_code), http_message(exc)),
            status_code=exc.status_code,
            headers=headers,
        )

    @app.exception_handler(Exception)
    async def unhandled_handler(request: Request, exc: Exception):
        # Served by Starlette's outermost middleware, which still re-raises so the request logger
        # and the server record it; the body carries nothing about the exception.
        return JSONResponse(envelope("INTERNAL_ERROR", MESSAGES[500]), status_code=500)

    schema = {"model": ErrorResponse}
    app.router.responses = {
        **app.router.responses,
        "4XX": {"description": "Error. Every error body is an ErrorResponse.", **schema},
        "5XX": {"description": "Server error. Every error body is an ErrorResponse.", **schema},
    }
    _declare_validation_errors(app)


def _declare_validation_errors(app: FastAPI) -> None:
    """FastAPI adds its own 422 `HTTPValidationError` to operations with input unless a 4XX is
    declared. Declare 422 as the envelope, and only where the operation takes input."""
    build = app.openapi

    def openapi():
        if app.openapi_schema is None:
            document = build()
            for item in document["paths"].values():
                for operation in item.values():
                    if operation.get("parameters") or operation.get("requestBody"):
                        operation["responses"].setdefault(
                            "422",
                            {
                                "description": "Validation error.",
                                "content": {
                                    "application/json": {
                                        "schema": {"$ref": "#/components/schemas/ErrorResponse"}
                                    }
                                },
                            },
                        )
            app.openapi_schema = document
        return app.openapi_schema

    app.openapi = openapi
