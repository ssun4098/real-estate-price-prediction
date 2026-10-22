"""ASGI entry point: ``uvicorn app.main:app``."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response

from app.api.routers import analysis, model, pages, portfolio, public_data, snapshots, system
from app.container import build_container
from app.core.guard import check_request
from app.core.http import SafeJSONResponse, apply_headers, error_response
from app.core.settings import Settings

# Request URLs carry addresses and (upstream) keys: keep access logs off, as the legacy server did.
logging.getLogger("uvicorn.access").disabled = True


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.container = build_container(settings)
        try:
            yield
        finally:
            app.state.container.close()

    app = FastAPI(
        title="개발사업성 분석 V6",
        version="6.0.0",
        lifespan=lifespan,
        default_response_class=SafeJSONResponse,
        docs_url="/api/docs" if settings.enable_docs else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if settings.enable_docs else None,
    )

    @app.middleware("http")
    async def guard(request: Request, call_next) -> Response:
        try:
            check_request(request, settings.allowed_hosts)
            response = await call_next(request)
        except Exception as exc:  # noqa: BLE001
            return error_response(exc)
        return apply_headers(response)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, exc: StarletteHTTPException) -> Response:
        return error_response(exc)

    for module in (pages, system, public_data, analysis, snapshots, portfolio, model):
        app.include_router(module.router)
    return app

