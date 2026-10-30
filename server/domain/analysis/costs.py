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


# 수지분석 지출 항목 기본값 (2026-10-29 요청). 목표 수익률은 입력하지 않고 총수입·총지출에서 계산한다.
#   허용 공사비 = 계획 공급면적 ÷ 3.3 × 평당 1,000만원
#   간접공사비 7% · 분양제비용 6% · 제세공과금 5% · 금융비용 6.5% = 허용 공사비 대비, 신탁보수 1% = 예상 총수입 대비
PYEONG_M2 = 3.3
EXPENSE_DEFAULTS = {"construction": ("areaUnit", 1000), "indirect": ("constructionPct", 7),
                    "sales": ("constructionPct", 6), "tax": ("constructionPct", 5),
                    "finance": ("constructionPct", 6.5), "trust": ("revenuePct", 1)}
# 입력 방식: 금액(원) / 수입%(예상 총수입 대비) / 지출%(예상 총지출 대비) / 공사비%(허용 공사비 대비) / 평당(만원, 공사비만)
EXPENSE_MODES = ("amount", "revenuePct", "budgetPct", "constructionPct", "areaUnit")


def _expense_priority_basis(income, land_won, supply_m2, rows, ready):
    """총지출과 목표 수익률을 지출 항목 계산식으로 구한다.

    총지출 T = 토지비 + 각 항목.  공사비%는 허용 공사비를, 지출%는 T 자신을 기준으로 하므로
    T = (토지비 + 금액·수입%·평당 항목 + 공사비% 몫) ÷ (1 − 지출% 합계) 로 한 번에 풀린다.
    목표 수익률 = (총수입 − T) ÷ 총수입 × 100 (토지비가 크면 음수일 수 있다).
    Browser counterpart: budget-priority.mjs / expensePriorityBasis.
    """
    result = {"requestedTargetMarginPct": None, "appliedTargetMarginPct": None,
              "requestedAllowableWon": None, "allowableWon": None, "totalExpenseWon": None,
              "constructionWon": None, "supplyAreaM2": supply_m2, "rowAmounts": {},
              "minimumRequiredBudgetWon": None, "fixedExpenseWon": None,
              "budgetExpensePct": None, "targetAdjusted": False,
              "targetAdjustmentStatus": "pending", "adjustmentError": None}
    def direct(row):  # 총지출과 관계없이 정해지는 금액 (근거가 없으면 None)
        mode, value = row.get("mode"), row.get("value")
        if value is None:
            return None
        if mode == "amount":
            return value
        if mode == "revenuePct":
            return income * (value / 100) if income is not None else None
        if mode == "areaUnit":
            return supply_m2 / PYEONG_M2 * value * 10_000 if supply_m2 is not None and supply_m2 >= 0 else None
        return None
    construction = next(r for r in rows if r["id"] == "construction")
    if not ready:
        # 입력이 덜 됐어도 다른 항목에 의존하지 않는 금액은 보여 준다 (지출%는 총지출이 필요해 보류).
        known = direct(construction)
        partial = {r["id"]: (known * r["value"] / 100 if r.get("mode") == "constructionPct" and known is not None and r.get("value") is not None
                             else direct(r)) for r in rows}
        return dict(result, rowAmounts={k: v for k, v in partial.items() if v is not None and math.isfinite(v)})
    def fail(status, message):
        return dict(result, targetAdjustmentStatus=status, adjustmentError=message)
    if construction["mode"] == "areaUnit" and (supply_m2 is None or supply_m2 < 0):
        return fail("missing-supply", "계획 공급면적이 없어 평당 공사비를 계산할 수 없습니다. 개발규모의 공급계획(호수·호당 면적)을 확인하세요.")
    share = sum(r["value"] for r in rows if r["mode"] == "budgetPct") / 100
    construction_share = sum(r["value"] for r in rows if r["mode"] == "constructionPct") / 100
    fixed = land_won + sum(direct(r) for r in rows if r["mode"] in ("amount", "revenuePct", "areaUnit"))
    if construction["mode"] == "budgetPct":
        share += construction_share * construction["value"] / 100
    else:
        fixed += construction_share * direct(construction)
    result.update(fixedExpenseWon=fixed if math.isfinite(fixed) else None, budgetExpensePct=share * 100)
    if not math.isfinite(fixed):
        return fail("overflow", "지출 합계가 계산 범위를 초과했습니다. 금액·비율의 입력 단위를 확인하세요.")
    if share >= 1 and (fixed > 0 or share > 1):
        return fail("infeasible", "지출% 합계가 100% 이상이어서 토지비와 다른 지출을 함께 충당할 수 없습니다. 지출 비율 또는 입력 기준을 확인하세요.")
    total = fixed / (1 - share) if share < 1 else 0.0
    construction_won = total * construction["value"] / 100 if construction["mode"] == "budgetPct" else direct(construction)
    amounts = {}
    for row in rows:
        mode, value = row["mode"], row["value"]
        amounts[row["id"]] = (total * value / 100 if mode == "budgetPct"
                              else construction_won * value / 100 if mode == "constructionPct" else direct(row))
    # 목표 수익률 = (예상 총수입 ÷ 예상 총지출 × 100) − 100 (2026-10-30 사용자 요청; 0% = 손익분기, 음수 = 적자). 브라우저 budget-priority.mjs 와 같은 식.
    margin = income / total * 100 - 100 if income > 0 and total > 0 else None
    if not math.isfinite(total) or not all(math.isfinite(v) for v in amounts.values()) or (margin is not None and not math.isfinite(margin)):
        return fail("overflow", "지출 합계가 계산 범위를 초과했습니다. 입력 금액과 지출 비율을 확인하세요.")
    result.update(allowableWon=total, totalExpenseWon=total, minimumRequiredBudgetWon=total,
                  constructionWon=construction_won, rowAmounts=amounts, appliedTargetMarginPct=margin,
                  targetAdjustmentStatus="zero-revenue" if income == 0 else "computed")
    return result


