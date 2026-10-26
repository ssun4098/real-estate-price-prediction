"""모든 요청에 공통으로 적용되는 HTTP 규칙.

1. 응답       ok(), html(), raw()  — 보내기 직전에 인증키·DB 비밀번호가 섞였는지 검사
2. 오류       error_response()     — 어떤 예외든 {"error": {"code", "message"}} 한 가지 모양으로
3. 요청 본문  json_body()          — JSON만, 64MB 이하, NaN 거부
4. 접속 검사  check_host()         — 허용된 주소(127.0.0.1:포트 등)에서 온 요청만
"""
from __future__ import annotations

import json
import urllib.parse
from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse, Response

from server.domain.public_api import ApiError  # 계산 엔진이 쓰는 것과 같은 예외: ApiError(code, message, status)

MAX_JSON = 64 * 1024 * 1024

# ---------------------------------------------------------------------------
# 비밀값(인증키·DB 비밀번호) 유출 차단
# ---------------------------------------------------------------------------
_SECRETS: tuple[str, ...] = ()


def set_secrets(secrets) -> None:
    global _SECRETS
    _SECRETS = tuple(s for s in secrets if s)


def _forms(secret: str) -> tuple[str, str]:
    return secret, urllib.parse.quote(secret, safe="")


def contains_secret(text: str | bytes) -> bool:
    data = text.encode("utf-8") if isinstance(text, str) else text
    return any(form.encode("utf-8") in data for s in _SECRETS for form in _forms(s))


def reject_secrets(document) -> str:
    """저장 전에 호출. 직렬화한 문자열을 돌려주고, 64MB 초과·인증키 포함이면 거부한다."""
    serialized = json.dumps(document, ensure_ascii=False, allow_nan=False)
    if len(serialized.encode("utf-8")) > MAX_JSON:
        raise ValueError("결과 파일이 64MB를 초과했습니다.")
    if contains_secret(serialized):
        raise ValueError("인증키를 포함한 자료는 저장할 수 없습니다.")
    return serialized


def redact(message: str) -> str:
    for secret in _SECRETS:
        for form in _forms(secret):
            message = message.replace(form, "[비공개]")
    return message


# ---------------------------------------------------------------------------
# 1. 응답
# ---------------------------------------------------------------------------
class SafeJSONResponse(JSONResponse):
    def render(self, content: Any) -> bytes:
        body = json.dumps(content, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
        return _checked(body)


class SafeBytesResponse(Response):
    def render(self, content: Any) -> bytes:
        return _checked(content if isinstance(content, bytes) else str(content).encode("utf-8"))


def _checked(body: bytes) -> bytes:
    if contains_secret(body):
        raise ValueError("응답에 인증정보가 포함되어 전송을 중단했습니다.")
    return body


def ok(data) -> Response:
    """JSON 응답. 핸들러는 dict 대신 이걸 돌려준다 (FastAPI가 최대 64MB 문서를 한 번 더 변환하지 않도록)."""
    return SafeJSONResponse(data)


def html(text: str) -> Response:
    return SafeBytesResponse(text.encode("utf-8"), media_type="text/html; charset=utf-8")


def raw(data: bytes, media_type: str) -> Response:
    return SafeBytesResponse(data, media_type=media_type)


SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Resource-Policy": "same-origin",
    "X-Frame-Options": "DENY",
}


def add_security_headers(response: Response) -> Response:
    response.headers.setdefault("Cache-Control", "no-store")
    response.headers.update(SECURITY_HEADERS)
    return response


