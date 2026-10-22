"""상태 확인."""
from __future__ import annotations

from fastapi import APIRouter, Request

from server import db
from server.web import ok

router = APIRouter()


@router.get("/healthz", include_in_schema=False)
def healthz(request: Request):
    """Docker 헬스체크용: 서버가 살아 있고 MySQL에 닿는지만. 자세한 내용은 내보내지 않는다."""
    db.ping(request.app.state.sessions)
    return ok({"status": "ok"})


@router.get("/api/status")
def status(request: Request):
    """화면 상단의 'API 준비 상태' 표시용."""
    info = request.app.state.public_data.status()
    info["model"] = request.app.state.model.info()
    return ok(info)
