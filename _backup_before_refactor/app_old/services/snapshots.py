from __future__ import annotations

import datetime as dt
import json
import re
import urllib.parse
import uuid

from app.core.errors import MAX_JSON, ApiError
from app.repositories.snapshots import SnapshotRepository
from pf_engine import validate_snapshot
from pf_persistence import export_snapshot

EXPORT_NOTICE = "Geocoder 실시간 위치·반경 분양사례 및 의존 수지는 저장에서 제외했습니다."


class SnapshotService:
    def __init__(self, repository: SnapshotRepository, secrets=()):
        self.repository = repository
        self.secrets = tuple(s for s in secrets if s)

    def validate(self, snapshot) -> dict:
        serialized = json.dumps(snapshot, ensure_ascii=False, allow_nan=False)
        if len(serialized.encode("utf-8")) > MAX_JSON:
            raise ValueError("결과 파일이 64MB를 초과했습니다.")
        for secret in self.secrets:
            if secret in serialized or urllib.parse.quote(secret, safe="") in serialized:
                raise ValueError("인증키를 포함한 자료는 저장할 수 없습니다.")
        # Caller-computed results are never trusted: the engine recalculates them.
        return export_snapshot(validate_snapshot(snapshot))

    def save(self, snapshot) -> dict:
        snapshot = self.validate(snapshot)
        ident = str(snapshot.get("id", ""))
        if not re.fullmatch(r"pf-[A-Za-z0-9_-]{1,100}", ident):
            ident = "pf-" + uuid.uuid4().hex
        if self.repository.exists(ident):
            ident = "pf-" + uuid.uuid4().hex
            snapshot["createdAt"] = dt.datetime.now(dt.timezone.utc).isoformat()
        snapshot["id"] = ident
        self.repository.add(ident, snapshot)
        return {"id": ident, "fileName": ident, "storage": "mysql", "htmlFileName": None,
                "snapshot": snapshot, "exportNotice": EXPORT_NOTICE}

    def read(self, ident: str) -> dict:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", ident):
            raise ValueError("결과 식별자가 올바르지 않습니다.")
        stored = self.repository.get(ident)
        if stored is None:
            raise ApiError("NOT_FOUND", "저장된 분석을 찾을 수 없습니다.", 404)
        return self.validate(stored)

    def list(self) -> list[dict]:
        return self.repository.list_meta()
