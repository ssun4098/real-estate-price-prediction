"""Read-only lookups that call external public APIs (rate limited by PublicDataService)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from starlette.responses import Response

from app.api.deps import get_container
from app.container import Container
from app.core.http import SafeJSONResponse, SafeRoute

router = APIRouter(prefix="/api", route_class=SafeRoute)


@router.get("/parcels")
def parcels(bbox: str = "", c: Container = Depends(get_container)) -> Response:
    return SafeJSONResponse(c.public_data.parcels(bbox))


@router.get("/parcel")
def parcel(pnu: str = "", year: int | None = None, refresh: str = "", c: Container = Depends(get_container)) -> Response:
    return SafeJSONResponse(c.public_data.parcel(pnu, year, refresh == "1"))


@router.get("/boundary-allocation")
def boundary_allocation(pnu: str = "", year: int | None = None, refresh: str = "",
                        c: Container = Depends(get_container)) -> Response:
    return SafeJSONResponse(c.public_data.boundary_allocation(pnu, year, refresh == "1"))


@router.get("/site-survey")
def site_survey(request: Request, c: Container = Depends(get_container)) -> Response:
    # The survey takes a free-form set of options; the last value of a repeated key wins.
    return SafeJSONResponse(c.public_data.site_survey(dict(request.query_params)))


@router.get("/address")
def address(keyword: str = "", c: Container = Depends(get_container)) -> Response:
    return SafeJSONResponse(c.public_data.address(keyword))


@router.get("/regions")
def regions(q: str = "", parent: str = "", level: str = "all", current: str = "1", refresh: str = "",
            c: Container = Depends(get_container)) -> Response:
    return SafeJSONResponse(c.public_data.regions(q=q, parent=parent, level=level, current=current != "0",
                                                  refresh=refresh == "1"))


@router.get("/data-coverage")
def data_coverage(c: Container = Depends(get_container)) -> Response:
    return SafeJSONResponse(c.public_data.data_coverage())


@router.get("/land-cache")
def land_cache(sgg: str | None = None, c: Container = Depends(get_container)) -> Response:
    return SafeJSONResponse(c.public_data.land_cache(sgg))


@router.get("/comparables")
def comparables(
    sgg: str = "", dong: str = "", start: str = "", end: str = "", refresh: str = "", scope: str = "dong",
    lon: str | None = None, lat: str | None = None, radiusKm: str = "5",
    landStart: str | None = None, landEnd: str | None = None,
    revenueStart: str | None = None, revenueEnd: str | None = None, asOf: str | None = None,
    landScope: str = "dong", selectedPnus: str | None = None, legalDongCode: str | None = None,
    c: Container = Depends(get_container),
) -> Response:
    return SafeJSONResponse(c.public_data.comparables(
        sgg, dong, start, end, refresh == "1",
        scope=scope, lon=lon, lat=lat, radius_km=radiusKm,
        land_start=landStart, land_end=landEnd, revenue_start=revenueStart, revenue_end=revenueEnd,
        as_of=asOf, land_scope=landScope, period_mode="rolling60",
        selected_pnus=selectedPnus, legal_dong_code=legalDongCode))
