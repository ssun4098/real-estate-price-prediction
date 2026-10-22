from __future__ import annotations

from fastapi import APIRouter, Depends
from starlette.responses import Response

from app.api.deps import get_container
from app.container import Container
from app.core.http import SafeJSONResponse, SafeRoute, json_body

router = APIRouter(prefix="/api", route_class=SafeRoute)


@router.post("/analyze")
def analyze(body: dict = Depends(json_body), c: Container = Depends(get_container)) -> Response:
    return SafeJSONResponse(c.analysis.analyze(body))
