"""토지 매입가: 토지 실거래 비교사례로 산정 (세부 계산은 domain/land.py 의 calculate_land).
"""
from __future__ import annotations

import math

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


# ---------------------------------------------------------------------------
# 토지 단가 예측 모델로 토지매입대금 정하기
# ---------------------------------------------------------------------------
# land_model: 필지 목록 [{pnu, jimok, landUse, areaM2}] 을 받아
#   {"rows": [{pnu, jimok, landUse, areaM2, unitPriceKrwPerM2, status, reason, forecastMonth, targetMonth, knownGroup}]}
#   를 돌려주는 함수 (server/features/model.py 의 ModelHolder.land_estimate). 없으면 None.
# 계산 domain 은 모델 코드를 직접 부르지 않고 이 함수만 받는다.
MODEL_BASIS = "시군구·지목·용도지역 그룹의 6개월 뒤 월간 거래단가 중앙값(학습 모델 예측) × 필지 면적. 모델이 못 구한 필지는 구한 필지들의 평균 단가로 채움."


def model_parcels(land):
    """분석 결과의 필지 배분에서 모델에 보낼 필지와, 보낼 수 없는 필지(사유 포함)를 나눈다."""
    profiles = {str(p.get("pnu")): p for p in land.get("parcelProfiles") or []}
    parcels, skipped = [], []
    for row in land.get("parcelAssignments") or []:
        pnu = str(row.get("pnu") or "")
        jimok_raw = (profiles.get(pnu) or {}).get("jimokRaw") or []
        jimok = jimok_raw[0] if len(jimok_raw) == 1 else None
        area = row.get("areaM2")
        reason = ("필지 분류·경계 미확정" if row.get("status") != "ready" else "지목 미확정" if not jimok
                  else "용도지역 미확정" if not row.get("zoneName") else "면적 미확정" if not (isinstance(area, (int, float)) and area > 0)
                  else "필지 번호(PNU) 확인 필요" if not (len(pnu) == 19 and pnu.isdigit()) else None)
        if reason:
            skipped.append({"pnu": pnu, "areaM2": area, "status": "분류 불가", "reason": reason})
        else:
            parcels.append({"pnu": pnu, "jimok": jimok, "landUse": row["zoneName"], "areaM2": float(area)})
    return parcels, skipped


def combine_land_model(rows, adjustment=1.0):
    """모델 금액 = Σ(구한 필지 단가 × 면적) + 평균 단가 × 못 구한 필지 면적. 한 필지도 못 구하면 None.

    화면(frontend/build/V6.template.html 안의 combineLandModel)과 같은 계산.
    """
    def positive(value):
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0

    is_priced = [positive(r.get("unitPriceKrwPerM2")) and positive(r.get("areaM2")) for r in rows]
    if not any(is_priced) or any(not positive(r.get("areaM2")) for r in rows):
        return None  # 구한 필지가 없거나, 면적을 모르는 필지가 있으면 평균으로도 채울 수 없다
    priced_area = sum(r["areaM2"] for r, ok in zip(rows, is_priced) if ok)
    priced_won = sum(r["unitPriceKrwPerM2"] * r["areaM2"] for r, ok in zip(rows, is_priced) if ok)
    average = priced_won / priced_area
    out_rows = []
    for row, ok in zip(rows, is_priced):
        unit = row["unitPriceKrwPerM2"] if ok else average
        out_rows.append({**row, "appliedUnitPriceKrwPerM2": unit, "amountWon": unit * row["areaM2"],
                         "basis": "모델 예측" if ok else "평균 단가로 채움"})
    total_area = sum(r["areaM2"] for r in rows)
    filled_won = average * (total_area - priced_area)
    return {"used": True, "totalWon": (priced_won + filled_won) * adjustment,
            "pricedWon": priced_won, "filledWon": filled_won,
            "averageUnitPriceKrwPerM2": average, "adjustmentFactor": adjustment,
            "pricedCount": sum(is_priced), "filledCount": len(rows) - sum(is_priced), "rowCount": len(rows),
            "pricedAreaM2": priced_area, "totalAreaM2": total_area,
            "targetMonths": sorted({r["targetMonth"] for r, ok in zip(rows, is_priced) if ok and r.get("targetMonth")}),
            "rows": out_rows, "basis": MODEL_BASIS}


def _apply_land_model(land, inputs, land_model):
    """모델이 있으면 토지매입대금(representativeWon)을 모델 금액으로 바꾼다. 비교사례 금액은 따로 남긴다."""
    land["comparablesRepresentativeWon"] = land.get("representativeWon")
    land["amountBasis"] = "comparables"
    if land_model is None:
        land["modelEstimate"] = {"used": False, "reason": "학습 모델이 꺼져 있어 비교사례 금액을 씁니다."}
        return land
    parcels, skipped = model_parcels(land)
    if not parcels:
        land["modelEstimate"] = {"used": False, "reason": "모델에 보낼 수 있는 필지가 없어 비교사례 금액을 씁니다."}
        return land
    try:
        adjustment = _adjustment(inputs.get("assumptions") or {}, "landAdjustmentPct")
        estimate = land_model(parcels)
    except Exception:  # noqa: BLE001 - 모델 문제로 분석 전체가 멈추지 않게 비교사례 금액으로 둔다
        land["modelEstimate"] = {"used": False, "reason": "모델 예측에 실패해 비교사례 금액을 씁니다."}
        return land
    combined = combine_land_model(list(estimate.get("rows") or []) + skipped, adjustment)
    if combined is None:
        land["modelEstimate"] = {"used": False, "reason": "모델이 단가를 구한 필지가 없어 비교사례 금액을 씁니다.",
                                 "rows": list(estimate.get("rows") or []) + skipped}
        return land
    land.update(representativeWon=combined["totalWon"], amountBasis="model", modelEstimate=combined)
    return land
