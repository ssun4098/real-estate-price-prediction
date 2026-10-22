"""Trained-model endpoints. Safe to call before a model exists: they report why it is unavailable."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from starlette.responses import Response

from app.api.deps import get_container
from app.container import Container
from app.core.http import SafeJSONResponse, SafeRoute
from app.schemas.prediction import ModelStatus, PredictRequest, PredictResponse

router = APIRouter(prefix="/api/model", route_class=SafeRoute, tags=["model"])


@router.get("/status", response_model=ModelStatus)
def model_status(c: Container = Depends(get_container)) -> Response:
    return SafeJSONResponse(c.prediction.status())


@router.post("/predict", response_model=PredictResponse)
def predict(payload: PredictRequest, c: Container = Depends(get_container)) -> Response:
    return SafeJSONResponse(c.prediction.predict(payload.features))
