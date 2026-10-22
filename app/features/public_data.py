"""공공 API 조회 (브이월드, 공공데이터포털, 도로명주소, KOSIS, SGIS).

실제 호출은 전부 backend/pf_api.py 의 Collector 가 한다. 여기서는
  - URL 쿼리값을 Collector 에 넘기고
  - 외부 API가 느리고 호출 한도가 있으므로 동시에 4건까지만 허용한다 (넘으면 429 BUSY).
"""
from __future__ import annotations

import datetime as dt
import threading
from contextlib import contextmanager

from fastapi import APIRouter, Path, Request

from app.web import ApiError, ok, raw
from pf_api import Collector
from pf_survey import enrich_parcel, site_survey

router = APIRouter(prefix="/api")


class PublicData:
    def __init__(self, collector: Collector, max_jobs: int = 4):
        self.collector = collector
        self._jobs = threading.BoundedSemaphore(max_jobs)

    @contextmanager
    def slot(self):
        """빈자리가 없으면 기다리지 않고 바로 거절한다 (요청이 무한히 쌓이지 않도록)."""
        if not self._jobs.acquire(blocking=False):
            raise ApiError("BUSY", "다른 자료를 조회 중입니다. 잠시 후 다시 시도하세요.", 429)
        try:
            yield self.collector
        finally:
            self._jobs.release()

    def status(self) -> dict:
        """/api/status 의 공공 API 부분."""
        keys = self.collector.keys
        info = self.collector.status()
        info["version"] = "6.0.0"
        info["exportPolicy"] = "v5-geocoder-requery"
        info["jsonSaveDirectory"] = "MySQL"
        api = info["apiStatus"]
        api.update({k: "준비" if keys.get(k) else "인증 미준비" for k in ("vworldGeocoder", "vworldSearch", "kosis")})
        api["sgis"] = "준비" if keys.get("sgisId") and keys.get("sgisSecret") else "서비스 ID·비밀값 확인 필요"
        return info


def _public(request: Request) -> PublicData:
    return request.app.state.public_data


def _year(year: int | None) -> int:
    return year or dt.date.today().year


# ---------------------------------------------------------------------------
# 라우터
# ---------------------------------------------------------------------------
@router.get("/tiles/{z}/{y}/{x}.jpeg")
def tile(request: Request, z: int = Path(ge=0, le=30), y: int = Path(ge=0), x: int = Path(ge=0)):
    """지도 배경 타일 (동시 조회 제한 없음)."""
    response = raw(_public(request).collector.tile(z, y, x), "image/jpeg")
    response.headers["Cache-Control"] = "private, max-age=300"
    return response


@router.get("/parcels")
def parcels(request: Request, bbox: str = ""):
    """지도 영역(bbox = 서,남,동,북) 안의 필지 경계."""
    with _public(request).slot() as collector:
        return ok(collector.parcels([float(v) for v in bbox.split(",")]))


@router.get("/parcel")
def parcel(request: Request, pnu: str = "", year: int | None = None, refresh: str = ""):
    """필지 하나의 상세 정보 (토지이용·공시지가 등)."""
    with _public(request).slot() as collector:
        found = collector.parcel(pnu, _year(year), refresh=refresh == "1")
        return ok(enrich_parcel(collector, found, _year(year)))


@router.get("/boundary-allocation")
def boundary_allocation(request: Request, pnu: str = "", year: int | None = None, refresh: str = ""):
    """필지가 여러 용도지역에 걸칠 때 면적 배분."""
    with _public(request).slot() as collector:
        return ok(collector.boundary_allocation(pnu, _year(year), refresh=refresh == "1"))


@router.get("/site-survey")
def survey(request: Request):
    """입지 조사. 옵션이 자유 형식이라 쿼리 전체를 넘긴다 (같은 키가 여러 번이면 마지막 값)."""
    with _public(request).slot() as collector:
        return ok(site_survey(collector, dict(request.query_params)))


@router.get("/address")
def address(request: Request, keyword: str = ""):
    with _public(request).slot() as collector:
        return ok(collector.address(keyword, geocode=True))


@router.get("/regions")
def regions(request: Request, q: str = "", parent: str = "", level: str = "all", current: str = "1",
            refresh: str = ""):
    """시도·시군구·읍면동 목록."""
    with _public(request).slot() as collector:
        return ok(collector.regions(q=q, parent=parent, level=level, current=current != "0",
                                    refresh=refresh == "1"))


@router.get("/data-coverage")
def data_coverage(request: Request):
    with _public(request).slot() as collector:
        return ok(collector.data_coverage())


@router.get("/land-cache")
def land_cache(request: Request, sgg: str | None = None):
    """MySQL에 쌓인 토지 실거래 캐시 현황."""
    with _public(request).slot() as collector:
        return ok(collector.land_storage(sgg))


@router.get("/comparables")
def comparables(
    request: Request,
    sgg: str = "", dong: str = "", start: str = "", end: str = "", refresh: str = "", scope: str = "dong",
    lon: str | None = None, lat: str | None = None, radiusKm: str = "5",
    landStart: str | None = None, landEnd: str | None = None,
    revenueStart: str | None = None, revenueEnd: str | None = None, asOf: str | None = None,
    landScope: str = "dong", selectedPnus: str | None = None, legalDongCode: str | None = None,
):
    """주변 실거래·분양 사례 (쿼리 이름은 화면이 쓰는 camelCase 그대로)."""
    with _public(request).slot() as collector:
        return ok(collector.comparables(
            sgg, dong, start, end, refresh == "1",
            scope=scope, lon=lon, lat=lat, radius_km=radiusKm,
            land_start=landStart, land_end=landEnd, revenue_start=revenueStart, revenue_end=revenueEnd,
            as_of=asOf, land_scope=landScope, period_mode="rolling60",
            selected_pnus=selectedPnus, legal_dong_code=legalDongCode))
