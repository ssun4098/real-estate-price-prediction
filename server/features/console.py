"""새 분석 콘솔 화면 (/console). 기존 화면(/)은 그대로 두고 별도 경로로 제공한다.

화면 파일은 frontend/console/ 에 있고(빌드 결과 build/, 지도 라이브러리 vendor/),
조회·계산은 기존 API(/api/parcel, /api/comparables, /api/analyze ...)를 그대로 쓴다.
이 파일에서 새로 만드는 API는 예측 차트용 두 가지뿐이다.

    GET /api/console/land-history?keys=41271|전|녹지지역,41271|대|일반주거지역
        토지 그룹(시군구|지목|용도지역)별 월간 거래단가 중앙값·거래 건수 (모델 입력 자료 group_history.csv.gz)
    GET /api/console/region-indicators?sgg=41271
        그 시군구의 월간 지가변동률과 COFIX (모델 입력 자료 macro_region_month.csv, cofix_release.csv)
"""
from __future__ import annotations

import csv
import gzip
import re
import threading
from collections import OrderedDict
from pathlib import Path

from fastapi import APIRouter, Request
from starlette.responses import Response

from server.web import ApiError, ok

router = APIRouter()

CONSOLE_DIR = Path(__file__).resolve().parents[2] / "frontend" / "console"
# 화면이 불러갈 수 있는 파일 종류. 이 밖의 파일(소스, 빌드 스크립트)은 내보내지 않는다.
ASSET_TYPES = {".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
               ".png": "image/png", ".svg": "image/svg+xml"}
ASSET_DIRS = ("build", "vendor")
GROUP_KEY = re.compile(r"^\d{5}\|[^|,]{1,12}\|[^|,]{1,20}$")
MAX_KEYS = 12


# ---------------------------------------------------------------------------
# 화면 파일
# ---------------------------------------------------------------------------
@router.get("/console", include_in_schema=False)
@router.get("/console/", include_in_schema=False)
def console_page():
    page = CONSOLE_DIR / "index.html"
    if not page.is_file():
        raise ApiError("CONSOLE_MISSING", "콘솔 화면 파일이 없습니다. frontend/console 폴더를 확인하세요.", 404)
    return Response(page.read_bytes(), media_type="text/html; charset=utf-8", headers={"Cache-Control": "no-cache"})


@router.get("/console/{folder}/{path:path}", include_in_schema=False)
def console_asset(folder: str, path: str):
    """build/ 와 vendor/ 안의 정해진 종류 파일만 돌려준다 (폴더 밖으로 나가는 경로는 거절)."""
    if folder not in ASSET_DIRS:
        raise ApiError("NOT_FOUND", "요청한 경로를 찾을 수 없습니다.", 404)
    base = (CONSOLE_DIR / folder).resolve()
    target = (base / path).resolve()
    if base not in target.parents or target.suffix not in ASSET_TYPES or not target.is_file():
        raise ApiError("NOT_FOUND", "요청한 경로를 찾을 수 없습니다.", 404)
    return Response(target.read_bytes(), media_type=ASSET_TYPES[target.suffix], headers={"Cache-Control": "no-cache"})


# ---------------------------------------------------------------------------
# 예측 차트용 자료
# ---------------------------------------------------------------------------
class ModelInputs:
    """모델 입력 자료를 시군구 단위로 읽어 기억해 둔다 (파일 전체 450만 행이 아니라 필요한 시군구만)."""

    def __init__(self, folder: Path, max_regions: int = 30):
        self.folder = folder
        self._lock = threading.Lock()
        self._history: OrderedDict[str, dict] = OrderedDict()
        self._max = max_regions
        self._macro = None
        self._cofix = None
        self._regions = None

    def history(self, sgg: str) -> dict:
        """{그룹 키: [[월, 단가, 건수], ...]} — 월 순서."""
        with self._lock:
            if sgg in self._history:
                self._history.move_to_end(sgg)
                return self._history[sgg]
        found: dict[str, list] = {}
        path = self.folder / "group_history.csv.gz"
        if not path.is_file():
            raise ApiError("MODEL_DATA_MISSING", "모델 입력 자료(group_history.csv.gz)가 없습니다.", 409)
        with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
            rows = csv.reader(handle)
            next(rows, None)
            prefix = sgg + "|"
            for key, month, unit, _area, count in rows:
                if key.startswith(prefix):
                    found.setdefault(key, []).append([month, round(float(unit)), int(float(count))])
        for points in found.values():
            points.sort()
        with self._lock:
            self._history[sgg] = found
            while len(self._history) > self._max:
                self._history.popitem(last=False)
        return found

    def indicators(self, sgg: str) -> dict:
        with self._lock:
            if self._regions is None:
                self._regions = {r["lawd_cd"]: r for r in _read_csv(self.folder / "region_map.csv")}
                self._macro = {}
                for row in _read_csv(self.folder / "macro_region_month.csv"):
                    if row.get("지가변동률") not in (None, ""):
                        self._macro.setdefault(row["지역키"], []).append([row["월"], float(row["지가변동률"])])
                self._cofix = [[r["월"], float(r["신규취급액기준_COFIX"])] for r in _read_csv(self.folder / "cofix_release.csv")
                               if r.get("신규취급액기준_COFIX") not in (None, "")]
            region = self._regions.get(sgg)
            key = region["입력지역키"] if region else None
            return {"sgg": sgg, "regionKey": key,
                    "regionName": " ".join(filter(None, [region.get("sido_nm"), region.get("sigungu_nm")])) if region else None,
                    "landChange": sorted(self._macro.get(key, [])) if key else [],
                    "cofix": sorted(self._cofix)}


def _read_csv(path: Path) -> list[dict]:
    if not path.is_file():
        raise ApiError("MODEL_DATA_MISSING", f"모델 입력 자료({path.name})가 없습니다.", 409)
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _inputs(request: Request) -> ModelInputs:
    state = request.app.state
    holder = getattr(state, "console_inputs", None)
    if holder is None:
        holder = state.console_inputs = ModelInputs(Path(state.model.model_dir) / "inputs")
    return holder


@router.get("/api/console/land-history")
def land_history(request: Request, keys: str = "", start: str = "2019-01"):
    wanted = [k.strip() for k in keys.split(",") if k.strip()]
    if not wanted or len(wanted) > MAX_KEYS or not all(GROUP_KEY.match(k) for k in wanted):
        raise ValueError(f"토지 그룹 키는 '시군구코드|지목|용도지역' 형식으로 1~{MAX_KEYS}개를 쉼표로 구분해 주세요.")
    if not re.fullmatch(r"\d{4}-\d{2}", start):
        raise ValueError("시작 월은 YYYY-MM 형식이어야 합니다.")
    series = []
    for key in dict.fromkeys(wanted):
        points = _inputs(request).history(key[:5]).get(key, [])
        series.append({"key": key, "points": [p for p in points if p[0] >= start]})
    return ok({"series": series, "source": "모델 입력 자료 · 토지 그룹 월간 거래단가 중앙값"})


@router.get("/api/console/region-indicators")
def region_indicators(request: Request, sgg: str = ""):
    if not re.fullmatch(r"\d{5}", sgg):
        raise ValueError("시군구 코드는 숫자 5자리여야 합니다.")
    return ok(_inputs(request).indicators(sgg))
