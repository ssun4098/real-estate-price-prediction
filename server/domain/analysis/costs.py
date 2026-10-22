"""사업비: 항목별 비용, 예산 배분 우선순위, 금융비 단가 반영.
"""
from __future__ import annotations

import math
from collections import defaultdict

from server.domain.analysis.common import SOURCE_STATES, _input_error, number


COST_LABELS = {
    "land_purchase": "토지 매입대금", "land_extra": "토지 취득 부대비용",
    "construction": "본 도급공사비", "separate_construction": "별도 공사비",
    "professional": "설계·감리·사업관리비", "tax_guarantee": "세금·부담금·보증료",
    "marketing_operating": "분양·광고·운영비", "finance_trust": "금융비·신탁보수",
    "contingency": "예비비",
}


def _expense_priority_basis(income, land_won, target, rows, ready):
    """Preserve expense settings; solve budget = fixed + budget * share.

    Keep requested and applied margins separate. A partial estimate must never
    claim that lowering the margin makes all expenses affordable.
    Browser counterpart: budget-priority.mjs / expensePriorityBasis.
    """
    requested = income * (1 - target / 100) if income is not None and target is not None else None
    result = {"requestedTargetMarginPct": target, "appliedTargetMarginPct": None,
              "requestedAllowableWon": requested, "allowableWon": requested,
              "minimumRequiredBudgetWon": None, "fixedExpenseWon": None,
              "budgetExpensePct": None, "targetAdjusted": False,
              "targetAdjustmentStatus": "pending", "adjustmentError": None}
    if not ready:
        return result
    share = sum(r["value"] for r in rows if r["mode"] == "budgetPct") / 100
    fixed = land_won + sum(r["value"] if r["mode"] == "amount" else income * (r["value"] / 100)
                           if r["mode"] == "revenuePct" else 0 for r in rows)
    result.update(fixedExpenseWon=fixed if math.isfinite(fixed) else None, budgetExpensePct=share * 100)
    def fail(status, message):
        return dict(result, allowableWon=None, targetAdjustmentStatus=status, adjustmentError=message)
    if not math.isfinite(fixed) or not math.isfinite(requested):
        return fail("overflow", "지출 합계가 계산 범위를 초과했습니다. 금액·비율의 입력 단위를 확인하세요.")
    if share >= 1 and (fixed > 0 or (share > 1 and requested > 0)):
        return fail("infeasible", "지출% 합계가 100% 이상이어서 토지비·금액·수입% 비용을 함께 충당할 수 없습니다. 지출 비율 또는 입력 기준을 확인하세요.")
    required = fixed / (1 - share) if share < 1 else 0
    allowable = max(requested, required)
    tolerance = max(1e-7, 2.220446049250313e-16 * max(1, abs(allowable), abs(requested)) * 32)
    adjusted = allowable - requested > tolerance
    applied = ((1 - allowable / income) * 100 if adjusted else target) if income > 0 else None
    if not math.isfinite(required) or not math.isfinite(allowable) or (income > 0 and not math.isfinite(applied)):
        return fail("overflow", "지출 설정을 유지하는 목표 수익률 계산이 숫자 범위를 초과했습니다. 입력 금액과 지출 비율을 확인하세요.")
    result.update(allowableWon=allowable, minimumRequiredBudgetWon=required,
                  appliedTargetMarginPct=applied, targetAdjusted=adjusted,
                  targetAdjustmentStatus="zero-revenue" if income == 0 else "lowered" if adjusted else "unchanged")
    return result


