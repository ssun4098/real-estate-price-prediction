"""HTTP plumbing shared by all routers: safe responses, route class, JSON body."""
from __future__ import annotations

import json
from typing import Any

from fastapi import Request
from fastapi.routing import APIRoute
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse, Response

from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.errors import MAX_JSON, ApiError, contains_secret, redact

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Resource-Policy": "same-origin",
    "X-Frame-Options": "DENY",
}


def apply_headers(response: Response, *, retry_after: int | None = None) -> Response:
    response.headers.setdefault("Cache-Control", "no-store")
    for key, value in SECURITY_HEADERS.items():
        response.headers[key] = value
    if retry_after is not None:
        response.headers["Retry-After"] = str(retry_after)
    return response


def _guard(body: bytes) -> bytes:
    # Same rule as the legacy server: a response containing a credential is never sent.
    if contains_secret(body):
        raise ValueError("응답에 인증정보가 포함되어 전송을 중단했습니다.")
    return body


class SafeJSONResponse(JSONResponse):
    def render(self, content: Any) -> bytes:
        body = json.dumps(content, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
        return _guard(body)


class SafeBytesResponse(Response):
    """Bytes/HTML payloads (page, map tiles) get the same credential check."""

    def render(self, content: Any) -> bytes:
        return _guard(content if isinstance(content, bytes) else str(content).encode("utf-8"))


def describe(exc: BaseException) -> tuple[int, dict]:
    """Map any exception to (status, payload). Never exposes tracebacks or keys."""
    if isinstance(exc, ApiError):
        status, code, message = exc.status, exc.code, exc.message
    elif isinstance(exc, RequestValidationError):
        status, code, message = 400, "INVALID_INPUT", "요청 형식이 올바르지 않습니다."
    elif isinstance(exc, StarletteHTTPException):
        status = exc.status_code
        code = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}.get(status, "HTTP_ERROR")
        message = {404: "요청한 경로를 찾을 수 없습니다.", 405: "허용되지 않는 요청 방식입니다."}.get(status, "요청을 처리할 수 없습니다.")
    elif isinstance(exc, (ValueError, KeyError, TypeError)):
        status, code, message = 400, "INVALID_INPUT", str(exc)
    else:
        status, code = 500, "INTERNAL_ERROR"
        message = "처리 중 오류가 발생했습니다. 입력·파일 권한을 확인하거나 다시 실행하세요."
    error = {"code": code, "message": redact(message)}
    if status == 429:
        error.update(retryable=True, retryAfterSeconds=1)
    return status, {"error": error}


def error_response(exc: BaseException) -> Response:
    status, payload = describe(exc)
    return apply_headers(JSONResponse(payload, status_code=status), retry_after=1 if status == 429 else None)


class SafeRoute(APIRoute):
    """Turns every exception raised by a handler into the standard error envelope."""

    def get_route_handler(self):
        original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            try:
                return await original(request)
            except Exception as exc:  # noqa: BLE001 - deliberately converted, never logged with details
                return error_response(exc)

        return handler


async def json_body(request: Request) -> dict:
    """Dependency: a strict JSON body of at most 64MB (same limits as the legacy server)."""
    if request.headers.get("content-type", "").split(";")[0].strip() != "application/json":
        raise ApiError("CONTENT_TYPE", "JSON 형식만 사용할 수 있습니다.", 415)
    try:
        declared = int(request.headers.get("content-length", "0"))
    except ValueError:
        raise ValueError("올바른 요청 크기가 필요합니다.") from None
    if declared <= 0 or declared > MAX_JSON:
        raise ApiError("BODY_LIMIT", "요청은 64MB 이하의 JSON이어야 합니다.", 413)
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > MAX_JSON:
            raise ApiError("BODY_LIMIT", "요청은 64MB 이하의 JSON이어야 합니다.", 413)

    def reject(_):
        raise ValueError("유한한 숫자가 필요합니다.")

    def parse() -> Any:
        try:
            return json.loads(bytes(raw).decode("utf-8"), parse_constant=reject)
        except (UnicodeError, json.JSONDecodeError):
            raise ValueError("올바른 JSON이 필요합니다.") from None

    return await run_in_threadpool(parse)
