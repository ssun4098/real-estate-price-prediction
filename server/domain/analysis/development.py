"""개발 규모: 대지면적·용적률·건폐율로 연면적·공급 세대수 계산.
"""
from __future__ import annotations

import copy
import math
from collections import defaultdict

from server.domain.analysis.common import _input_error, number, statistics


def _development(inputs, warnings):
    unique = {}
    for parcel in inputs.get("parcels", []):
        pnu = str(parcel.get("pnu") or "")
        if not pnu:
            raise ValueError("선택 필지에 PNU가 필요합니다.")
        if pnu in unique:
            warnings.append(f"중복 필지 {pnu}는 면적에 한 번만 반영했습니다.")
            continue
        unique[pnu] = parcel
    known, missing, groups = 0.0, 0, defaultdict(lambda: {"areaM2": 0.0, "missing": 0})
    for parcel in unique.values():
        area = number(parcel.get("areaM2"), "필지 대장 면적", minimum=0)
        group = str(parcel.get("group") or "기본")
        if area is None or area <= 0:
            missing += 1
            groups[group]["missing"] += 1
        else:
            known += area
            groups[group]["areaM2"] += area
    total_units, supply, far_area, plan_missing, far_missing = 0, 0.0, 0.0, False, False
    for row in inputs.get("unitPlan", []):
        count = number(row.get("units"), "계획 호수", minimum=0)
        area = number(row.get("supplyAreaM2"), "호당 공급면적", minimum=0)
        far = number(row.get("farAreaM2"), "호당 용적률 배분면적", minimum=0)
        if count is not None and not count.is_integer():
            raise ValueError("계획 호수는 음이 아닌 정수여야 합니다.")
        if count is None or (count > 0 and (area is None or area <= 0)):
            plan_missing = True
            continue
        total_units += int(count)
        supply += count * (area or 0)
        if count and far is None:
            far_missing = True
        else:
            far_area += count * (far or 0)
    assumptions = inputs.get("assumptions", {})
    far_base = number(assumptions.get("farBaseAreaM2"), "용적률 기준 대지면적", minimum=0)
    far_pct = number(assumptions.get("farPct"), "용적률", minimum=0)
    limit = far_base * far_pct / 100 if far_base is not None and far_pct is not None else None
    planned = far_area if inputs.get("unitPlan") and not far_missing and not plan_missing else None
    status = "미확인"
    if planned is not None and limit is not None:
        status = "제약 위반" if planned > limit + .000001 else "사용자 가정"
    if status == "제약 위반":
        warnings.append("계획 용적률 배분면적이 검토한 한도를 초과합니다. 수입은 미승인 공급계획 시나리오입니다.")
    if limit is None or planned is None:
        warnings.append("용적률·배치·주차 등 개발규모 검토가 완료되지 않았습니다.")
    return {"landAreaM2": known if unique and missing == 0 else None,
            "knownLandAreaM2": known, "missingParcelCount": missing, "parcelCount": len(unique),
            "supplyAreaM2": supply if inputs.get("unitPlan") and not plan_missing and supply > 0 else None,
            "units": total_units if not plan_missing else None, "farLimitAreaM2": limit,
            "plannedFarAreaM2": planned, "status": status, "landGroups": dict(groups)}