def _budget_allocation(inputs, revenue, land, errors):
    """Budget envelopes never replace independent cost estimates or cash flows."""
    config = inputs.get("budgetAllocation") or {}
    fields = (("construction", "공사비", 60), ("indirect", "간접 공사비", 4),
              ("sales", "분양제비용", 4), ("tax", "제세공과금", 3), ("finance", "금융비용", 4))
    local_errors = []
    def error(path, value, reason, action):
        item = {"section": "budget", "path": path,
                "message": f"{value if value not in (None, '') else '미입력'} → {reason} → {action}"}
        local_errors.append(item)
        if errors is not None:
            errors.append(item)
    def numeric(value, path, label, minimum=0, maximum=100):
        try:
            return number(value, label, minimum=minimum, maximum=maximum, required=True)
        except ValueError:
            error(path, value, label + "이 없거나 허용 범위를 벗어났습니다", f"{minimum}~{maximum} 범위의 숫자로 수정하세요")
            return None
    target_raw = inputs.get("assumptions", {}).get("targetMarginPct")
    target = numeric(target_raw, "assumptions.targetMarginPct", "기대 수익률", maximum=99)
    income = revenue["representativeWon"]
    allowable = income * (1 - target / 100) if income is not None and target is not None else None
    rows = []
    expense_edits = (inputs.get("financeEditor") or {}).get("expenses") or {}
    if not isinstance(expense_edits, dict):
        error("financeEditor.expenses", expense_edits, "비용 편집 항목은 객체여야 합니다", "비용 입력 형식을 확인하세요")
        expense_edits = {}
    def expense_value(key, default_mode, default_value, label):
        edit = expense_edits.get(key, {"mode": default_mode, "value": default_value})
        path = "financeEditor.expenses." + key
        value_path = path + ".value" if key in expense_edits else "budgetAllocation." + ("trustRatePct" if key == "trust" else key + "Pct")
        if not isinstance(edit, dict) or edit.get("mode") not in ("budgetPct", "revenuePct", "amount"):
            error(path, edit, "지원하지 않는 비용 입력 방식입니다", "허용예산 비율·수입 비율·금액 중 선택하세요")
            return None, None, None
        mode = edit["mode"]
        value = numeric(edit.get("value"), value_path, label, maximum=None if mode == "amount" else 100)
        base = allowable if mode == "budgetPct" else income
        amount = value if mode == "amount" else base * (value / 100) if base is not None and value is not None else None
        if amount is not None and not math.isfinite(amount):
            error(path + ".value", value, "비용 계산 범위를 초과했습니다", "금액·비율의 단위를 확인하세요")
            amount = None
        return mode, value, amount
    for key, label, default in fields:
        mode, value, amount = expense_value(key, "budgetPct", config.get(key + "Pct", default), label + " 배분값")
        pct = value if mode == "budgetPct" else None
        rows.append({"id": key, "label": "허용 " + label, "pct": pct,
                     "mode": mode, "value": value, "amountWon": amount})
    trust_type = config.get("trustType", "")
    if trust_type is None:
        trust_type = ""
    trust_rate = trust_won = None
    # An unselected product can use the user's 1% budget assumption; this does
    # not choose a trust contract or change the separate cash-flow fee schedule.
    if trust_type in ("", "management", "completion"):
        default_rate = config.get("trustRatePct")
        if default_rate is None or isinstance(default_rate, str) and not default_rate.strip():
            default_rate = 1
        trust_mode, trust_value, trust_won = expense_value("trust", "revenuePct", default_rate, "참고 신탁보수")
        trust_rate = trust_value if trust_mode == "revenuePct" else None
    elif trust_type == "distribution":
        error("budgetAllocation.trustType", "분양관리신탁", "순수 아파트 사업에 단일 매출액 요율을 적용할 수 없습니다", "적용 대상·보수 조건을 확인하세요. 관리형 상품을 검토하거나 조건 확정 전에는 신탁보수 산출을 보류하세요")
    else:
        error("budgetAllocation.trustType", trust_type, "지원하지 않는 신탁상품입니다", "상품 미선택의 사용자 가정 또는 지원하는 신탁상품을 선택하세요")
    trust_row = {"id": "trust", "mode": locals().get("trust_mode"), "value": locals().get("trust_value")}
    all_rows = rows + [trust_row]
    ready = (not local_errors and income is not None and income >= 0
             and land.get("representativeWon") is not None and land["representativeWon"] >= 0
             and all(r.get("value") is not None for r in all_rows))
    priority = _expense_priority_basis(income, land.get("representativeWon"), target, all_rows, ready)
    allowable = priority["allowableWon"]
    if priority["adjustmentError"]:
        error("financeEditor.expenses", "지출 설정", priority["adjustmentError"], "지출 입력 기준·금액·비율을 확인하세요")
    for row in rows:
        if row["mode"] == "budgetPct":
            row["amountWon"] = allowable * (row["value"] / 100) if allowable is not None and row["value"] is not None else None
    if trust_row["mode"] == "budgetPct":
        trust_won = allowable * (trust_row["value"] / 100) if allowable is not None and trust_row["value"] is not None else None
    values = [r["amountWon"] for r in rows] + [land["representativeWon"], trust_won]
    known = sum(v for v in values if v is not None)
    if not math.isfinite(known):
        error("budgetAllocation", "금액 합계 초과", "배분 지출 합계가 숫자 범위를 초과합니다", "분양수입·토지비·배분율과 입력 단위를 확인하여 수정하세요")
        known = None
    complete = allowable is not None and all(v is not None for v in values) and not local_errors
    allocated = known if complete else None
    gap = allowable - allocated if complete else None
    tolerance = max(1e-7, 2.220446049250313e-16 * max(1, abs(allowable or 0), abs(allocated or 0)) * 32)
    if gap is not None and abs(gap) <= tolerance:
        gap = 0
    total_pct = sum(r["pct"] for r in rows) if all(r["pct"] is not None for r in rows) else None
    return {"revenueWon": income, **priority, "targetMarginPct": target,
            "landWon": land["representativeWon"], "trustWon": trust_won,
            "trustType": trust_type, "trustRatePct": trust_rate,
            "trustRateSource": "사용자 예산 가정 · 기본 총수입의 1% · 계약 확정 아님" if trust_rate is not None else None,
            "allocationRows": rows, "allocationPctTotal": total_pct,
            "knownAllocatedWon": known, "allocatedWon": allocated,
            "unallocatedWon": max(gap, 0) if gap is not None else None,
            "overallocatedWon": max(-gap, 0) if gap is not None else None,
            "profitWon": income - allocated if income is not None and allocated is not None else None,
            "profitMarginPct": (income - allocated) / income * 100 if income and allocated is not None else None,
            "trustMode": locals().get("trust_mode"), "trustValue": locals().get("trust_value"),
            "complete": complete, "fieldErrors": local_errors,
            "status": "지출 비율 조합 확인 필요" if priority["targetAdjustmentStatus"] == "infeasible" else "입력 확인 · 배분 미완료" if not complete else "수입 0원 · 수익률 산정 불가" if priority["targetAdjustmentStatus"] == "zero-revenue" else "지출 설정 유지 · 목표 수익률 조정" if priority["targetAdjusted"] else "허용 예산 배분 완료",
            "note": "지출 입력 설정을 우선 유지한 허용 예산입니다. 독립 예상비용·현금흐름과 중복 합산하지 않습니다."}


