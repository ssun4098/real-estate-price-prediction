from __future__ import annotations

from fastapi import APIRouter, Depends
from starlette.responses import Response

from app.api.deps import get_container
from app.container import Container
from app.core.http import SafeJSONResponse, SafeRoute, json_body

router = APIRouter(prefix="/api", route_class=SafeRoute)


@router.get("/portfolio-samples")
def list_samples(c: Container = Depends(get_container)) -> Response:
    return SafeJSONResponse({"items": c.portfolio.list(), "defaultId": c.portfolio.default_id()})


@router.get("/portfolio-samples/{ident}")
def read_sample(ident: str, c: Container = Depends(get_container)) -> Response:
    return SafeJSONResponse(c.portfolio.read(ident))


@router.post("/portfolio-samples")
def save_sample(body: dict = Depends(json_body), c: Container = Depends(get_container)) -> Response:
    return SafeJSONResponse(c.portfolio.save(body))


@router.get("/portfolio-default")
def read_default(c: Container = Depends(get_container)) -> Response:
    return SafeJSONResponse({"id": c.portfolio.default_id()})


@router.post("/portfolio-default")
def set_default(body: dict = Depends(json_body), c: Container = Depends(get_container)) -> Response:
    return SafeJSONResponse(c.portfolio.set_default(body.get("id")))
