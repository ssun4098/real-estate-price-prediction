"""현금흐름: 월별 수입·지출, 분양률 곡선, 대출 시뮬레이션.
"""
from __future__ import annotations

import copy
import datetime as dt
from collections import defaultdict

from server.domain.analysis.common import _input_error, date_value, number


def _empty_cashflow(missing, message="목표 미산출"):
    return {"status": "계산 미완료", "missing": missing, "rows": [], "summary": {},
            "exit": {"status": message, "requiredPct": None, "additionalRequiredPct": None,
                     "expectedPct": None, "marginPp": None}}


def _prepare_cashflow(raw, revenue, land):
    debt_mode = raw.get("debtMode", "pf")
    if debt_mode not in ("pf", "none"):
        raise ValueError("PF 차입 구분은 pf 또는 none이어야 합니다.")
    required = ["asOf", "endDate", "openingCashWon"]
    if debt_mode == "pf":
        required += ["openingDebtWon", "loanLimitWon", "annualRatePct", "maturityDate", "financingConfirmed", "autoDraw"]
    else:
        for field in ("openingDebtWon", "loanLimitWon"):
            if (number(raw.get(field), field, minimum=0) or 0) > 0:
                raise ValueError("PF 차입 없음 상태에서는 차입잔액·한도를 입력할 수 없습니다.")
        for event in raw.get("events", []):
            if event.get("kind") in ("loanDraw", "loanRepay", "fee") and any(
                    (number(event.get(field), field, minimum=0) or 0) > 0
                    for field in ("amountWon", "pctRevenue", "pctLand")):
                raise ValueError("PF 차입 없음 상태에서는 차입 인출·원금 상환·대주 수수료를 입력할 수 없습니다.")
    missing = [k for k in required if raw.get(k) is None or raw.get(k) == ""]
    if raw.get("scheduleComplete") is not True:
        missing.append("사업비·수납·조달 일정 범위 확인(scheduleComplete)")
    if missing:
        return None, missing
    cfg = copy.deepcopy(raw)
    cfg["debtMode"] = debt_mode
    cfg["asOf"] = date_value(raw["asOf"], "현금흐름 기준일")
    cfg["startDate"] = date_value(raw.get("startDate") or raw["asOf"], "현금흐름 시작일")
    cfg["endDate"] = date_value(raw["endDate"], "사업 정산일")
    cfg["maturityDate"] = date_value(raw["maturityDate"], "PF 만기일") if debt_mode == "pf" else cfg["endDate"]
    if cfg["startDate"] != cfg["asOf"]:
        raise ValueError("현금흐름 시작일은 기준일과 같아야 합니다. 기준일 잔액을 입력하세요.")
    if not cfg["asOf"] <= cfg["maturityDate"] <= cfg["endDate"]:
        raise ValueError("기준일 ≤ PF 만기일 ≤ 사업 정산일 순서여야 합니다.")
    if (cfg["endDate"] - cfg["asOf"]).days > 7305:
        raise ValueError("현금흐름 분석기간은 20년 이내로 설정하세요.")
    cfg["openingCashWon"] = number(raw["openingCashWon"], "기초 현금", minimum=0, required=True)
    for field in ("openingDebtWon", "loanLimitWon", "annualRatePct"):
        cfg[field] = number(raw[field], field, minimum=0, required=True) if debt_mode == "pf" else 0.
    if cfg["openingDebtWon"] > cfg["loanLimitWon"]:
        raise ValueError("기초 차입잔액이 총 차입한도를 초과합니다.")
    if debt_mode == "none":
        cfg["financingConfirmed"], cfg["autoDraw"] = False, False
    if not isinstance(cfg["financingConfirmed"], bool) or not isinstance(cfg["autoDraw"], bool):
        raise ValueError("조달 확정·자동 인출 여부는 true 또는 false여야 합니다.")
    cfg["interestDayBasis"] = number(raw.get("interestDayBasis", 365), "이자 일수 기준", required=True)
    if cfg["interestDayBasis"] not in (360, 365):
        raise ValueError("이자 일수 기준은 360 또는 365를 입력하세요.")
    cfg["interestPaymentDates"] = {date_value(d, "이자 지급일") for d in raw.get("interestPaymentDates", [])} if debt_mode == "pf" else set()
    cfg["interestPaymentDates"].update((cfg["maturityDate"], cfg["endDate"]))
    cfg["events"] = []
    allowed = {"salesReceipt", "land", "cost", "equity", "loanDraw", "loanRepay", "fee", "trustFee", "otherIn", "otherOut"}
    for i, event in enumerate(raw.get("events", [])):
        e = dict(event)
        e["id"] = str(e.get("id") or f"event-{i}")
        e["date"] = date_value(e.get("date"), "지급·수납일")
        if e.get("kind") not in allowed:
            raise ValueError(f"현금흐름 {e['id']}: 지원하지 않는 구분입니다.")
        if e.get("kind") == "salesReceipt" and e.get("contractDate") not in (None, ""):
            contracted = date_value(e["contractDate"], "분양 수납 계약일")
            if contracted > e["date"]:
                raise ValueError(f"cashflow.events.{i}.contractDate: 분양 수납일은 계약일보다 빠를 수 없습니다.")
        if e["date"] < cfg["asOf"]:
            if not e.get("actual"):
                raise ValueError("기준일 이전 거래는 실적으로 표시해야 합니다.")
            continue  # Already reflected in opening cash/debt; never double counted.
        if e["date"] > cfg["endDate"]:
            raise ValueError("정산일 이후 현금흐름이 있습니다. 정산일 또는 지급일을 수정하세요.")
        if e.get("actual") and e["date"] > cfg["asOf"]:
            raise ValueError("미래 거래를 실적으로 표시할 수 없습니다.")
        alternatives = [k for k in ("amountWon", "pctRevenue", "pctLand") if e.get(k) is not None and e.get(k) != ""]
        if len(alternatives) != 1:
            raise ValueError("현금흐름 행에는 금액·매출비율·토지대금비율 중 하나만 입력하세요.")
        field = alternatives[0]
        amount = number(e[field], field, minimum=0, required=True)
        if field != "amountWon":
            base = revenue if field == "pctRevenue" else land
            if base is None:
                missing.append("수납·지급 비율의 기준금액 미확보")
                continue
            amount = base * amount / 100
        e["amountWon"] = amount
        cfg["events"].append(e)
    land_pct = [e for e in raw.get("events", []) if e.get("kind") == "land" and e.get("pctLand") is not None]
    if land_pct and abs(sum(number(e["pctLand"], required=True) for e in land_pct) - 100) > .000001:
        raise ValueError("토지 계약금·중도금·잔금의 비율 합계는 100%여야 합니다.")
    trust = raw.get("trust")
    cfg["trustFeeWon"] = None
    if isinstance(trust, dict) and trust.get("notApplicable") is True:
        cfg["trustFeeWon"] = 0
    elif isinstance(trust, dict):
        basis = number(trust.get("basisWon"), "신탁보수 기준금액", minimum=0)
        rate = number(trust.get("ratePct"), "신탁보수율", minimum=0)
        if basis is not None and rate is not None:
            fee = basis * rate / 100
            if fee and any(e["kind"] == "trustFee" and e["amountWon"] > 0 for e in cfg["events"]):
                raise ValueError("신탁보수 자동 지급계획과 수기 신탁보수 지급을 동시에 반영할 수 없습니다.")
            payments = trust.get("paymentSchedule", [])
            if fee and (not payments or abs(sum(number(e.get("pct"), "신탁 지급 비율", minimum=0, required=True) for e in payments) - 100) > .000001):
                raise ValueError("신탁보수 지급 비율은 100%여야 합니다.")
            cfg["trustFeeWon"] = fee
            for i, payment in enumerate(payments):
                when = date_value(payment.get("date"), "신탁보수 지급일")
                if not cfg["asOf"] <= when <= cfg["endDate"]:
                    raise ValueError("신탁 지급일은 분석기간 안이어야 합니다.")
                cfg["events"].append({"id": f"trust-{i}", "kind": "trustFee", "date": when,
                                      "amountWon": fee * number(payment["pct"], required=True) / 100})
    if any(not cfg["asOf"] <= d <= cfg["endDate"] for d in cfg["interestPaymentDates"]):
        raise ValueError("이자 지급일이 분석기간 밖에 있습니다.")
    cfg["fullRevenueWon"] = revenue
    return (cfg if not missing else None), missing


