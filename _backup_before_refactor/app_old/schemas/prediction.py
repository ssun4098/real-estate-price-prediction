from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class PredictRequest(BaseModel):
    # Free-form on purpose: the feature set belongs to the model, which is not defined yet.
    features: dict[str, Any] = Field(min_length=1, max_length=500)


class ModelStatus(BaseModel):
    state: str
    ready: bool
    name: str | None = None
    version: str | None = None
    error: str | None = None


class PredictResponse(BaseModel):
    model: str | None
    version: str | None
    result: dict[str, Any]
