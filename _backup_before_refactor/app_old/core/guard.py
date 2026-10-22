"""Host/Origin guard (same policy as the legacy local server, hosts configurable)."""
from __future__ import annotations

from starlette.requests import Request

from app.core.errors import ApiError


def check_request(request: Request, allowed_hosts: frozenset[str]) -> None:
    if request.headers.get("host", "").lower() not in allowed_hosts:
        raise ApiError("INVALID_HOST", "허용된 실행 주소로 접속하세요.", 403)
    origin = request.headers.get("origin")
    if origin is not None and origin not in {"http://" + h for h in allowed_hosts}:
        raise ApiError("ORIGIN_REJECTED", "다른 사이트에서 분석 서버에 접근할 수 없습니다.", 403)
    if request.headers.get("sec-fetch-site") == "cross-site":
        raise ApiError("ORIGIN_REJECTED", "다른 사이트에서 분석 서버에 접근할 수 없습니다.", 403)
