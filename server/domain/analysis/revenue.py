"""분양 수입: 비교 분양사례 단가 × 공급면적. 사례가 부족하면 계산을 보류한다.
"""
from __future__ import annotations

import copy
import math
from collections import defaultdict

from server.domain.analysis.common import WON_PER_MANWON, _positive_case, number, statistics
from server.domain.analysis.comparables import (
    _adjustment, _case_date_reason, _collection_incomplete, _comparison_linkage_context,
    _geo_distance_km, _revenue_radius_context,
)


def _revenue(inputs, development, warnings):
    assumptions = inputs.get("assumptions", {})
    adjustment = _adjustment(assumptions, "revenueAdjustmentPct")
    method = assumptions.get("revenueMethod", "median")
    if method not in ("mean", "median"):
        raise ValueError("분양 대표값은 mean 또는 median이어야 합니다.")
    complexes, excluded, seen = defaultdict(list), [], set()
    asof = inputs.get("project", {}).get("asOf")
    linkage = _comparison_linkage_context(inputs, "revenue")
    radius = _revenue_radius_context(inputs)
    context_reason = (linkage or {}).get("reason") or (radius or {}).get("reason")
    if linkage and not context_reason:
        requested_scope = (inputs.get("comparisonFilters") or {}).get("scope")
        if requested_scope and requested_scope != linkage["query"].get("scope", "dong"):
            context_reason = "분양사례 범위가 변경되었습니다. 현재 조건으로 분양사례를 다시 조회하세요."
    if context_reason:
        warnings.append(context_reason)
    for i, case in enumerate(inputs.get("comparables", {}).get("revenueCases", [])):
        cid = str(case.get("id") or f"revenue-{i}")
        reason = None
        area, price = _positive_case(case.get("supplyAreaM2")), _positive_case(case.get("priceManwon"))
        complex_id = str(case.get("houseManageNo") or case.get("complexId") or "")
        if context_reason:
            reason = context_reason
        elif _collection_incomplete(inputs, "applyhome"):
            reason = "부분 수집: 전체 표본 판정 보류"
        elif case.get("eligible") is False:
            reason = case.get("exclusionReason") or "사용자 또는 수집 단계 제외"
        elif not complex_id:
            reason = "단지 식별자 미확보"
        elif not area or not price:
            reason = "양수 가격·공급면적 미확보"
        elif case.get("addressStatus") in ("미확정", "unresolved") and not case.get("legalDongCode"):
            reason = "비교 지역 미확정"
        if not reason:
            reason = _case_date_reason(case, inputs, "revenue", linkage)
        if not reason and linkage and not radius:
            if str(case.get("legalDongCode") or "") != linkage["legalDongCode"]:
                reason = "선택 필지의 법정동 밖 분양사례 또는 법정동 미확정"
        if not reason and radius:
            try:
                lon = number(case.get("lon"), "사례 경도", minimum=120, maximum=134, required=True)
                lat = number(case.get("lat"), "사례 위도", minimum=30, maximum=40, required=True)
                if case.get("addressVerified") is not True or case.get("coordinateVerified") is not True:
                    reason = "반경 비교를 위한 사업지 위치 미확정"
                else:
                    distance = _geo_distance_km(radius["center"]["lon"], radius["center"]["lat"], lon, lat)
                    case["distanceKm"] = distance
                    if distance > radius["radiusKm"] + 1e-9:
                        reason = "선택한 분양 검색 반경 밖 사례"
            except ValueError:
                reason = "반경 비교를 위한 사업지 좌표 미확보"
        key = (complex_id, str(case.get("announcementNo") or ""), str(case.get("modelNo") or cid))
        if not reason and key in seen:
            reason = "같은 공고·주택형 식별자 중복"
        seen.add(key)
        if reason:
            excluded.append({"id": cid, "reason": reason})
        else:
            complexes[complex_id].append((case, cid, price * WON_PER_MANWON / area))
    points = []
    for complex_id, rows in complexes.items():
        announcements = {str(c.get("announcementNo") or "") for c, _, _ in rows}
        if len(announcements) > 1:
            chosen = [row for row in rows if row[0].get("representativeAnnouncement") is True]
            if not chosen or len({str(c.get("announcementNo")) for c, _, _ in chosen}) != 1:
                excluded.extend({"id": cid, "reason": "동일 단지 복수 공고 관계 미확인"} for _, cid, _ in rows)
                continue
            selected = {cid for _, cid, _ in chosen}
            excluded.extend({"id": cid, "reason": "확인된 대표 공고 외 공고"} for _, cid, _ in rows if cid not in selected)
            rows = chosen
        unit = statistics([v for _, _, v in rows])["median"]
        area = development["supplyAreaM2"]
        base = unit * area if area is not None else None
        points.append({"id": complex_id, "label": rows[0][0].get("name") or complex_id,
                       "unitPriceWonM2": unit, "baseValueWon": base,
                       "medianSupplyAreaM2": statistics([_positive_case(c["supplyAreaM2"]) for c, _, _ in rows])["median"],
                       "valueWon": base * adjustment if base is not None else None,
                       "caseIds": [cid for _, cid, _ in rows],
                       "distanceKm": rows[0][0].get("distanceKm"),
                       "legalDongName": rows[0][0].get("legalDongName")})
    stats = statistics([p["valueWon"] for p in points if p["valueWon"] is not None])
    base_stats = statistics([p["baseValueWon"] for p in points if p["baseValueWon"] is not None])
    representative = stats[method]
    final_sales = number(assumptions.get("finalSalesPct", 100), "최종 분양률", minimum=0, maximum=100, required=True)
    discount = number(assumptions.get("discountPct", 0), "할인율", minimum=0, maximum=100, required=True)
    full_net = representative * (1 - discount / 100) if representative is not None else None
    net = full_net * (final_sales / 100) if full_net is not None else None
    if final_sales < 100:
        warnings.append("미분양 잔여재고의 처분대금은 자동 반영하지 않았습니다. 별도 매각·처분 시나리오를 검토하세요.")
    return {"label": "비교단지 사례 기준 잠재 분양수입", "points": points,
            "eligibleComplexes": copy.deepcopy(points),
            "supplyAreaStats": statistics([p["medianSupplyAreaM2"] for p in points]),
            "stats": stats, "baseStats": base_stats, "unitPriceStats": statistics([p["unitPriceWonM2"] for p in points]),
            "representativeWon": representative, "potentialRevenueWon": representative,
            "fullNetRevenueWon": full_net, "netRevenueWon": net, "excluded": excluded,
            "status": ("주변 분양사례 재조회 필요" if radius else "분양사례 재조회 필요") if context_reason else "부분 수집 · 판정 보류" if _collection_incomplete(inputs, "applyhome") else "계획 공급면적 필요" if development["supplyAreaM2"] is None else stats["status"],
            "comparisonReason": context_reason,
            "comparisonScope": "radius" if radius else "dong",
            "radiusKm": radius["radiusKm"] if radius else None,
            "method": method, "sourceStatus": "공개자료 기반 추정",
            "assumption": "단지 내부 중앙값·단지 동일 가중·공통 공급면적당 단가. 실제 계약·수납액 아님"}