def _sales_curve(cfg, raw_exit, future_pct):
    """Explicit future contract cohorts. One percentage point uses the same fixed price list."""
    if raw_exit is None:
        return [], []
    past = number(raw_exit.get("pastContractedPct"), "기준일 누적 계약률", minimum=0, maximum=100, required=True)
    future_pct = number(future_pct, "향후 추가 계약률", minimum=0, maximum=100 - past, required=True)
    curve = raw_exit.get("futureSalesCurve", [])
    if not curve and past < 100:
        raise ValueError("Exit 계산에는 잔여 판매 경로가 필요합니다.")
    if curve and abs(sum(number(c.get("sharePct"), "판매 경로 비중", minimum=0, required=True) for c in curve) - 100) > .000001:
        raise ValueError("향후 판매 경로 비중 합계는 100%여야 합니다.")
    events, contracts = [], []
    for i, cohort in enumerate(curve):
        contract_date = date_value(cohort.get("contractDate"), "향후 계약일")
        if contract_date <= cfg["asOf"]:
            raise ValueError("향후 계약일은 기준일 이후여야 합니다.")
        if contract_date > cfg["endDate"]:
            raise ValueError("계약일이 사업 정산일 이후입니다.")
        share = number(cohort["sharePct"], minimum=0, required=True)
        collections = cohort.get("collections", [])
        if not collections or abs(sum(number(c.get("pct"), "수납 비율", minimum=0, required=True) for c in collections) - 100) > .000001:
            raise ValueError("각 계약의 계약금·중도금·잔금 수납 비율 합계는 100%여야 합니다.")
        contracts.append({"date": contract_date, "pct": future_pct * share / 100})
        for j, item in enumerate(collections):
            receipt_date = date_value(item.get("date"), "분양 수납일")
            if not contract_date <= receipt_date <= cfg["endDate"]:
                raise ValueError("분양 수납일은 계약일 이후이고 정산일 이내여야 합니다.")
            if cfg["fullRevenueWon"] is None:
                raise ValueError("판매 경로 계산에 분양수입 기준금액이 필요합니다.")
            events.append({"id": f"future-{i}-{j}", "date": receipt_date, "kind": "salesReceipt",
                           "amountWon": cfg["fullRevenueWon"] * future_pct / 100 * share / 100 * number(item["pct"], minimum=0, required=True) / 100})
    return events, contracts


