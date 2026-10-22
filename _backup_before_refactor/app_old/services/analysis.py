from __future__ import annotations

from pf_engine import analyze


class AnalysisService:
    """Business-case calculation. Delegates to the existing engine unchanged."""

    def analyze(self, inputs: dict) -> dict:
        return analyze(inputs, partial=True)
