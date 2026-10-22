from __future__ import annotations

from fastapi import APIRouter, Depends
from starlette.responses import Response

from app.api.deps import get_container
from app.container import Container
from app.core.http import SafeBytesResponse, SafeRoute

router = APIRouter(route_class=SafeRoute, include_in_schema=False)


@router.get("/")
@router.get("/index.html")
@router.get("/V6.html")
@router.get("/pf_study.html")
def dashboard(c: Container = Depends(get_container)) -> Response:
    return SafeBytesResponse(c.pages.dashboard().encode("utf-8"), media_type="text/html; charset=utf-8")


@router.get("/favicon.ico")
def favicon() -> Response:
    return Response(status_code=204, media_type="image/x-icon")