def _simulate(cfg, extra_events=(), include_rows=True):
    events = defaultdict(list)
    for e in list(cfg["events"]) + list(extra_events):
        events[e["date"]].append(e)
    dates = set(events) | cfg["interestPaymentDates"] | {cfg["asOf"], cfg["maturityDate"], cfg["endDate"]}
    cash, debt = cfg["openingCashWon"], cfg["openingDebtWon"]
    accrued, total_interest, paid_interest, lender_fee, trust_fee = 0., 0., 0., 0., 0.
    due = defaultdict(float)
    peak_debt, peak_gap, peak_13, peak_date, maturity_unpaid = debt, 0., 0., None, None
    last, rows = cfg["asOf"], []
    principal_arrears = 0.
    cumulative_receipts, cumulative_required = 0., 0.
    for date in sorted(dates):
        days = (date - last).days
        accrual = debt * cfg["annualRatePct"] / 100 * days / cfg["interestDayBasis"]
        accrued += accrual
        total_interest += accrual
        row = {"date": date.isoformat(), "inflowWon": 0., "outflowWon": 0., "salesReceiptWon": 0.,
               "landPaymentWon": 0., "costPaymentWon": 0., "equityWon": 0., "drawWon": 0.,
               "principalPaidWon": 0., "interestPaidWon": 0., "interestAccruedWon": accrual}
        requested_principal, external_in, requested_draw = 0., 0., 0.
        for e in events[date]:
            kind, amount = e["kind"], e["amountWon"]
            if kind in ("salesReceipt", "equity", "otherIn"):
                cash += amount
                external_in += amount
                row["inflowWon"] += amount
                if kind == "salesReceipt":
                    row["salesReceiptWon"] += amount
                    cumulative_receipts += amount
                if kind == "equity":
                    row["equityWon"] += amount
            elif kind == "loanDraw":
                requested_draw += amount
            elif kind == "loanRepay":
                requested_principal += amount
            else:
                due[kind] += amount
                if kind == "fee":
                    lender_fee += amount
                elif kind == "trustFee":
                    trust_fee += amount
        if date in cfg["interestPaymentDates"]:
            due["interest"] += accrued
            accrued = 0.
        if requested_draw > 0 and cfg["financingConfirmed"] and date < cfg["maturityDate"]:
            draw = min(requested_draw, max(0., cfg["loanLimitWon"] - debt))
            debt += draw
            cash += draw
            row["drawWon"] += draw
        nonprincipal_due = sum(due.values())
        principal_due = debt if date >= cfg["maturityDate"] else min(debt, requested_principal + principal_arrears)
        # No unconfirmed refinancing and no borrowing from the same matured PF.
        # Automatic borrowing funds operating/interest payments, never rolls an
        # early principal repayment into another draw of the same loan.
        need = max(0., nonprincipal_due - cash)
        if need and cfg["autoDraw"] and cfg["financingConfirmed"] and date < cfg["maturityDate"]:
            draw = min(need, max(0., cfg["loanLimitWon"] - debt))
            debt += draw
            cash += draw
            row["drawWon"] += draw
        peak_debt = max(peak_debt, debt)
        gap = max(0., nonprincipal_due + principal_due - cash)
        cumulative_required = max(cumulative_required, max(0., cumulative_receipts + nonprincipal_due + principal_due - cash))
        if gap > peak_gap:
            peak_gap, peak_date = gap, date.isoformat()
        if date <= cfg["asOf"] + dt.timedelta(weeks=13):
            peak_13 = max(peak_13, gap)
        # Explicit waterfall: operating payments, fees, interest, then principal.
        for kind in ("land", "cost", "otherOut", "fee", "trustFee", "interest"):
            paid = min(cash, due[kind])
            cash -= paid
            due[kind] -= paid
            row["outflowWon"] += paid
            if kind == "land":
                row["landPaymentWon"] += paid
            elif kind == "interest":
                row["interestPaidWon"] += paid
                paid_interest += paid
            else:
                row["costPaymentWon"] += paid
        principal_paid = min(cash, principal_due, debt)
        cash -= principal_paid
        debt -= principal_paid
        row["principalPaidWon"] = principal_paid
        row["outflowWon"] += principal_paid
        principal_arrears = max(0., principal_due - principal_paid)
        unpaid = sum(due.values()) + max(0., principal_due - principal_paid)
        if date == cfg["maturityDate"]:
            maturity_unpaid = debt + due["interest"] + accrued
        row.update(debtWon=debt, cashWon=cash, unfundedWon=gap, unpaidWon=unpaid,
                   cumulativeSalesReceiptWon=cumulative_receipts, requiredSalesReceiptWon=cumulative_required,
                   principalOverdueWon=debt if date >= cfg["maturityDate"] else max(0., principal_due - principal_paid),
                   unpaidOperatingWon=sum(v for k, v in due.items() if k != "interest"))
        if include_rows:
            rows.append(row)
        last = date
    return {"rows": rows, "summary": {"interestWon": total_interest, "interestPaidWon": paid_interest,
            "lenderFeeWon": lender_fee, "trustFeeWon": trust_fee, "maxDebtWon": peak_debt,
            "maxUnfundedWon": peak_gap, "maxUnfundedDate": peak_date, "maxUnfunded13WeeksWon": peak_13,
            "maturityUnpaidWon": maturity_unpaid, "finalCashWon": cash, "finalDebtWon": debt,
            "finalUnpaidWon": sum(due.values()) + debt, "totalSalesReceiptWon": cumulative_receipts}}


