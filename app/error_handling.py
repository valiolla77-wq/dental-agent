"""FastAPI middleware and exception handlers for the API error contract."""

import logging
import uuid
from contextvars import ContextVar
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.errors import AppError, ERROR_CATALOG


logger = logging.getLogger("dental_agent.errors")
request_id_context: ContextVar[str | None] = ContextVar(
    "request_id", default=None
)


def _error_response(
    code: str,
    request_id: str,
    details: dict[str, Any] | None = None,
) -> JSONResponse:
    definition = ERROR_CATALOG[code]
    return JSONResponse(
        status_code=definition.status_code,
        headers={"X-Request-ID": request_id},
        content={
            "error": {
                "code": definition.code,
                "message": definition.message,
                "details": details or {},
                "request_id": request_id,
            }
        },
    )


def _request_id(request: Request) -> str:
    return (
        getattr(request.state, "request_id", None)
        or request_id_context.get()
        or str(uuid.uuid4())
    )


def _validation_reason(error_type: str) -> str:
    if error_type == "missing":
        return "required"
    if "parsing" in error_type or "type" in error_type:
        return "invalid_format"
    return "invalid_value"


class RequestIdMiddleware:
    """Pure ASGI middleware; client-supplied request IDs are ignored."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = str(uuid.uuid4())
        scope.setdefault("state", {})["request_id"] = request_id
        token = request_id_context.set(request_id)

        async def send_with_request_id(message):
            if message["type"] == "http.response.start":
                headers = [
                    (name, value)
                    for name, value in message.get("headers", [])
                    if name.lower() != b"x-request-id"
                ]
                headers.append((b"x-request-id", request_id.encode("ascii")))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            request_id_context.reset(token)


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    request_id = _request_id(request)
    definition = exc.definition
    log_method = getattr(logger, definition.logging_level.lower())
    log_method(
        "API error %s",
        exc.code,
        extra={"request_id": request_id, "error_code": exc.code},
    )
    return _error_response(exc.code, request_id, exc.details)


async def validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    fields = []
    for error in exc.errors():
        location = error.get("loc", ())
        # Exclude transport prefixes and never echo the rejected value/message.
        field_path = ".".join(
            str(part)
            for part in location
            if part not in {"body", "query", "path", "header", "cookie"}
        )
        fields.append(
            {
                "field": field_path,
                "reason": _validation_reason(str(error.get("type", ""))),
            }
        )

    definition = ERROR_CATALOG["COMMON_VALIDATION_ERROR"]
    logger.info(
        "API validation error",
        extra={"request_id": _request_id(request), "error_code": definition.code},
    )
    return _error_response(
        definition.code,
        _request_id(request),
        {"fields": fields},
    )


async def http_error_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    if exc.status_code == 400:
        code = "COMMON_BAD_REQUEST"
    elif exc.status_code == 401:
        code = "COMMON_UNAUTHORIZED"
    elif exc.status_code == 403:
        code = "COMMON_FORBIDDEN"
    elif exc.status_code == 404:
        code = "COMMON_NOT_FOUND"
    elif exc.status_code == 405:
        code = "COMMON_METHOD_NOT_ALLOWED"
    elif exc.status_code == 409:
        code = "COMMON_CONFLICT"
    else:
        # Application routes use AppError for catalogued client errors.
        code = "INTERNAL_ERROR"
        logger.error(
            "Uncatalogued HTTP exception with status %s",
            exc.status_code,
            extra={"request_id": _request_id(request), "error_code": code},
        )
        return _error_response(code, _request_id(request))

    definition = ERROR_CATALOG[code]
    getattr(logger, definition.logging_level.lower())(
        "API error %s",
        code,
        extra={"request_id": _request_id(request), "error_code": code},
    )
    return _error_response(code, _request_id(request))


async def database_error_handler(
    request: Request, exc: SQLAlchemyError
) -> JSONResponse:
    request_id = _request_id(request)
    logger.exception(
        "Database operation failed",
        exc_info=(type(exc), exc, exc.__traceback__),
        extra={"request_id": request_id, "error_code": "DATABASE_ERROR"},
    )
    return _error_response("DATABASE_ERROR", request_id)


async def internal_error_handler(request: Request, exc: Exception) -> JSONResponse:
    if isinstance(exc, SQLAlchemyError):
        return await database_error_handler(request, exc)

    request_id = _request_id(request)
    logger.exception(
        "Unhandled application exception",
        exc_info=(type(exc), exc, exc.__traceback__),
        extra={"request_id": request_id, "error_code": "INTERNAL_ERROR"},
    )
    return _error_response("INTERNAL_ERROR", request_id)


def configure_error_handling(app: FastAPI) -> None:
    app.add_middleware(RequestIdMiddleware)
    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_error_handler)
    app.add_exception_handler(Exception, internal_error_handler)
