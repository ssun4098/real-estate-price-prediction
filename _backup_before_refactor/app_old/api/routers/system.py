from __future__ import annotations

from fastapi import APIRouter, Depends, Path
from starlette.responses import Response

from app.api.deps import get_container
from app.container import Container
from app.core.http import SafeBytesResponse, SafeJSONResponse, SafeRoute

router = APIRouter(route_class=SafeRoute)


@router.get("/healthz", include_in_schema=False)
def healthz(c: Container = Depends(get_container)) -> Response:
    """Liveness + database reachability for the container healthcheck. Exposes no details."""
    c.ping()
    return SafeJSONResponse({"status": "ok"})


@router.get("/api/status")
def status(c: Container = Depends(get_container)) -> Response:
    info = c.public_data.status("MySQL")
    info["model"] = c.prediction.status()
    return SafeJSONResponse(info)


@router.get("/api/tiles/{z}/{y}/{x}.jpeg")
def tile(z: int = Path(ge=0, le=30), y: int = Path(ge=0), x: int = Path(ge=0),
         c: Container = Depends(get_container)) -> Response:
    response = SafeBytesResponse(c.public_data.tile(z, y, x), media_type="image/jpeg")
    response.headers["Cache-Control"] = "private, max-age=300"
    return response