# ---------------------------------------------------------------------------
# 2. 오류 → 표준 응답
# ---------------------------------------------------------------------------
def error_response(exc: BaseException) -> Response:
    """예외 종류별 상태코드. 내부 정보(스택·키)는 절대 내보내지 않는다."""
    if isinstance(exc, ApiError):
        status, code, message = exc.status, exc.code, exc.message
    elif isinstance(exc, RequestValidationError):
        status, code, message = 400, "INVALID_INPUT", "요청 형식이 올바르지 않습니다."
    elif isinstance(exc, HTTPException):
        status = exc.status_code
        code, message = {
            404: ("NOT_FOUND", "요청한 경로를 찾을 수 없습니다."),
            405: ("METHOD_NOT_ALLOWED", "허용되지 않는 요청 방식입니다."),
        }.get(status, ("HTTP_ERROR", "요청을 처리할 수 없습니다."))
    elif isinstance(exc, (ValueError, KeyError, TypeError)):
        status, code, message = 400, "INVALID_INPUT", str(exc)
    else:
        status, code = 500, "INTERNAL_ERROR"
        message = "처리 중 오류가 발생했습니다. 입력·파일 권한을 확인하거나 다시 실행하세요."

    error = {"code": code, "message": redact(message)}
    headers = None
    if status == 429:  # 동시 조회 초과: 1초 뒤 다시 시도하라고 알려 준다
        error.update(retryable=True, retryAfterSeconds=1)
        headers = {"Retry-After": "1"}
    return add_security_headers(JSONResponse({"error": error}, status_code=status, headers=headers))


# ---------------------------------------------------------------------------
# 3. 요청 본문 (Depends(json_body) 로 사용)
# ---------------------------------------------------------------------------
async def json_body(request: Request) -> Any:
    if request.headers.get("content-type", "").split(";")[0].strip() != "application/json":
        raise ApiError("CONTENT_TYPE", "JSON 형식만 사용할 수 있습니다.", 415)
    try:
        declared = int(request.headers.get("content-length", "0"))
    except ValueError:
        raise ValueError("올바른 요청 크기가 필요합니다.") from None
    if declared <= 0 or declared > MAX_JSON:
        raise ApiError("BODY_LIMIT", "요청은 64MB 이하의 JSON이어야 합니다.", 413)

    raw_body = bytearray()
    async for chunk in request.stream():
        raw_body.extend(chunk)
        if len(raw_body) > MAX_JSON:
            raise ApiError("BODY_LIMIT", "요청은 64MB 이하의 JSON이어야 합니다.", 413)

    def no_nan(_):
        raise ValueError("유한한 숫자가 필요합니다.")

    def parse():
        try:
            return json.loads(bytes(raw_body).decode("utf-8"), parse_constant=no_nan)
        except (UnicodeError, json.JSONDecodeError):
            raise ValueError("올바른 JSON이 필요합니다.") from None

    return await run_in_threadpool(parse)  # 큰 JSON 해석이 다른 요청을 막지 않도록


# ---------------------------------------------------------------------------
# 4. 접속 주소 검사 (다른 사이트에서 몰래 보낸 요청 차단)
# ---------------------------------------------------------------------------
def check_host(request: Request, allowed_hosts: frozenset[str]) -> None:
    host = request.headers.get("host", "").lower()
    any_host = "*" in allowed_hosts          # ALLOWED_HOSTS=* : 어느 주소로 접속하든 허용 (서버 IP·도메인을 적기 싫을 때)
    if not any_host and host not in allowed_hosts:
        raise ApiError("INVALID_HOST", "허용된 실행 주소로 접속하세요.", 403)
    origin = request.headers.get("origin")
    cross_site = request.headers.get("sec-fetch-site") == "cross-site"
    # 서버(80·443)는 http·https 로, 내 PC(127.0.0.1)는 http 로 접속하므로 두 방식 모두 허용한다.
    # 주소를 제한하지 않을 때는 '지금 접속한 주소와 같은 주소에서 온 요청'만 통과시킨다.
    hosts = {host} if any_host else allowed_hosts
    allowed_origins = {scheme + h for h in hosts for scheme in ("http://", "https://")}
    if cross_site or (origin is not None and origin not in allowed_origins):
        raise ApiError("ORIGIN_REJECTED", "다른 사이트에서 분석 서버에 접근할 수 없습니다.", 403)
