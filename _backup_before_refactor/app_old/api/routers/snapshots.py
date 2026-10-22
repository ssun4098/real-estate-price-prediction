from __future__ import annotations

from fastapi import APIRouter, Depends
from starlette.responses import Response

from app.api.deps import get_container
from app.container import Container
from app.core.http import SafeJSONResponse, SafeRoute, json_body

router = APIRouter(route_class=SafeRoute)


@router.get("/api/snapshots")
def list_snapshots(c: Container = Depends(get_container)) -> Response:
    return SafeJSONResponse({"items": c.snapshots.list()})


@router.get("/api/snapshots/{ident}")
def read_snapshot(ident: str, c: Container = Depends(get_container)) -> Response:
    return SafeJSONResponse(c.snapshots.read(ident))


@router.get("/pf-study-v6-snapshots/{ident}.json", include_in_schema=False)
def read_snapshot_legacy_path(ident: str, c: Container = Depends(get_container)) -> Response:
    return SafeJSONResponse(c.snapshots.read(ident))


# /api/save and /api/export-json were two endpoints because one also rewrote V6.html on disk.
# The page is now rendered per request from MySQL, so both store the same record.
@router.post("/api/save")
@router.post("/api/export-json")
def save_snapshot(body: dict = Depends(json_body), c: Container = Depends(get_container)) -> Response:
    return SafeJSONResponse(c.snapshots.save(body))