def calculate_cashflow(raw, full_revenue_won=None, land_won=None):
    if not isinstance(raw, dict):
        return _empty_cashflow(["판매·수납·지급·차입 일정"])
    cfg, missing = _prepare_cashflow(raw, full_revenue_won, land_won)
    if cfg is None:
        result = _empty_cashflow(missing)
        result["debtMode"] = raw.get("debtMode", "pf")
        if result["debtMode"] == "none":
            result["exit"].update(status="해당 없음", reason="PF 차입 없음")
        return result
    exit_cfg = raw.get("exit")
    if isinstance(exit_cfg, dict) and not exit_cfg.get("futureSalesCurve") and all(
            exit_cfg.get(field) in (None, "") for field in ("pastContractedPct", "expectedFutureContractedPct")):
        exit_cfg = None  # An untouched optional editor is not an assumed sales path.
    extra, contracts = [], []
    exit_result = {"status": "목표 미산출", "requiredPct": None, "additionalRequiredPct": None,
                   "expectedPct": None, "marginPp": None}
    if isinstance(exit_cfg, dict) and full_revenue_won is not None:
        future = number(exit_cfg.get("expectedFutureContractedPct"), "예상 추가 계약률", minimum=0, required=True)
        extra, contracts = _sales_curve(cfg, exit_cfg, future)
    result = _simulate(cfg, extra)
    if cfg["debtMode"] == "none":
        exit_result.update(status="해당 없음", reason="PF 차입 없음")
        result["summary"]["maturityUnpaidWon"] = None
    elif isinstance(exit_cfg, dict) and full_revenue_won is not None:
        past = number(exit_cfg["pastContractedPct"], minimum=0, maximum=100, required=True)
        expected = past + sum(c["pct"] for c in contracts if c["date"] <= cfg["maturityDate"])
        upper = 100 - past
        def run(amount):
            ev, ct = _sales_curve(cfg, exit_cfg, amount)
            return _simulate(cfg, ev, False), ct
        high, _ = run(upper)
        if high["summary"]["maturityUnpaidWon"] > .5:
            exit_result.update(status="현재 조건에서 상환 불가", expectedPct=expected)
        else:
            low_result, _ = run(0.)
            if low_result["summary"]["maturityUnpaidWon"] <= .5:
                answer = 0.
            else:
                lo, hi = 0., upper
                for _ in range(55):
                    mid = (lo + hi) / 2
                    trial, _ = run(mid)
                    if trial["summary"]["maturityUnpaidWon"] <= .5:
                        hi = mid
                    else:
                        lo = mid
                answer = hi
            threshold, necessary_contracts = run(answer)
            additional = sum(c["pct"] for c in necessary_contracts if c["date"] <= cfg["maturityDate"])
            required_pct = past + additional
            exit_result.update(status="조건부 추정", requiredPct=required_pct,
                               additionalRequiredPct=additional, futurePathScalePct=answer,
                               expectedPct=expected, marginPp=expected - required_pct,
                               fundingGapAtExitWon=threshold["summary"]["maxUnfundedWon"])
    result.update(status="시나리오 계산 완료", missing=[], exit=exit_result,
                  debtMode=cfg["debtMode"],
                  financeComplete=raw.get("financeComplete") is True and cfg["trustFeeWon"] is not None,
                  assumption="기준일 잔액 고정. 실제 경과일 단리. 영업지급→수수료→이자→원금 순서. 만기 이후 신규 PF 인출 없음.",
                  basisDate=cfg["asOf"].isoformat(), pastActualCount=sum(1 for e in raw.get("events", []) if e.get("actual") and str(e.get("date")) < cfg["asOf"].isoformat()))
    return result


