"""학습 모델 자리. 모델이 아직 없어도 앱은 정상으로 켜진다 (자세한 방법은 data/models/README.md).

    GET  /api/model/status         not_configured(모델 미지정) / ready / failed
    POST /api/model/predict        {"features": {...}} → 모델 결과. 모델이 없으면 503 MODEL_NOT_READY
    POST /api/model/land-estimate  {"parcels": [{pnu, jimok, landUse, areaM2}]} → 필지별 모델 단가 × 면적과 합계
                                   (화면 '예상 토지매입대금' 옆의 모델 예측 금액)

.env 의 MODEL_ENTRYPOINT=모듈:클래스 로 data/models/ 폴더 안의 클래스를 지정한다.
그 클래스는 name, version, load(model_dir), predict(features) 를 갖추면 된다.
predict 가 낼 수 있는 예외: 입력 잘못 → ValueError/KeyError/TypeError (422),
예측에 쓸 자료가 아직 없음 → LookupError (409).
land-estimate 는 predict 결과의 unitPriceKrwPerM2(원/㎡)와 context(기준월·예측 대상월)를 쓴다.
"""
from __future__ import annotations

import importlib
import logging
import sys
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from server.web import ApiError, ok

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


class LandParcel(BaseModel):
    """필지(또는 용도지역별로 나눈 필지 조각) 하나."""
    pnu: str = Field(pattern=r"^\d{19}$")      # 앞 5자리 = 시군구 코드
    jimok: str = Field(max_length=40)          # 토지대장 지목 (예: 대, 전, 도로)
    landUse: str = Field(max_length=60)        # 용도지역 (예: 제2종일반주거지역)
    areaM2: float = Field(gt=0, allow_inf_nan=False)


class LandEstimateRequest(BaseModel):
    parcels: list[LandParcel] = Field(min_length=1, max_length=300)


# ---------------------------------------------------------------------------
# 라우터
# ---------------------------------------------------------------------------
@router.get("/status")
def model_status(request: Request):
    return ok(request.app.state.model.info())


@router.post("/predict")
def predict(request: Request, payload: PredictRequest):
    return ok(request.app.state.model.predict(payload.features))


@router.post("/land-estimate")
def land_estimate(request: Request, payload: LandEstimateRequest):
    return ok(request.app.state.model.land_estimate([p.model_dump() for p in payload.parcels]))


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
                sys.path.append(str(self.model_dir))  # 맨 뒤에 추가 → server 모듈을 가리지 않음
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
        data_info = getattr(self.predictor, "data_info", None)
        return {"state": self.state, "ready": self.state == "ready",
                "name": getattr(self.predictor, "name", None),
                "version": getattr(self.predictor, "version", None),
                "data": data_info() if callable(data_info) else None,
                "error": self.error}

    def predict(self, features: dict) -> dict:
        return {"model": self._predictor().name, "version": self._predictor().version,
                "result": self._call(features)}

    def land_estimate(self, parcels: list[dict]) -> dict:
        """필지마다 '그 토지 그룹의 6개월 뒤 단가 × 면적'. 같은 그룹은 한 번만 예측한다.

        단가를 못 구한 필지가 하나라도 있으면 totalWon 은 None 이고, 구한 것만 더한 값은 partialWon.
        """
        predictor = self._predictor()
        cache: dict[str, dict] = {}
        rows = []
        for parcel in parcels:
            row = {**parcel, "status": "산출", "reason": None, "unitPriceKrwPerM2": None, "amountWon": None,
                   "landGroupKey": None, "forecastMonth": None, "targetMonth": None, "knownGroup": None}
            features = {"sggCode": parcel["pnu"][:5], "jimok": parcel["jimok"], "landUse": parcel["landUse"]}
            try:
                key = (features["sggCode"], features["jimok"], features["landUse"])
                if key not in cache:
                    cache[key] = self._call(features)
                result = cache[key]
            except ApiError as exc:
                row.update(status="자료 없음" if exc.status == 409 else "분류 불가", reason=exc.message)
                rows.append(row)
                continue
            context = result.get("context") or {}
            row.update(landGroupKey=result["landGroupKey"], unitPriceKrwPerM2=result["unitPriceKrwPerM2"],
                       amountWon=result["unitPriceKrwPerM2"] * parcel["areaM2"], knownGroup=result["knownGroup"],
                       forecastMonth=context.get("forecastMonth"), targetMonth=context.get("targetMonth"))
            rows.append(row)

        priced = [r for r in rows if r["amountWon"] is not None]
        partial = sum(r["amountWon"] for r in priced)
        return {
            "model": predictor.name, "version": predictor.version,
            "rows": rows,
            "totalWon": partial if priced and len(priced) == len(rows) else None,
            "partialWon": partial if priced else None,
            "pricedCount": len(priced), "rowCount": len(rows),
            "pricedAreaM2": sum(r["areaM2"] for r in priced), "totalAreaM2": sum(r["areaM2"] for r in rows),
            "targetMonths": sorted({r["targetMonth"] for r in priced if r["targetMonth"]}),
            "basis": "시군구·지목·용도지역 그룹의 6개월 뒤 월간 거래단가 중앙값(모델 예측) × 필지 면적. 필지별 감정가가 아닙니다.",
        }

    # ------------------------------------------------------------------
    def _predictor(self) -> Predictor:
        if self.predictor is None:
            raise ApiError("MODEL_NOT_READY", "학습 모델이 아직 준비되지 않았습니다.", 503)
        return self.predictor

    def _call(self, features: dict) -> dict:
        try:
            return self._predictor().predict(features)
        except ApiError:
            raise
        except (ValueError, KeyError, TypeError) as exc:
            raise ApiError("INVALID_FEATURES", "모델 입력값이 올바르지 않습니다: " + str(exc), 422) from None
        except LookupError as exc:  # KeyError 는 위에서 먼저 잡힌다
            raise ApiError("MODEL_DATA_MISSING", str(exc), 409) from None
        except Exception:  # noqa: BLE001 - 모델 내부 오류 내용은 밖으로 내보내지 않는다
            raise ApiError("PREDICTION_FAILED", "모델 추론 중 오류가 발생했습니다.", 500) from None
