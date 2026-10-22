"""Loads the configured model once and reports its state.

States: ``not_configured`` (no MODEL_ENTRYPOINT: the normal state until a model
exists), ``ready`` and ``failed``. A missing or broken model never prevents the
rest of the application from starting.
"""
from __future__ import annotations

import importlib
import logging
import sys
from pathlib import Path

from app.ml.base import Predictor

log = logging.getLogger("v6.ml")


class ModelRegistry:
    def __init__(self, model_dir: Path, entrypoint: str):
        self.model_dir = model_dir
        self.entrypoint = entrypoint
        self.predictor: Predictor | None = None
        self.state = "not_configured"
        self.error: str | None = None

    def load(self) -> None:
        if not self.entrypoint:
            return
        try:
            module_name, _, class_name = self.entrypoint.partition(":")
            if not module_name or not class_name:
                raise ValueError("MODEL_ENTRYPOINT는 'module:ClassName' 형식이어야 합니다.")
            if self.model_dir.is_dir() and str(self.model_dir) not in sys.path:
                sys.path.append(str(self.model_dir))  # appended, so it can never shadow app/backend modules
            predictor = getattr(importlib.import_module(module_name), class_name)()
            predictor.load(self.model_dir)
            if not isinstance(predictor, Predictor):
                raise TypeError("모델이 Predictor 계약(name, version, load, predict)을 만족하지 않습니다.")
            self.predictor, self.state = predictor, "ready"
        except Exception as exc:  # noqa: BLE001 - report only the type; messages may contain paths
            self.predictor, self.state = None, "failed"
            self.error = f"모델을 불러오지 못했습니다 ({type(exc).__name__})."
            log.error("model load failed: %s", type(exc).__name__)

    def info(self) -> dict:
        return {
            "state": self.state,
            "ready": self.state == "ready",
            "name": getattr(self.predictor, "name", None),
            "version": getattr(self.predictor, "version", None),
            "error": self.error,
        }