def _budget_allocation(inputs, revenue, land, errors, development=None):
    """수지분석 표: 지출 항목 계산식 → 총지출 → 목표 수익률. 독립 예상비용·현금흐름과 합치지 않는다."""
    config = inputs.get("budgetAllocation") or {}
    fields = (("construction", "공사비"), ("indirect", "간접 공사비"),
              ("sales", "분양제비용"), ("tax", "제세공과금"), ("finance", "금융비용"))
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
            error(path, value, label + "이 없거나 허용 범위를 벗어났습니다", f"{minimum}~{maximum if maximum is not None else ''} 범위의 숫자로 수정하세요")
            return None
    income = revenue["representativeWon"]
    supply = (development or {}).get("supplyAreaM2")
    expense_edits = (inputs.get("financeEditor") or {}).get("expenses") or {}
    if not isinstance(expense_edits, dict):
        error("financeEditor.expenses", expense_edits, "비용 편집 항목은 객체여야 합니다", "비용 입력 형식을 확인하세요")
        expense_edits = {}
    def expense_value(key, default_mode, default_value, label):
        edit = expense_edits.get(key, {"mode": default_mode, "value": default_value})
        path = "financeEditor.expenses." + key
        value_path = path + ".value" if key in expense_edits else "budgetAllocation." + ("trustRatePct" if key == "trust" else key)
        allowed = ("amount", "revenuePct", "budgetPct", "areaUnit") if key == "construction" else ("amount", "revenuePct", "budgetPct", "constructionPct")
        if not isinstance(edit, dict) or edit.get("mode") not in allowed:
            error(path, edit, "지원하지 않는 비용 입력 방식입니다", "평당·공사비%·지출%·수입%·금액 중 선택하세요")
            return None, None
        mode = edit["mode"]
        value = numeric(edit.get("value"), value_path, label, maximum=None if mode in ("amount", "areaUnit") else 100)
        return mode, value
    rows = []
    for key, label in fields:
        mode, value = expense_value(key, *EXPENSE_DEFAULTS[key], label)
        rows.append({"id": key, "label": "허용 " + label, "pct": value if mode == "budgetPct" else None,
                     "mode": mode, "value": value, "amountWon": None})
    trust_type = config.get("trustType", "")
    if trust_type is None:
        trust_type = ""
    trust_mode = trust_value = trust_rate = trust_won = None
    # An unselected product can use the user's 1% budget assumption; this does
    # not choose a trust contract or change the separate cash-flow fee schedule.
    if trust_type in ("", "management", "completion"):
        default_rate = config.get("trustRatePct")
        if default_rate is None or isinstance(default_rate, str) and not default_rate.strip():
            default_rate = EXPENSE_DEFAULTS["trust"][1]
        trust_mode, trust_value = expense_value("trust", "revenuePct", default_rate, "참고 신탁보수")
        trust_rate = trust_value if trust_mode == "revenuePct" else None
    elif trust_type == "distribution":
        error("budgetAllocation.trustType", "분양관리신탁", "순수 아파트 사업에 단일 매출액 요율을 적용할 수 없습니다", "적용 대상·보수 조건을 확인하세요. 관리형 상품을 검토하거나 조건 확정 전에는 신탁보수 산출을 보류하세요")
    else:
        error("budgetAllocation.trustType", trust_type, "지원하지 않는 신탁상품입니다", "상품 미선택의 사용자 가정 또는 지원하는 신탁상품을 선택하세요")
    trust_row = {"id": "trust", "mode": trust_mode, "value": trust_value}
    all_rows = rows + [trust_row]
    ready = (not local_errors and income is not None and income >= 0
             and land.get("representativeWon") is not None and land["representativeWon"] >= 0
             and all(r.get("value") is not None for r in all_rows))
    priority = _expense_priority_basis(income, land.get("representativeWon"), supply, all_rows, ready)
    if priority["adjustmentError"]:
        error("financeEditor.expenses", "지출 설정", priority["adjustmentError"], "지출 입력 기준·금액·비율과 공급계획을 확인하세요")
    amounts = priority.pop("rowAmounts")
    for row in rows:
        row["amountWon"] = amounts.get(row["id"])
    trust_won = amounts.get("trust")
    total = priority["totalExpenseWon"]
    complete = total is not None and not local_errors
    margin = priority["appliedTargetMarginPct"]
    total_pct = sum(r["pct"] for r in rows) if all(r["pct"] is not None for r in rows) else None
    status = ("지출 비율 조합 확인 필요" if priority["targetAdjustmentStatus"] == "infeasible"
              else "공급계획 확인 필요" if priority["targetAdjustmentStatus"] == "missing-supply"
              else "입력 확인 · 계산 미완료" if not complete
              else "수입 0원 · 수익률 산정 불가" if priority["targetAdjustmentStatus"] == "zero-revenue"
              else "수지 계산 완료 · 목표 수익률 자동 산정")
    return {"revenueWon": income, **priority, "targetMarginPct": margin,
            "landWon": land["representativeWon"], "trustWon": trust_won,
            "trustType": trust_type, "trustRatePct": trust_rate,
            "trustRateSource": "사용자 예산 가정 · 기본 총수입의 1% · 계약 확정 아님" if trust_rate is not None else None,
            "allocationRows": rows, "allocationPctTotal": total_pct,
            "knownAllocatedWon": total, "allocatedWon": total if complete else None,
            "unallocatedWon": 0 if complete else None, "overallocatedWon": 0 if complete else None,
            "profitWon": income - total if complete and income is not None else None,
            "profitMarginPct": margin if complete else None,
            "trustMode": trust_mode, "trustValue": trust_value,
            "complete": complete, "fieldErrors": local_errors, "status": status,
            "note": "지출 항목 계산식으로 총지출을 구하고 목표 수익률=(총수입−총지출)÷총수입으로 산정합니다. 독립 예상비용·현금흐름과 중복 합산하지 않습니다."}


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