def _apply_finance_price(inputs, result, kind, errors):
    """Source distributions stay unchanged; editor amounts are explicit assumptions."""
    result["comparableWon"] = result.get("representativeWon")
    editor = inputs.get("financeEditor") or {}
    edit = editor.get(kind)
    if edit is None:
        return result
    path = "financeEditor." + kind
    try:
        if not isinstance(edit, dict) or edit.get("mode") not in ("comparablePct", "amount"):
            raise ValueError("비교사례 비율 또는 직접 금액을 선택하세요.")
        mode = edit["mode"]
        value = number(edit.get("value"), "편집 금액·비율", minimum=0, maximum=200 if mode == "comparablePct" else None, required=True)
        base = result["comparableWon"]
        applied = value if mode == "amount" else base * (value / 100) if base is not None else None
        if applied is not None and not math.isfinite(applied): raise ValueError("금액 계산 범위를 초과했습니다.")
        result.update(representativeWon=applied, editMode=mode, editValue=value,
                      sourceStatus="사용자 가정" if mode == "amount" else "공개자료 기반 추정 · 사용자 비율 적용")
        if mode == "amount": result["status"] = "사용자 입력 금액 적용"
    except (ValueError, TypeError) as exc:
        _input_error(errors, kind, path + ".value", exc)
        result.update(representativeWon=None, status="입력 오류 · 계산 보류")
    if kind == "revenue":
        value = result["representativeWon"]
        assumptions = inputs.get("assumptions") or {}
        discount = number(assumptions.get("discountPct", 0), "할인율", minimum=0, maximum=100, required=True)
        final_sales = number(assumptions.get("finalSalesPct", 100), "최종 분양률", minimum=0, maximum=100, required=True)
        full_net = value * (1 - discount / 100) if value is not None else None
        result.update(potentialRevenueWon=value, fullNetRevenueWon=full_net,
                      netRevenueWon=full_net * (final_sales / 100) if full_net is not None else None)
    return result


