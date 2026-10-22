"""사업성 계산의 전체 순서.

    analyze(입력)            입력 검사 → 개발 규모 → 분양 수입 → 토지비 → 금융 단가·예산 → 현금흐름 → 사업비 합계 → 지표
    validate_snapshot(저장본)  저장본을 믿지 않고 analyze 로 다시 계산

네트워크·인증키를 쓰지 않는다. 문서에 없는 업무 기본값을 몰래 채우지 않는다.
"""
from __future__ import annotations

import copy
import datetime as dt
import re
import uuid

from server.domain.land import parcel_profile
from server.domain.analysis.common import VERSION, _input_error, _safe_tree, date_value, number
from server.domain.analysis.comparables import _collection_incomplete
from server.domain.analysis.development import (
    _development, _linked_development, _partial_development,
)
from server.domain.analysis.revenue import _rescale_revenue, _revenue
from server.domain.analysis.land_price import _land
from server.domain.analysis.costs import _apply_finance_price, _budget_allocation, _costs
from server.domain.analysis.cashflow import (
    _cashflow_scalar_errors, _empty_cashflow, calculate_cashflow,
)


def _okr(inputs, costs, cashflow):
    cfg = inputs.get("okr") or {}
    approved = cfg.get("targetsConfirmed") is True
    actuals = cfg.get("actuals") or {}
    targets = cfg.get("targets") or {}
    def row(identifier, label, actual, target, direction="le"):
        v = number(actual, label, minimum=0)
        t = number(target, label + " 목표", minimum=0) if approved else None
        state = "실적 미확인" if v is None else "목표 미설정" if t is None else ("목표 충족" if (v <= t if direction == "le" else v >= t) else "목표 미충족")
        return {"id": identifier, "label": label, "actual": v, "target": t, "status": state}
    rows = [row("unsold6", "분양 개시 6개월 미분양률", actuals.get("unsold6Pct"), targets.get("unsold6Pct")),
            row("unsoldCompletion", "계약 준공일 미분양률", actuals.get("unsoldCompletionPct"), targets.get("unsoldCompletionPct")),
            row("dueCollection", "납기도래 분양대금 수납률", actuals.get("dueCollectionPct"), targets.get("dueCollectionPct"), "ge")]
    budget = number(targets.get("originalConstructionBudgetWon"), "최초 승인 공사비", minimum=0)
    construction_rows = [r for r in costs["items"] if r.get("category", r["id"]) in ("construction", "separate_construction")]
    construction = sum(r["amountWon"] for r in construction_rows) if construction_rows and all(r["amountWon"] is not None for r in construction_rows) else None
    rows.append({"id": "construction", "label": "최초 승인 공사비 예산 준수", "actual": construction,
                 "target": budget if approved else None,
                 "status": "목표 미설정" if not approved or budget is None else "계산 미완료" if construction is None else ("시나리오상 목표 충족" if construction <= budget else "시나리오상 목표 미충족")})
    rows.append(row("completion", "준공 지연일수", actuals.get("completionDelayDays"), 0))
    rows.append(row("overdue", "기한 경과 미지급액", actuals.get("overdueWon"), 0))
    gap = cashflow.get("summary", {}).get("maxUnfunded13WeeksWon")
    rows.append({"id": "funding", "label": "향후 13주 최대 미조달 부족액", "actual": gap, "target": 0,
                 "status": "계산 미완료" if gap is None else ("시나리오상 목표 충족" if gap <= .5 else "시나리오상 목표 미충족")})
    return {"targetsConfirmed": approved, "targetVersion": cfg.get("targetVersion"), "rows": rows,
            "note": "공개자료·가정으로 실제 운영 성과를 판정하지 않습니다. 미분양·수납 목표는 사업별 승인 후 적용합니다."}


def _error_path(message, section, inputs):
    """Use stable input paths for field-level UI links, with a section fallback."""
    message = str(message)
    explicit = re.match(r"(cashflow\.events\.\d+\.contractDate):", message)
    if explicit:
        return explicit.group(1)
    aliases = {
        "revenue": {"대표값": "assumptions.revenueMethod", "가격 보정률": "assumptions.revenueAdjustmentPct", "revenueAdjustmentPct": "assumptions.revenueAdjustmentPct", "최종 분양률": "assumptions.finalSalesPct", "할인율": "assumptions.discountPct"},
        "land": {"대표값": "assumptions.landMethod", "가격 보정률": "assumptions.landAdjustmentPct", "landAdjustmentPct": "assumptions.landAdjustmentPct"},
        "cashflow": {"차입 구분": "cashflow.debtMode", "기초 현금": "cashflow.openingCashWon", "현금흐름 기준일": "cashflow.asOf", "현금흐름 시작일": "cashflow.startDate", "사업 정산일": "cashflow.endDate", "PF 만기일": "cashflow.maturityDate", "조달 확정": "cashflow.financingConfirmed", "기초 차입잔액": "cashflow.openingDebtWon", "차입 없음": "cashflow.debtMode", "일수 기준": "cashflow.interestDayBasis", "이자 지급일": "cashflow.interestPaymentDates", "신탁": "cashflow.trust", "향후": "cashflow.exit", "판매 경로": "cashflow.exit", "기준일 누적": "cashflow.exit.pastContractedPct", "예상 추가": "cashflow.exit.expectedFutureContractedPct", "지급·수납일": "cashflow.events", "현금흐름 행": "cashflow.events", "토지 계약금": "cashflow.events"},
    }
    for key, path in aliases.get(section, {}).items():
        if key in message:
            return path
    for field in ("openingDebtWon", "loanLimitWon", "annualRatePct", "openingCashWon"):
        if field in message:
            return "cashflow." + field
    return section