def _cashflow_scalar_errors(raw, errors):
    """Report malformed entered fields even while other required fields are blank."""
    if not isinstance(raw, dict):
        return
    def numeric(record, fields, path):
        for field, maximum in fields:
            if record.get(field) not in (None, ""):
                try:
                    number(record[field], field, minimum=0, maximum=maximum)
                except ValueError as exc:
                    _input_error(errors, "cashflow", path + "." + field, exc)
    def dates(record, fields, path):
        for field in fields:
            if record.get(field) not in (None, ""):
                try:
                    date_value(record[field], field)
                except ValueError as exc:
                    _input_error(errors, "cashflow", path + "." + field, exc)
    numeric(raw, [(k, None) for k in ("openingCashWon", "openingDebtWon", "loanLimitWon")], "cashflow")
    dates(raw, ("asOf", "startDate", "endDate"), "cashflow")
    if raw.get("debtMode", "pf") != "none":
        numeric(raw, [("annualRatePct", None), ("interestDayBasis", None)], "cashflow")
        dates(raw, ("maturityDate",), "cashflow")
    for i, event in enumerate(raw.get("events", []) if isinstance(raw.get("events", []), list) else []):
        if isinstance(event, dict):
            numeric(event, [("amountWon", None), ("pctRevenue", None), ("pctLand", 100)], f"cashflow.events.{i}")
            dates(event, ("date",), f"cashflow.events.{i}")
            if event.get("kind") == "salesReceipt":
                dates(event, ("contractDate",), f"cashflow.events.{i}")
                if event.get("date") and event.get("contractDate"):
                    try:
                        receipt_date, contract_date = date_value(event["date"]), date_value(event["contractDate"])
                        if receipt_date < contract_date:
                            _input_error(errors, "cashflow", f"cashflow.events.{i}.contractDate", "분양 수납일은 계약일보다 빠를 수 없습니다.")
                    except ValueError:
                        pass  # Invalid date fields were reported individually above.
    trust = raw.get("trust")
    if isinstance(trust, dict) and not trust.get("notApplicable"):
        numeric(trust, [("basisWon", None), ("ratePct", None)], "cashflow.trust")
        for i, payment in enumerate(trust.get("paymentSchedule", []) if isinstance(trust.get("paymentSchedule", []), list) else []):
            if isinstance(payment, dict):
                numeric(payment, [("pct", 100)], f"cashflow.trust.paymentSchedule.{i}")
                dates(payment, ("date",), f"cashflow.trust.paymentSchedule.{i}")
    exit_cfg = raw.get("exit")
    if isinstance(exit_cfg, dict):
        numeric(exit_cfg, [("pastContractedPct", 100), ("expectedFutureContractedPct", 100)], "cashflow.exit")
        for i, cohort in enumerate(exit_cfg.get("futureSalesCurve", []) if isinstance(exit_cfg.get("futureSalesCurve", []), list) else []):
            if not isinstance(cohort, dict):
                continue
            path = f"cashflow.exit.futureSalesCurve.{i}"
            numeric(cohort, [("sharePct", 100)], path)
            dates(cohort, ("contractDate",), path)
            for j, payment in enumerate(cohort.get("collections", []) if isinstance(cohort.get("collections", []), list) else []):
                if isinstance(payment, dict):
                    numeric(payment, [("pct", 100)], path + f".collections.{j}")
                    dates(payment, ("date",), path + f".collections.{j}")
