"""사업성 계산과 분석 저장본.

    POST /api/analyze                    입력값 → 계산 결과 (저장하지 않음)
    POST /api/save, /api/export-json     분석 저장 (둘 다 같은 저장. 예전엔 export-json이 V6.html 파일도 썼음)
    GET  /api/snapshots                  저장 목록 (최신순)
    GET  /api/snapshots/{id}             저장본 하나
    GET  /pf-study-v6-snapshots/{id}.json   예전 주소 (화면 호환용)

핵심 규칙: 브라우저가 보낸 계산 결과는 믿지 않는다. 저장할 때도, 읽어 줄 때도 엔진으로 다시 계산한다.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select

from server.db import SnapshotRow, db_errors
from server.web import ApiError, json_body, ok, reject_secrets
from server.domain.analysis import analyze, validate_snapshot
from server.domain.persistence import export_snapshot

router = APIRouter()

EXPORT_NOTICE = "Geocoder 실시간 위치·반경 분양사례 및 의존 수지는 저장에서 제외했습니다."


def _snapshots(request: Request) -> "SnapshotService":
    return request.app.state.snapshots


# ---------------------------------------------------------------------------
# 라우터
# ---------------------------------------------------------------------------
@router.post("/api/analyze")
def analyze_inputs(request: Request, body: dict = Depends(json_body)):
    # 학습 모델이 켜져 있으면 토지매입대금을 모델 예측으로 계산한다.
    return ok(analyze(body, partial=True, land_model=request.app.state.model.estimator()))


@router.post("/api/save")
@router.post("/api/export-json")
def save_snapshot(request: Request, body: dict = Depends(json_body)):
    return ok(_snapshots(request).save(body))


@router.get("/api/snapshots")
def list_snapshots(request: Request):
    return ok({"items": _snapshots(request).list()})


@router.get("/api/snapshots/{ident}")
def read_snapshot(request: Request, ident: str):
    return ok(_snapshots(request).read(ident))


@router.get("/pf-study-v6-snapshots/{ident}.json", include_in_schema=False)
def read_snapshot_old_path(request: Request, ident: str):
    return ok(_snapshots(request).read(ident))


# ---------------------------------------------------------------------------
# 규칙 + DB
# ---------------------------------------------------------------------------
class SnapshotService:
    def __init__(self, sessions, land_model=None):
        self.sessions = sessions
        self.land_model = land_model  # 호출하면 '필지 → 모델 단가' 함수(또는 None)를 주는 함수 (ModelHolder.estimator)

    def recompute(self, snapshot) -> dict:
        """인증키가 섞였는지 확인하고, 엔진으로 다시 계산한 뒤, 저장 규칙에 맞게 정리한다."""
        reject_secrets(snapshot)
        land_model = self.land_model() if self.land_model else None
        return export_snapshot(validate_snapshot(snapshot, land_model), land_model)

    def save(self, snapshot) -> dict:
        snapshot = self.recompute(snapshot)
        ident = str(snapshot.get("id", ""))
        if not re.fullmatch(r"pf-[A-Za-z0-9_-]{1,100}", ident):
            ident = "pf-" + uuid.uuid4().hex
        if self._exists(ident):
            # 같은 id가 이미 있으면 덮어쓰지 않고 새 id로 따로 저장한다.
            ident = "pf-" + uuid.uuid4().hex
            snapshot["createdAt"] = dt.datetime.now(dt.timezone.utc).isoformat()
        snapshot["id"] = ident
        with db_errors(), self.sessions.begin() as session:
            session.add(SnapshotRow(
                id=ident, name=snapshot.get("name"), scenario=snapshot.get("scenario"),
                created_at=snapshot.get("createdAt"),
                body=json.dumps(snapshot, ensure_ascii=False, allow_nan=False)))
        return {"id": ident, "fileName": ident, "storage": "mysql", "htmlFileName": None,
                "snapshot": snapshot, "exportNotice": EXPORT_NOTICE}

    def read(self, ident: str) -> dict:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", ident):
            raise ValueError("결과 식별자가 올바르지 않습니다.")
        with db_errors(), self.sessions() as session:
            row = session.get(SnapshotRow, ident)
            body = row.body if row else None
        if body is None:
            raise ApiError("NOT_FOUND", "저장된 분석을 찾을 수 없습니다.", 404)
        return self.recompute(json.loads(body))

    def list(self) -> list[dict]:
        """최신순. 큰 본문(body)은 읽지 않고 작은 열만 읽는다."""
        with db_errors(), self.sessions() as session:
            rows = session.execute(
                select(SnapshotRow.id, SnapshotRow.name, SnapshotRow.scenario, SnapshotRow.created_at)
                .order_by(SnapshotRow.created_at.desc())).all()
        return [{"id": r.id, "name": r.name, "scenario": r.scenario, "createdAt": r.created_at} for r in rows]

    def _exists(self, ident: str) -> bool:
        with db_errors(), self.sessions() as session:
            return session.get(SnapshotRow, ident) is not None
