"""토지 매입가: 토지 실거래 비교사례로 산정 (세부 계산은 domain/land.py 의 calculate_land).
"""
from __future__ import annotations

from server.domain.land import calculate_land
from server.domain.analysis.common import _positive_case, statistics
from server.domain.analysis.comparables import (
    _adjustment, _case_date_reason, _collection_incomplete, _comparison_linkage_context,
)


def _land(inputs, development, warnings=None):
    linkage = _comparison_linkage_context(inputs, "land")
    if linkage and not linkage.get("reason"):
        wanted = inputs.get("comparisonFilters", {}).get("landScope", "dong")
        fetched = linkage["query"].get("landScope", "dong")
        if wanted != fetched and linkage["query"].get("landRawScope") != "sgg":
            linkage["reason"] = "토지 비교 범위가 변경되었습니다. 시군구 원자료를 다시 조회하세요."
    if (linkage or {}).get("reason") and warnings is not None:
        warnings.append(linkage["reason"])
    return calculate_land(inputs, development, stats=statistics, context=linkage,
                          date_reason=lambda case: _case_date_reason(case, inputs, "land", linkage),
                          incomplete=_collection_incomplete(inputs, "land"), positive=_positive_case,
                          adjustment=_adjustment(inputs.get("assumptions", {}), "landAdjustmentPct"))