def analyze(inputs, partial=False):
    if not isinstance(inputs, dict):
        raise ValueError("분석 입력은 JSON 객체여야 합니다.")
    safe = _safe_tree(inputs)
    allowed = {"project", "parcels", "unitPlan", "comparables", "assumptions", "costs", "cashflow", "sources", "okr", "map", "filters", "comparisonFilters", "collectionStatus", "uiSettings", "uiProgress", "planHistory", "linkedScenario", "budgetAllocation", "financeEditor"}
    safe = {k: v for k, v in safe.items() if k in allowed}
    for field in ("parcels", "unitPlan", "costs", "sources"):
        if not isinstance(safe.get(field, []), list):
            raise ValueError(f"{field}: 목록이 필요합니다.")
    for field in ("project", "comparables", "assumptions", "linkedScenario", "budgetAllocation", "financeEditor"):
        if not isinstance(safe.get(field, {}), dict):
            raise ValueError(f"{field}: 객체가 필요합니다.")
    # Refresh verified saved overlay calculations from retained raw polygons;
    # no API call or guessed geometry. Held evidence stays untouched so a stale
    # attribute/PNU/version conflict cannot disappear on the next analysis.
    from server.domain.boundary import recompute_boundary
    for parcel in safe.get("parcels", []):
        if isinstance(parcel, dict) and isinstance(parcel.get("boundaryAllocation"), dict):
            recalculated = recompute_boundary(parcel)
            if recalculated.get("status") == "ready":
                parcel["boundaryAllocation"] = recalculated
    errors, warnings = [], []
    invalid_asof = False
    if safe.get("project", {}).get("asOf"):
        try:
            date_value(safe["project"]["asOf"], "분석 기준일")
        except ValueError as exc:
            _input_error(errors if partial else None, "comparison", "project.asOf", exc)
            invalid_asof = True
    linked_enabled = safe.get("linkedScenario", {}).get("enabled") is True
    development_inputs = safe
    if linked_enabled:
        # Preserve the original manual plan in the snapshot. It is deliberately
        # not a dependency of the separately enabled linked scenario.
        development_inputs = copy.deepcopy(safe)
        development_inputs["unitPlan"] = []
        development_inputs.setdefault("assumptions", {}).pop("farBaseAreaM2", None)
        development_inputs["assumptions"].pop("farPct", None)
    development = _partial_development(development_inputs, warnings, errors) if partial else _development(development_inputs, warnings)
    def part(section, operation, fallback):
        try:
            return _safe_tree(operation())
        except (ValueError, TypeError, AttributeError, KeyError, OverflowError) as exc:
            if not partial:
                raise
            _input_error(errors, section, _error_path(exc, section, safe), exc)
            result = fallback()
            result.update(status="입력 오류 · 계산 보류", validationError=str(exc))
            return result
    empty = {"project": {}, "parcels": [], "comparables": {}, "assumptions": {}}
    def revenue_operation():
        if invalid_asof:
            raise ValueError("분석 기준일을 확인하세요.")
        return _revenue(safe, development, warnings)
    def land_operation():
        if invalid_asof:
            raise ValueError("분석 기준일을 확인하세요.")
        return _land(safe, development, warnings)
    revenue = part("revenue", revenue_operation, lambda: _revenue(empty, development, []))
    linked_result = _linked_development(safe, development, revenue, errors if partial else None)
    if linked_enabled:
        revenue = _rescale_revenue(safe, revenue, development, errors if partial else None)
        warnings.append("필지 확인 면적을 대지면적으로, 용적률 적용 면적을 공급면적으로 보는 간이 가정입니다. 법적 허용 용적률·인허가 가능 호수를 확정한 결과가 아닙니다.")
    land = part("land", land_operation, lambda: _land(empty, development, []))
    revenue = _apply_finance_price(safe, revenue, "revenue", errors if partial else None)
    land = _apply_finance_price(safe, land, "land", errors if partial else None)
    for parcel in safe.get("parcels", []):
        if isinstance(parcel, dict): parcel["comparisonProfile"] = parcel_profile(parcel)
    budget = _budget_allocation(safe, revenue, land, errors if partial else None) if linked_enabled or "budgetAllocation" in safe or "financeEditor" in safe else None
    if partial:
        _cashflow_scalar_errors(safe.get("cashflow"), errors)
    if any(e["section"] == "cashflow" for e in errors):
        cashflow = _empty_cashflow([e["message"] for e in errors if e["section"] == "cashflow"])
        cashflow["status"] = "입력 오류 · 계산 보류"
    else:
        cashflow = part("cashflow", lambda: calculate_cashflow(safe.get("cashflow"), revenue["fullNetRevenueWon"], land["representativeWon"]), lambda: _empty_cashflow(["입력 오류 항목을 확인하세요."]))
    if isinstance(safe.get("cashflow"), dict) and safe["cashflow"].get("debtMode") == "none":
        cashflow["debtMode"] = "none"
        cashflow["exit"].update(status="해당 없음", reason="PF 차입 없음")
    costs = part("costs", lambda: _costs(safe, land, revenue, cashflow, warnings, errors if partial else None), lambda: _costs({}, land, revenue, cashflow, []))
    if any(e["section"] == "costs" for e in errors):
        costs["status"] = "입력 오류 · 일부 계산 보류"
    if _collection_incomplete(safe):
        affected = "·".join(label for dataset, label in (("applyhome", "분양"), ("land", "토지")) if _collection_incomplete(safe, dataset))
        warnings.append(f"{affected} 자료 수집 미완료: 해당 표본과 의존하는 수지 판정을 보류했습니다. 전체 페이지·기간을 다시 조회하세요.")
    if cashflow.get("summary") and revenue["netRevenueWon"] is not None:
        total_receipts = cashflow["summary"]["totalSalesReceiptWon"]
        if total_receipts > revenue["fullNetRevenueWon"] + 1:
            warnings.append("예정 분양 수납 합계가 전량 판매 순매출을 초과합니다. 기존 계약 수납과 향후 계약 경로 중복을 확인하세요.")
    kpis = {
        "profitMargin": {"value": costs["marginPct"], "target": costs["targetMarginPct"], "unit": "%",
                         "status": "계산 미완료" if costs["marginPct"] is None else "목표 미설정" if costs["targetMarginPct"] is None else ("시나리오상 목표 충족" if costs["marginPct"] >= costs["targetMarginPct"] else "시나리오상 목표 미충족")},
        "exit": cashflow["exit"],
        "funding": {"value": cashflow.get("summary", {}).get("maxUnfundedWon"), "target": 0, "unit": "원"},
    }
    okr = part("okr", lambda: _okr(safe, costs, cashflow), lambda: _okr({}, costs, cashflow))
    results = {"development": development, "revenue": revenue, "land": land,
               "costs": costs, "cashflow": cashflow, "kpis": kpis, "okr": okr,
               "linkedScenario": linked_result, "budget": budget}
    if partial:
        results["validation"] = {"mode": "partial", "fieldErrors": errors,
            "sections": {section: {"status": "invalid" if any(e["section"] == section for e in errors) else "valid",
                                   "errors": [e for e in errors if e["section"] == section]}
                         for section in ("comparison", "development", "linkedScenario", "budget", "revenue", "land", "costs", "cashflow", "okr")}}
        warnings += [e["message"] for e in errors]
    project = safe.get("project", {})
    snapshot = {"schemaVersion": 1, "analysisVersion": VERSION,
            "id": "pf-" + uuid.uuid4().hex, "createdAt": dt.datetime.now(dt.timezone.utc).isoformat(),
            "name": str(project.get("name") or "미지정 사업"), "scenario": str(project.get("scenario") or "기본 시나리오"),
            "inputs": safe, "results": results, "sources": safe.get("sources", []),
            "warnings": list(dict.fromkeys(warnings))}
    return _safe_tree(snapshot)


def validate_snapshot(snapshot):
    """Validate then recompute canonical results; uploaded numbers aren't trusted."""
    if not isinstance(snapshot, dict) or snapshot.get("schemaVersion") != 1 or snapshot.get("analysisVersion") not in (VERSION, "pf-study-1", "pf-study-2", "pf-study-3"):
        raise ValueError("지원하지 않는 분석 결과 버전입니다.")
    safe = _safe_tree(snapshot)
    if not isinstance(safe.get("inputs"), dict):
        raise ValueError("분석 결과에 입력 조건이 없습니다.")
    sid = str(safe.get("id") or "")
    if not re.fullmatch(r"pf-[a-zA-Z0-9_-]{1,100}", sid):
        raise ValueError("분석 결과 ID가 올바르지 않습니다.")
    timestamp = str(safe.get("createdAt") or "")
    try:
        dt.datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("분석 결과 생성시각이 올바르지 않습니다.") from None
    computed = analyze(safe["inputs"], partial=safe.get("results", {}).get("validation", {}).get("mode") == "partial")
    computed["id"], computed["createdAt"] = sid, timestamp
    return computed