def _costs(inputs, land, revenue, cashflow, warnings, errors=None):
    provided, groups = {}, defaultdict(list)
    for i, item in enumerate(inputs.get("costs", [])):
        if not isinstance(item, dict):
            _input_error(errors, "costs", f"costs.{i}", "비용 행은 객체여야 합니다.")
            item = {"id": f"invalid-cost-{i}", "category": "미분류", "amountWon": None}
        cid = str(item.get("id") or "")
        if not cid or cid in provided:
            _input_error(errors, "costs", f"costs.{i}.id", "비용 항목 ID는 비어 있지 않고 중복되지 않아야 합니다.")
            cid = f"invalid-cost-{i}"
            item = {**item, "amountWon": None}
        category = str(item.get("category") or item.get("id") or "미분류")
        row = {**item, "id": cid, "category": category,
               "label": item.get("label") or COST_LABELS.get(category, category)}
        try:
            row["amountWon"] = number(row.get("amountWon"), row["label"], minimum=0)
        except ValueError as exc:
            _input_error(errors, "costs", f"costs.{i}.amountWon", exc)
            row["amountWon"] = None
            row["validationError"] = str(exc)
        provided[cid] = row
        groups[category].append(row)
    for category in COST_LABELS:
        if not groups[category]:
            row = {"id": category, "category": category, "label": COST_LABELS[category], "amountWon": None}
            # A detail row's identifier can equal a different category name.
            while row["id"] in provided:
                row["id"] = "missing-" + row["id"]
            groups[category].append(row)
    land_rows = groups["land_purchase"]
    if len(land_rows) != 1:
        _input_error(errors, "costs", "costs", "토지 매입대금은 비교사례 산출액 한 행만 반영합니다. 토지 매입대금 상세 행을 중복 추가하지 마세요.")
        for row in land_rows:
            row["amountWon"] = None
    else:
        land_rows[0].update(amountWon=land["representativeWon"], sourceStatus="공개자료 기반 추정", calculationSource="land")
    finance_rows = groups["finance_trust"]
    if len(finance_rows) == 1 and finance_rows[0]["amountWon"] is None and not finance_rows[0].get("validationError") and cashflow.get("financeComplete"):
        summary = cashflow["summary"]
        finance_rows[0].update(amountWon=summary["interestWon"] + summary["lenderFeeWon"] + summary["trustFeeWon"],
                               sourceStatus="사용자 가정", calculationSource="cashflow")
    elif cashflow.get("financeComplete") and any(r["amountWon"] is not None for r in finance_rows):
        warnings.append("금융·신탁 비용은 수기 비용행 합계를 사용했습니다. 현금흐름 산출액을 다시 더하지 않았으며 두 근거의 범위를 확인하세요.")
    items, category_totals = [], {}
    for category, rows in groups.items():
        category_totals[category] = sum(r["amountWon"] for r in rows) if all(r["amountWon"] is not None for r in rows) else None
        for row in rows:
            amount = row["amountWon"]
            source = row.get("sourceStatus") or ("사용자 가정" if amount is not None else "미확보")
            if amount is None:
                source = "미확보"
            if source not in SOURCE_STATES:
                source = "사용자 가정" if amount is not None else "미확보"
            row["sourceStatus"] = source
            items.append(row)
    missing = [r["id"] for r in items if r["amountWon"] is None]
    subtotal = sum(r["amountWon"] for r in items if r["amountWon"] is not None)
    total = subtotal if not missing else None
    try:
        target = number(inputs.get("assumptions", {}).get("targetMarginPct"), "목표 이익률", minimum=0, maximum=100)
    except ValueError as exc:
        _input_error(errors, "costs", "assumptions.targetMarginPct", exc)
        target = None
    income = revenue["netRevenueWon"]
    allowable = income * (1 - target / 100) if income is not None and target is not None else None
    profit = income - total if income is not None and total is not None else None
    margin = profit / income * 100 if profit is not None and income > 0 else None
    gap = allowable - total if allowable is not None and total is not None else None
    if cashflow.get("summary") and not cashflow.get("financeComplete"):
        warnings.append("현금흐름의 금융·신탁 비용 범위가 완전하다고 확인되지 않아 비용표를 자동 완성하지 않았습니다.")
    return {"items": items, "categoryTotals": category_totals, "knownSubtotalWon": subtotal, "totalWon": total,
            "missingIds": missing, "allowableWon": allowable, "gapWon": gap,
            "profitWon": profit, "marginPct": margin, "targetMarginPct": target,
            "status": "계산 미완료" if total is None or income is None else ("해당 없음" if income == 0 else "시나리오 계산 완료")}