def _rescale_revenue(inputs, revenue, development, errors=None):
    """Keep selected comparable population fixed during linked scale changes."""
    if revenue.get("validationError"):
        return revenue
    assumptions = inputs.get("assumptions", {})
    adjustment = _adjustment(assumptions, "revenueAdjustmentPct")
    area = development["supplyAreaM2"]
    overflow = False
    for point in revenue["points"]:
        point["baseValueWon"] = point["unitPriceWonM2"] * area if area is not None else None
        point["valueWon"] = point["baseValueWon"] * adjustment if area is not None else None
        overflow |= any(v is not None and not math.isfinite(v) for v in (point["baseValueWon"], point["valueWon"]))
    if overflow:
        message = "계산 범위 초과 → 공급면적과 사례 단가를 곱한 금액이 숫자 범위를 초과합니다 → 면적·가격 보정률·사례 가격과 입력 단위를 수정하세요"
        item = {"section": "revenue", "path": "linkedScenario.farPct", "message": message}
        revenue["fieldErrors"] = [item]
        if errors is not None:
            errors.append(item)
        for point in revenue["points"]:
            point["baseValueWon"] = point["valueWon"] = None
    revenue["eligibleComplexes"] = copy.deepcopy(revenue["points"])
    revenue["stats"] = statistics([p["valueWon"] for p in revenue["points"] if p["valueWon"] is not None])
    revenue["baseStats"] = statistics([p["baseValueWon"] for p in revenue["points"] if p["baseValueWon"] is not None])
    representative = revenue["stats"][revenue["method"]]
    discount = number(assumptions.get("discountPct", 0), "할인율", minimum=0, maximum=100, required=True)
    final_sales = number(assumptions.get("finalSalesPct", 100), "최종 분양률", minimum=0, maximum=100, required=True)
    full_net = representative * (1 - discount / 100) if representative is not None else None
    revenue.update(representativeWon=representative, potentialRevenueWon=representative,
                   fullNetRevenueWon=full_net,
                   netRevenueWon=full_net * (final_sales / 100) if full_net is not None else None)
    if not revenue.get("comparisonReason") and not _collection_incomplete(inputs, "applyhome"):
        revenue["status"] = "계획 공급면적 필요" if area is None else revenue["stats"]["status"]
    if overflow:
        revenue["status"] = "입력 오류 · 금액 계산 범위 초과"
    return revenue
