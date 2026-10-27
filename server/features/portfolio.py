"""샘플 선반: '보관'을 눌러 고정해 둔 분석. 한 번 저장하면 바뀌지 않는다.

    GET  /api/portfolio-samples          목록
    GET  /api/portfolio-samples/{id}     하나
    POST /api/portfolio-samples          보관 (서버에서 다시 계산해서 저장)
    GET  /api/portfolio-default          화면을 열 때 보여줄 기본 샘플 id
    POST /api/portfolio-default          기본 샘플 지정

규칙
  - 저장할 때만 엔진으로 다시 계산한다. 읽을 때는 저장 당시 결과를 그대로 보여준다
    (엔진이 바뀌어도 과거 보관본이 달라지지 않도록. persistencePolicy=portfolio_frozen_v1).
  - data/samples/ 폴더의 샘플은 읽기 전용 기본 제공본이다. DB에 같은 id가 있으면 DB 것이 우선.
  - 기본 샘플로 지정한 id가 잘못되면 다른 샘플로 몰래 바꾸지 않고 '기본 없음'으로 둔다.
  - 저장본은 바뀌지 않으므로(지우는 기능도 없음) 전체 목록을 한 번 읽어 기억해 두고,
    저장본 id 목록이 바뀌었을 때만 다시 읽는다. 예시 하나가 수 MB라 요청마다 읽으면 메모리가 크게 늘어난다.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import re
import threading
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select

from server.db import PortfolioSampleRow, SettingRow, db_errors
from server.web import ApiError, json_body, ok, reject_secrets
from server.domain.analysis.common import _safe_tree
from server.domain.analysis import validate_snapshot
from server.domain.persistence import PORTFOLIO_POLICY, portfolio_capture_tree

router = APIRouter()

DEFAULT_KEY = "portfolio_default_id"  # app_settings 테이블의 키


def _portfolio(request: Request) -> "PortfolioService":
    return request.app.state.portfolio


# ---------------------------------------------------------------------------
# 라우터
# ---------------------------------------------------------------------------
@router.get("/api/portfolio-samples")
def list_samples(request: Request):
    portfolio = _portfolio(request)
    return ok({"items": portfolio.list(), "defaultId": portfolio.default_id()})


@router.get("/api/portfolio-samples/{ident}")
def read_sample(request: Request, ident: str):
    return ok(_portfolio(request).read(ident))


@router.post("/api/portfolio-samples")
def save_sample(request: Request, body: dict = Depends(json_body)):
    return ok(_portfolio(request).save(body))


@router.get("/api/portfolio-default")
def read_default(request: Request):
    return ok({"id": _portfolio(request).default_id()})


@router.post("/api/portfolio-default")
def set_default(request: Request, body: dict = Depends(json_body)):
    return ok(_portfolio(request).set_default(body.get("id")))


# ---------------------------------------------------------------------------
# 규칙
# ---------------------------------------------------------------------------
def load_bundled_samples(samples_dir: Path) -> tuple[list[dict], str | None]:
    """data/samples/pf-sample-*.json 과 data/samples/default.json(기본 샘플 id)."""
    entries = [json.loads(p.read_text("utf-8")) for p in sorted(samples_dir.glob("pf-sample-*.json"))]
    default_file = samples_dir / "default.json"
    default_id = json.loads(default_file.read_text("utf-8")).get("id") if default_file.is_file() else None
    return entries, default_id


class PortfolioService:
    def __init__(self, sessions, bundled_entries=(), bundled_default_id=None, land_model=None):
        self.sessions = sessions
        self.land_model = land_model  # 새 예시를 저장할 때 화면과 같은 토지매입대금(모델 예측)으로 계산하기 위함
        self.bundled: dict[str, dict] = {}
        for item in bundled_entries:
            clean = self._clean(item)
            self._check_item(clean, clean.get("id"))
            self.bundled[clean["id"]] = clean
        self.bundled_default_id = bundled_default_id if bundled_default_id in self.bundled else None
        self._entries_key = None    # 기억해 둔 목록이 어떤 저장본 id 목록으로 만든 것인지
        self._entries: list[dict] = []
        self._lock = threading.Lock()

    # --- 저장 -------------------------------------------------------------
    def save(self, body) -> dict:
        if not isinstance(body, dict) or not isinstance(body.get("snapshot"), dict):
            raise ValueError("저장할 분석 결과가 필요합니다.")
        clean = self._clean(body)
        candidate = clean["snapshot"]
        results = candidate.get("results")
        validation = results.get("validation") if isinstance(results, dict) else None
        if isinstance(validation, dict) and validation.get("mode") == "browser-preview":
            # 브라우저 계산값은 믿지 않는다: /api/analyze 와 같은 partial 모드로 다시 계산.
            validation["mode"] = "partial"
        snapshot = validate_snapshot(candidate, self.land_model() if self.land_model else None)

        name = str(clean.get("name") or snapshot.get("name") or "저장한 분석").strip()
        if not name or len(name) > 120:
            raise ValueError("분석 이름은 1~120자로 입력하세요.")
        item = self._clean({
            "id": self._new_id(),
            "name": name,
            "capturedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
            "readOnly": True,
            "persistencePolicy": PORTFOLIO_POLICY,
            "snapshot": snapshot,
            "displayState": _display_state(clean.get("displayState") or {}),
        })
        with db_errors(), self.sessions.begin() as session:
            session.add(PortfolioSampleRow(id=item["id"], captured_at=item["capturedAt"],
                                           body=json.dumps(item, ensure_ascii=False, allow_nan=False)))
        return {**item, "fileName": item["id"], "storage": "mysql"}

    # --- 읽기 -------------------------------------------------------------
    def read(self, ident) -> dict:
        _check_id(ident)
        with db_errors(), self.sessions() as session:
            row = session.get(PortfolioSampleRow, ident)
            body = row.body if row else None
        if body is not None:
            return self._check_item(self._clean(json.loads(body)), ident)
        if ident in self.bundled:
            return self._clean(self.bundled[ident])
        raise ApiError("NOT_FOUND", "저장한 분석을 찾을 수 없습니다.", 404)

    def version(self) -> tuple:
        """저장본 id 목록 + 기본 샘플 설정. 이 값이 같으면 목록·화면 내용도 같다 (본문은 읽지 않아 가볍다)."""
        with db_errors(), self.sessions() as session:
            rows = tuple(sorted(session.execute(select(PortfolioSampleRow.id, PortfolioSampleRow.captured_at)).tuples()))
            setting = session.get(SettingRow, DEFAULT_KEY)
            default = setting.value if setting else None
        return rows, default

    def entries(self) -> list[dict]:
        """기본 제공 + DB 샘플 전체 (최신순). 형식이 깨진 항목은 건너뛴다.

        저장본 id 목록이 그대로면 기억해 둔 목록을 그대로 돌려준다 (돌려받은 항목은 고치지 말 것).
        """
        rows, _ = self.version()
        with self._lock:  # 동시에 여러 요청이 와도 한 번만 읽는다
            if self._entries_key != rows:
                self._entries, self._entries_key = self._read_entries(), rows
            return self._entries

    def _read_entries(self) -> list[dict]:
        items = dict(self.bundled)
        with db_errors(), self.sessions() as session:
            bodies = list(session.scalars(select(PortfolioSampleRow.body)))
        for body in bodies:
            try:
                raw = json.loads(body)
                item = self._check_item(self._clean(raw), raw.get("id"))
                items[item["id"]] = item
            except (ValueError, KeyError, TypeError):
                continue
        return sorted(items.values(), key=lambda item: item["capturedAt"], reverse=True)

    def list(self) -> list[dict]:
        """목록 화면용 요약."""
        default_id = self.default_id()
        result = []
        for item in self.entries():
            try:
                snapshot = item["snapshot"]
                result.append({
                    "id": item["id"], "name": item["name"], "capturedAt": item["capturedAt"],
                    "readOnly": True, "persistencePolicy": PORTFOLIO_POLICY,
                    "isDefault": item["id"] == default_id,
                    "scenario": snapshot.get("scenario"),
                    "parcelCount": len(snapshot["inputs"].get("parcels", [])),
                    "areaM2": snapshot["results"].get("development", {}).get("landAreaM2"),
                })
            except (KeyError, TypeError):
                continue
        return result

    # --- 기본 샘플 ----------------------------------------------------------
    def default_id(self):
        with db_errors(), self.sessions() as session:
            row = session.get(SettingRow, DEFAULT_KEY)
            ident = row.value if row else None
        if ident is None:
            return self.bundled_default_id
        # 형식이 맞는 샘플(entries 에 들어간 것)만 인정. 잘못된 지정은 다른 샘플로 바꾸지 않는다.
        return ident if any(item["id"] == ident for item in self.entries()) else None

    def set_default(self, ident) -> dict:
        self.read(ident)  # 존재·형식 확인
        with db_errors(), self.sessions.begin() as session:
            session.merge(SettingRow(key=DEFAULT_KEY, value=ident))
        return {"id": ident}

    # --- 검사 도우미 ---------------------------------------------------------
    @staticmethod
    def _clean(value):
        """전송용·비공개 필드만 빼고(행·조회상태·좌표·결과는 유지) 크기·인증키를 검사한다."""
        value = _safe_tree(portfolio_capture_tree(value))
        reject_secrets(value)
        return value

    @staticmethod
    def _check_item(item, ident):
        _check_id(ident)
        snapshot = item.get("snapshot") if isinstance(item, dict) else None
        if (not isinstance(item, dict) or item.get("id") != ident or
                item.get("persistencePolicy") != PORTFOLIO_POLICY or item.get("readOnly") is not True or
                not isinstance(snapshot, dict) or
                not isinstance(snapshot.get("inputs"), dict) or not isinstance(snapshot.get("results"), dict)):
            raise ValueError("저장한 분석의 형식이 올바르지 않습니다.")
        try:
            dt.datetime.fromisoformat(str(item.get("capturedAt")).replace("Z", "+00:00"))
        except ValueError:
            raise ValueError("저장 시각이 올바르지 않습니다.") from None
        return item  # 다시 계산하지 않는다 (고정 보관본)

    def _new_id(self) -> str:
        while True:
            ident = "pf-sample-" + uuid.uuid4().hex
            with db_errors(), self.sessions() as session:
                if session.get(PortfolioSampleRow, ident) is None:
                    return ident


def _check_id(ident) -> None:
    if not re.fullmatch(r"pf-sample-[a-f0-9]{32}", str(ident)):
        raise ValueError("저장한 분석 식별자가 올바르지 않습니다.")


def _display_state(display) -> dict:
    """같이 보관할 화면 상태(주소·탭·지도 위치 등)만 골라서 검사한다."""
    if not isinstance(display, dict):
        raise ValueError("화면 자료는 객체여야 합니다.")
    display = {key: display[key] for key in ("survey", "address", "viewState", "mapView") if key in display}
    if "address" in display and not isinstance(display["address"], str):
        raise ValueError("화면 주소는 문자열이어야 합니다.")
    if "survey" in display and display["survey"] is not None and not isinstance(display["survey"], dict):
        raise ValueError("입지 조사 자료는 객체여야 합니다.")
    if "viewState" in display:
        view = display["viewState"]
        if (not isinstance(view, dict) or view.get("main") not in ("finance", "survey") or
                view.get("tab") not in ("parcels", "regulation", "location", "development")):
            raise ValueError("저장할 화면 탭이 올바르지 않습니다.")
        display["viewState"] = {key: view[key] for key in ("main", "tab")}
    if "mapView" in display:
        view = display["mapView"]
        limits = {"lon": (-180, 180), "lat": (-85.05112878, 85.05112878), "z": (0, 22)}
        if not isinstance(view, dict) or any(
                not isinstance(view.get(key), (int, float)) or isinstance(view.get(key), bool) or
                not math.isfinite(view[key]) or not low <= view[key] <= high
                for key, (low, high) in limits.items()):
            raise ValueError("저장할 지도 위치가 올바르지 않습니다.")
        display["mapView"] = {key: view[key] for key in limits}
    return display
