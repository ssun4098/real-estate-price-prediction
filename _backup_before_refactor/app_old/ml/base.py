"""The contract a trained model must satisfy. The app depends on this, never on a framework."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class Predictor(Protocol):
    name: str
    version: str

    def load(self, model_dir: Path) -> None:
        """Load weights/artifacts from ``model_dir``. Called once at startup."""

    def predict(self, features: dict[str, Any]) -> dict[str, Any]:
        """Return a JSON-serialisable result. Must be thread-safe (called from a worker pool)."""
