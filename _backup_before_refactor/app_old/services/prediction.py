from __future__ import annotations

from app.core.errors import ApiError
from app.ml.registry import ModelRegistry


class PredictionService:
    """The only way the rest of the app reaches the trained model."""

    def __init__(self, registry: ModelRegistry):
        self.registry = registry

    def status(self) -> dict:
        return self.registry.info()

    def predict(self, features: dict) -> dict:
        predictor = self.registry.predictor
        if predictor is None:
            raise ApiError("MODEL_NOT_READY", "학습 모델이 아직 준비되지 않았습니다.", 503)
        try:
            result = predictor.predict(features)
        except (ValueError, KeyError, TypeError) as exc:
            # Bad features are the caller's problem; model internals are not.
            raise ApiError("INVALID_FEATURES", "모델 입력값이 올바르지 않습니다: " + str(exc), 422) from None
        except Exception:  # noqa: BLE001
            raise ApiError("PREDICTION_FAILED", "모델 추론 중 오류가 발생했습니다.", 500) from None
        return {"model": predictor.name, "version": predictor.version, "result": result}
