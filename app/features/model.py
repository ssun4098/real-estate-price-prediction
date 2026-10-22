"""학습 모델 자리. 모델이 아직 없어도 앱은 정상으로 켜진다 (자세한 방법은 data/models/README.md).

    GET  /api/model/status    not_configured(모델 미지정) / ready / failed
    POST /api/model/predict   {"features": {...}} → 모델 결과. 모델이 없으면 503 MODEL_NOT_READY

.env 의 MODEL_ENTRYPOINT=모듈:클래스 로 data/models/ 폴더 안의 클래스를 지정한다.
그 클래스는 name, version, load(model_dir), predict(features) 를 갖추면 된다.
"""
from __future__ import annotations

import importlib
import logging
import sys
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.web import ApiError, ok

router = APIRouter(prefix="/api/model", tags=["model"])
log = logging.getLogger("uvicorn.error")


@runtime_checkable
class Predictor(Protocol):
    """모델이 지켜야 할 약속 (Java의 interface 와 같은 역할)."""
    name: str
    version: str

    def load(self, model_dir: Path) -> None: ...                       # 시작할 때 한 번
    def predict(self, features: dict[str, Any]) -> dict[str, Any]: ...  # 여러 요청이 동시에 부를 수 있음


class PredictRequest(BaseModel):
    # 입력 항목은 모델이 정할 일이라 일부러 자유 형식.
    features: dict[str, Any] = Field(min_length=1, max_length=500)


# ---------------------------------------------------------------------------
# 라우터
# ---------------------------------------------------------------------------
@router.get("/status")
def model_status(request: Request):
    return ok(request.app.state.model.info())


@router.post("/predict")
def predict(request: Request, payload: PredictRequest):
    return ok(request.app.state.model.predict(payload.features))


# ---------------------------------------------------------------------------
# 모델 불러오기·호출
# ---------------------------------------------------------------------------
class ModelHolder:
    def __init__(self, model_dir: Path, entrypoint: str):
        self.model_dir = model_dir
        self.entrypoint = entrypoint
        self.predictor: Predictor | None = None
        self.state = "not_configured"
        self.error: str | None = None

    def load(self) -> None:
        """실패해도 앱은 켜진다. 원인은 /api/model/status 의 error 와 로그로 확인."""
        if not self.entrypoint:
            return
        try:
            module_name, _, class_name = self.entrypoint.partition(":")
            if not module_name or not class_name:
                raise ValueError("MODEL_ENTRYPOINT는 'module:ClassName' 형식이어야 합니다.")
            if self.model_dir.is_dir() and str(self.model_dir) not in sys.path:
                sys.path.append(str(self.model_dir))  # 맨 뒤에 추가 → app/backend 모듈을 가리지 않음
            predictor = getattr(importlib.import_module(module_name), class_name)()
            predictor.load(self.model_dir)
            if not isinstance(predictor, Predictor):
                raise TypeError("모델이 Predictor 약속(name, version, load, predict)을 지키지 않습니다.")
            self.predictor, self.state = predictor, "ready"
        except Exception as exc:  # noqa: BLE001 - 메시지에 경로가 섞일 수 있어 예외 종류만 남긴다
            self.predictor, self.state = None, "failed"
            self.error = f"모델을 불러오지 못했습니다 ({type(exc).__name__})."
            log.error("model load failed: %s", type(exc).__name__)

    def info(self) -> dict:
        return {"state": self.state, "ready": self.state == "ready",
                "name": getattr(self.predictor, "name", None),
                "version": getattr(self.predictor, "version", None),
                "error": self.error}

    def predict(self, features: dict) -> dict:
        if self.predictor is None:
            raise ApiError("MODEL_NOT_READY", "학습 모델이 아직 준비되지 않았습니다.", 503)
        try:
            result = self.predictor.predict(features)
        except (ValueError, KeyError, TypeError) as exc:
            raise ApiError("INVALID_FEATURES", "모델 입력값이 올바르지 않습니다: " + str(exc), 422) from None
        except Exception:  # noqa: BLE001 - 모델 내부 오류 내용은 밖으로 내보내지 않는다
            raise ApiError("PREDICTION_FAILED", "모델 추론 중 오류가 발생했습니다.", 500) from None
        return {"model": self.predictor.name, "version": self.predictor.version, "result": result}