def _linked_development(inputs, development, revenue, errors):
    """Apply the explicit simplified linked scenario without rewriting unitPlan.

    Tolerance matches revision-model.mjs: it protects a mathematically integral
    fit against floating-point noise, not an extra dwelling's worth of area.
    """
    config = inputs.get("linkedScenario") or {}
    enabled = config.get("enabled") is True
    area_points = [{"id": p["id"], "label": p["label"], "valueM2": p["medianSupplyAreaM2"],
                    "caseIds": p["caseIds"]} for p in revenue["points"]]
    area_stats = statistics([p["valueM2"] for p in area_points])
    development.update(linkedMode=enabled, areaPoints=area_points, areaStats=area_stats)
    result = {"enabled": enabled, "fieldErrors": [], "status": "기존 수기 공급계획",
              "medianSupplyAreaM2": area_stats["median"], "supplyAreaStats": area_stats}
    if not enabled:
        return result
    local_errors = result["fieldErrors"]
    def error(path, value, reason, action):
        message = f"{value if value not in (None, '') else '미입력'} → {reason} → {action}"
        item = {"section": "linkedScenario", "path": path, "message": message}
        local_errors.append(item)
        if errors is not None:
            errors.append(item)
    def numeric(name, label, default=None, minimum=0, maximum=None):
        value = config.get(name, default)
        try:
            return number(value, label, minimum=minimum, maximum=maximum, required=True)
        except ValueError:
            rule = f"{minimum} 이상" + (f" {maximum} 이하" if maximum is not None else "")
            error("linkedScenario." + name, value, label + "이 없거나 허용 범위를 벗어났습니다", rule + "의 숫자로 수정하세요")
            return None
    default_far = numeric("farDefaultPct", "기본 용적률", 200)
    maximum_far = numeric("farMaxPct", "최대 용적률", 500)
    far = numeric("farPct", "현재 용적률", 200)
    if maximum_far is not None and maximum_far <= 0:
        error("linkedScenario.farMaxPct", maximum_far, "슬라이더 최대값은 0보다 커야 합니다", "최대 용적률을 양수로 수정하세요")
    for key, value, label in (("farDefaultPct", default_far, "기본 용적률"), ("farPct", far, "현재 용적률")):
        if value is not None and maximum_far is not None and value > maximum_far:
            error("linkedScenario." + key, value, label + "이 설정한 최대 용적률을 초과합니다", "값을 낮추거나 최대 용적률을 수정하세요")
    land_area = development["landAreaM2"]
    if land_area is None or land_area <= 0:
        error("parcels", land_area, "선택 필지의 확인 면적을 모두 확보하지 못했습니다", "02-A에서 필지를 선택하고 각 확인 면적을 입력하세요")
    mode = config.get("areaMode", "median")
    area = None
    if mode == "median":
        area = area_stats["median"]
        if area is None:
            error("linkedScenario.supplyAreaM2", None, "적합 분양사례가 없어 기본 공급면적 중앙값을 산출할 수 없습니다", "비교조건을 바꾸어 재조회하거나 수기 면적 모드에서 양수 면적을 입력하세요")
    elif mode == "manual":
        area = numeric("supplyAreaM2", "호당 공급면적")
        if area is not None and area <= 0:
            error("linkedScenario.supplyAreaM2", area, "호당 공급면적은 0보다 커야 합니다", "양수 공급면적을 입력하세요")
    else:
        error("linkedScenario.areaMode", mode, "지원하지 않는 공급면적 입력 방식입니다", "중앙값 또는 수기 입력을 선택하세요")
    # Capacity depends on the parcel area and FAR, independently of the supply
    # area sample. Missing unit-area evidence holds units and assigned area only.
    # A malformed FAR default or range still holds capacity without clamping.
    capacity = units = assigned = remainder = per_far = None
    if not any(e["path"] == "parcels" or e["path"].startswith("linkedScenario.far") for e in local_errors):
        capacity = land_area * (far / 100)
        if not math.isfinite(capacity):
            error("linkedScenario.farPct", far, "면적 계산이 안전한 숫자 범위를 초과합니다", "용적률·대지면적과 입력 단위를 확인하여 수정하세요")
            capacity = None
    if capacity is not None and not local_errors:
        raw_units = capacity / area
        if not math.isfinite(capacity) or not math.isfinite(raw_units) or raw_units > 2 ** 53 - 1:
            error("linkedScenario.farPct", far, "면적·호수 계산이 안전한 숫자 범위를 초과합니다", "용적률·대지면적·호당 면적과 입력 단위를 확인하여 현실적인 값으로 수정하세요")
            capacity = None
        else:
            tolerance = max(1e-8, abs(capacity) * 1e-12)
            units = math.floor(raw_units + .5)
            if units * area > capacity + tolerance:
                units = math.floor((capacity + tolerance) / area)
            if units > 2 ** 53 - 1 or not math.isfinite(units * area):
                error("linkedScenario.farPct", far, "분양 호수·배정 면적이 안전한 숫자 범위를 초과합니다", "용적률·면적과 입력 단위를 확인하여 수정하세요")
                capacity = units = None
            else:
                assigned = units * area
                remainder = max(0.0, capacity - assigned)
                per_far = capacity / units if units > 0 else None
    development.update(capacitySupplyAreaM2=capacity, assignedSupplyAreaM2=assigned,
                       unassignedSupplyAreaM2=remainder, supplyAreaM2=assigned, units=units,
                       unitSupplyAreaM2=area, farAreaPerUnitM2=per_far,
                       farLimitAreaM2=capacity, plannedFarAreaM2=capacity,
                       status="입력 오류 · 연동 계산 보류" if local_errors else "용적률 연동 간이 가정")
    result.update(farDefaultPct=default_far, farMaxPct=maximum_far, farPct=far, areaMode=mode,
                  landAreaM2=land_area, capacityAreaM2=capacity, supplyAreaM2=area,
                  units=units, assignedSupplyAreaM2=assigned, unallocatedAreaM2=remainder,
                  farAreaPerUnitM2=per_far, status=development["status"])
    return result


def _partial_development(inputs, warnings, errors):
    """Parcel area and supply are separate dependencies; preserve valid siblings."""
    working = copy.deepcopy(inputs)
    for name, fields in (("parcels", ("areaM2",)), ("unitPlan", ("units", "supplyAreaM2", "farAreaM2"))):
        for i, row in enumerate(working.get(name, [])):
            if not isinstance(row, dict):
                _input_error(errors, "development", f"{name}.{i}", "행은 객체여야 합니다.")
                working[name][i] = {"pnu": f"invalid-{i}", "areaM2": None} if name == "parcels" else {"units": None}
                continue
            if name == "parcels" and not row.get("pnu"):
                _input_error(errors, "development", f"parcels.{i}.pnu", "선택 필지에 PNU가 필요합니다.")
                row.update(pnu=f"invalid-{i}", areaM2=None)
            for field in fields:
                try:
                    value = number(row.get(field), field, minimum=0)
                    if field == "units" and value is not None and not value.is_integer():
                        raise ValueError("계획 호수는 음이 아닌 정수여야 합니다.")
                except ValueError as exc:
                    _input_error(errors, "development", f"{name}.{i}.{field}", exc)
                    row[field] = None
    for field in ("farBaseAreaM2", "farPct"):
        try:
            number(working.get("assumptions", {}).get(field), field, minimum=0)
        except ValueError as exc:
            _input_error(errors, "development", "assumptions." + field, exc)
            working.setdefault("assumptions", {})[field] = None
    return _development(working, warnings)
