"""FastAPI application factory with the uniform error envelope."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.router import router
from app.config import get_settings
from app.core.errors import AppError
from app.core.ids import new_id
from app.core.logging import configure_logging, get_logger
from app.storage import database

logger = get_logger("airlock")


class _SecurityHeadersMiddleware:
    """Pure-ASGI middleware: MIME-sniffing guard on every response.

    No CSP here by design: `/api/docs` serves Swagger UI (HTML+JS),
    which a global `default-src 'none'` would break. The API itself is
    JSON-only, React auto-escapes, and artifact bytes already carry
    `nosniff` at the endpoint; this closes the remaining responses.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        async def guarded_send(message):
            if message.get("type") == "http.response.start":
                headers = list(message.get("headers", []))
                names = {name.lower() for name, _ in headers}
                if b"x-content-type-options" not in names:
                    headers.append((b"x-content-type-options", b"nosniff"))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send=guarded_send)


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    # Fail fast (before serving) when migrations are pending, so a stale
    # database surfaces the repair command instead of a runtime
    # `no such table` crash on the first query (e.g. login rate limits).
    database.require_schema_current(get_settings())
    yield
    from app.providers.http import POOL
    POOL.close_all()


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    app = FastAPI(title="Airlock API", version="0.1.0",
                  docs_url="/api/docs", openapi_url="/api/openapi.json",
                  lifespan=_lifespan)

    @app.exception_handler(AppError)
    async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(status_code=exc.status, content={
            "error": {"code": exc.code, "message": exc.message,
                      "request_id": new_id("req"), "details": exc.details}})

    @app.exception_handler(RequestValidationError)
    async def validation_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(status_code=422, content={
            "error": {"code": "E_SCHEMA",
                      "message": "Request validation failed",
                      "request_id": new_id("req"),
                      "details": [{"code": ".".join(str(p) for p in err["loc"]),
                                   "message": err["msg"]}
                                  for err in exc.errors()]}})

    @app.exception_handler(StarletteHTTPException)
    async def http_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = "E_SCHEMA" if exc.status_code in (404, 422) else "E_INTERNAL"
        if exc.status_code == 401:
            code = "E_AUTH"
        return JSONResponse(status_code=exc.status_code, content={
            "error": {"code": code, "message": str(exc.detail),
                      "request_id": new_id("req"), "details": []}})

    @app.exception_handler(Exception)
    async def unhandled_handler(_: Request, exc: Exception) -> JSONResponse:
        logger.error("unhandled error: %r", exc)
        return JSONResponse(status_code=500, content={
            "error": {"code": "E_INTERNAL",
                      "message": "Internal server error",
                      "request_id": new_id("req"), "details": []}})

    app.include_router(router)
    app.add_middleware(_SecurityHeadersMiddleware)
    return app


app = create_app()
