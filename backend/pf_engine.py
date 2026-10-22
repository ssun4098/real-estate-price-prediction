"""PF Study calculation engine. KRW, square metres and dated cash flows only.

No network, credentials or undocumented business defaults. A null is unknown;
an explicitly entered zero is a valid assumption. Source inputs are retained.
"""
from __future__ import annotations

import copy
import datetime as dt
import json
import math
import re
import uuid
from collections import defaultdict
from urllib.parse import parse_qsl, urlsplit
from pf_land import calculate_land, parcel_profile

VERSION = "pf-study-5"
WON_PER_MANWON = 10000
COST_LABELS = {
    "land_purchase": "토지 매입대금", "land_extra": "토지 취득 부대비용",
    "construction": "본 도급공사비", "separate_construction": "별도 공사비",
    "professional": "설계·감리·사업관리비", "tax_guarantee": "세금·부담금·보증료",
    "marketing_operating": "분양·광고·운영비", "finance_trust": "금융비·신탁보수",
    "contingency": "예비비",
}
SOURCE_STATES = {"실적", "계약", "공개자료 기반 추정", "사용자 가정", "미확보"}
SECRET_FIELDS = {"key", "apikey", "servicekey", "confmkey", "authorization", "password", "secret", "token", "accesskey", "vworldapikey", "datagokrapikey", "jusoapikey", "vworldgeocoderapikey", "vworldsearchapikey", "kosisapikey", "consumerkey", "consumersecret", "accesstoken", "sgissecret"}
# V2 permits official land price as survey reference metadata only. None of the
# revenue/land/cost calculations reads it or substitutes it for market price.
EXCLUDED_PRICE_FIELDS = set()


def number(value, label="값", minimum=None, maximum=None, required=False):
    if value is None or value == "":
        if required:
            raise ValueError(f"{label}: 값이 필요합니다.")
        return None
    if isinstance(value, bool):
        raise ValueError(f"{label}: 숫자를 입력하세요.")
    try:
        n = float(str(value).replace(",", "").strip())
    except (ValueError, TypeError):
        raise ValueError(f"{label}: 숫자를 입력하세요.") from None
    if not math.isfinite(n) or (minimum is not None and n < minimum) or (maximum is not None and n > maximum):
        raise ValueError(f"{label}: 허용 범위를 벗어난 숫자입니다.")
    return n


def date_value(value, label="날짜"):
    try:
        return dt.date.fromisoformat(str(value))
    except (ValueError, TypeError):
        raise ValueError(f"{label}: YYYY-MM-DD 형식이 필요합니다.") from None


def _safe_tree(value, depth=0, counter=None):
    """Reject credentials, unsafe resource URLs, unreasonable JSON and NaNs."""
    if counter is None:
        counter = [0]
    counter[0] += 1
    if depth > 30 or counter[0] > 3000000:
        raise ValueError("분석 자료의 크기 또는 중첩 단계가 너무 큽니다.")
    if isinstance(value, dict):
        result = {}
        for key, child in value.items():
            if not isinstance(key, str) or len(key) > 200:
                raise ValueError("자료 항목 이름이 올바르지 않습니다.")
            norm = re.sub(r"[_\-\s]", "", key).lower()
            if norm in SECRET_FIELDS:
                raise ValueError("분석 자료에는 인증 정보를 넣을 수 없습니다.")
            if norm in EXCLUDED_PRICE_FIELDS:
                continue
            result[key] = _safe_tree(child, depth + 1, counter)
        return result
    if isinstance(value, list):
        if len(value) > 100000:
            raise ValueError("분석 자료 행 수가 너무 많습니다.")
        return [_safe_tree(v, depth + 1, counter) for v in value]
    if isinstance(value, str):
        if len(value) > 20000:
            raise ValueError("자료의 텍스트가 너무 깁니다.")
        if value.strip().lower().startswith(("javascript:", "data:text/html", "file:")):
            raise ValueError("허용되지 않는 자료 주소입니다.")
        if value.startswith(("https://", "http://")):
            parts = urlsplit(value)
            if parts.username or parts.password:
                raise ValueError("인증 정보가 포함된 주소는 저장할 수 없습니다.")
            if any(re.sub(r"[_\-]", "", k).lower() in SECRET_FIELDS for k, _ in parse_qsl(parts.query)):
                raise ValueError("인증 정보가 포함된 주소는 저장할 수 없습니다.")
            if re.search(r"/wmts/1\.0\.0/[^/]+/", parts.path):
                raise ValueError("인증 정보가 포함된 타일 주소는 저장할 수 없습니다.")
        return value
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and math.isfinite(value):
        return value
    raise ValueError("JSON에서 사용할 수 없는 값입니다.")


def quantile(values, p):
    if not values:
        return None
    h = (len(values) - 1) * p
    lo, hi = math.floor(h), math.ceil(h)
    return values[lo] + (values[hi] - values[lo]) * (h - lo)


def statistics(values):
    """Linear quantiles, observed Tukey whiskers; no automatic outlier removal."""
    x = sorted(number(v, "표본", required=True) for v in values)
    if not x:
        return {"n": 0, "min": None, "q1": None, "median": None, "mean": None,
                "q3": None, "max": None, "iqr": None, "whiskerLow": None,
                "whiskerHigh": None, "outliers": [], "showBox": False, "status": "비교사례 없음"}
    q1, med, q3 = (quantile(x, p) for p in (.25, .5, .75))
    iqr = q3 - q1
    inner = [v for v in x if q1 - 1.5 * iqr <= v <= q3 + 1.5 * iqr]
    return {"n": len(x), "min": x[0], "q1": q1, "median": med,
            "mean": math.fsum(v / len(x) for v in x), "q3": q3, "max": x[-1], "iqr": iqr,
            "whiskerLow": min(inner), "whiskerHigh": max(inner),
            "outliers": [v for v in x if v < min(inner) or v > max(inner)],
            "showBox": len(x) >= 5,
            "status": "사례 부족" if len(x) < 5 else ("동일 금액 관측" if x[0] == x[-1] else "산출 완료")}


def _positive_case(value):
    try:
        x = number(value)
        return x if x is not None and x > 0 else None
    except ValueError:
        return None


def _geo_distance_km(lon1, lat1, lon2, lat2):
    """Great-circle distance; map pixels and degree differences are not distances."""
    a, b = math.radians(lat1), math.radians(lat2)
    dlat, dlon = b - a, math.radians(lon2 - lon1)
    h = math.sin(dlat / 2) ** 2 + math.cos(a) * math.cos(b) * math.sin(dlon / 2) ** 2
    return 6371.0088 * 2 * math.asin(math.sqrt(min(1, max(0, h))))


def _parcel_center(parcels):
    """Same documented union bounding-box center used by the map controls."""
    points = []
    def visit(value):
        if not isinstance(value, list):
            return
        if len(value) >= 2 and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in value[:2]):
            lon, lat = value[:2]
            if not (math.isfinite(lon) and math.isfinite(lat) and 120 < lon < 134 and 30 < lat < 40):
                raise ValueError("필지 좌표는 국내 EPSG:4326 경도·위도여야 합니다.")
            points.append((lon, lat))
        else:
            for child in value:
                visit(child)
    if not parcels:
        return None
    for parcel in parcels:
        geometry = parcel.get("geometry") or {}
        if geometry.get("type") not in ("Polygon", "MultiPolygon"):
            return None
        before = len(points)
        visit(geometry.get("coordinates"))
        if len(points) == before:
            return None
    return {"lon": (min(x for x, _ in points) + max(x for x, _ in points)) / 2,
            "lat": (min(y for _, y in points) + max(y for _, y in points)) / 2}


def _canonical_dong(value):
    """Normalize only the name form; a bare village name is never a full key."""
    parts = str(value or "").strip().split()
    if not parts:
        return ""
    if parts[-1].endswith("리") and len(parts) > 1 and parts[-2].endswith(("읍", "면")):
        return " ".join(parts[-2:])
    return parts[-1]


def _same_dong(left, right):
    a, b = _canonical_dong(left), _canonical_dong(right)
    return bool(a and b and a == b and not (a.endswith("리") and " " not in a))


def _comparison_period(record, dataset):
    """Split-period inputs keep legacy common-month snapshots readable."""
    prefix = "revenue" if dataset == "revenue" else "land"
    return (record.get(prefix + "Start") or record.get("start"),
            record.get(prefix + "End") or record.get("end"))


def _valid_month(value):
    try:
        return bool(re.fullmatch(r"\d{4}-\d{2}", str(value or ""))) and date_value(str(value) + "-01") is not None
    except ValueError:
        return False


def _rolling_query_valid(query, dataset):
    """Historical saved windows stay readable, but must describe exactly 60 months."""
    try:
        boundary=date_value(query.get("endExclusive"), "조회 종료 경계")
        if boundary.day!=1:return False
        first=boundary.replace(year=boundary.year-5)
        last=boundary-dt.timedelta(days=1)
        return (_comparison_period(query,dataset)==(first.strftime("%Y-%m"),last.strftime("%Y-%m"))
                and query.get(dataset+"StartDate")==first.isoformat()
                and query.get(dataset+"EndDate")==last.isoformat())
    except (ValueError,TypeError,AttributeError):
        return False


def _case_date_reason(case, inputs, dataset, linkage):
    """Never compare malformed date strings lexically or accept post-as-of rows."""
    value = case.get("date")
    if value in (None, ""):
        if linkage and dataset == "land":
            return "거래일 미확정"
        if linkage and linkage["query"].get("asOf"):
            return "공고일 미확정"
        return None  # Historical/manual v1 fixtures did not require dated evidence.
    try:
        date = date_value(value)
    except ValueError:
        return "공고일 미확정" if dataset == "revenue" else "거래일 미확정"
    cutoff = inputs.get("project", {}).get("asOf")
    if cutoff and date > date_value(cutoff, "분석 기준일"):
        return "분석 기준일 이후 공고" if dataset == "revenue" else "분석 기준일 이후 거래"
    if linkage:
        start, end = _comparison_period(linkage["query"], dataset)
        if not start <= date.isoformat()[:7] <= end:
            return "조회 기간 밖 분양사례" if dataset == "revenue" else "조회 기간 밖 토지거래"
        query=linkage["query"]
        first=query.get(dataset+"StartDate")
        last=query.get(dataset+"EndDate")
        if (first and date.isoformat()<first) or (last and date.isoformat()>last):
            return "조회 일자 범위 밖 사례"
        if query.get("periodMode")=="rolling60" and date.isoformat()>=str(query.get("endExclusive") or ""):
            return "월초 종료 경계 이후 사례"
        if query.get("periodMode")=="latest" and date.isoformat() < ("2020-02-04" if dataset=="revenue" else "2006-01-01"):
            return "고정 시작일 이전 사례"
    return None


def _comparison_linkage_context(inputs, dataset="land"):
    """Reject stale API comparisons while retaining explicit legacy manual inputs.

    PNU identifies the selected parcel's legal district. The API query records the
    population that was actually fetched; editable filters cannot rewrite it.
    """
    filters = inputs.get("comparisonFilters") or {}
    comparisons = inputs.get("comparables", {})
    query = (comparisons.get("landQuery") if dataset == "land" else None) or comparisons.get("query") or {}
    active = bool(query) or any(k in filters for k in ("sgg", "dong", "start", "end", "landStart", "revenueStart", "selectionLinked"))
    if not active:
        return None
    result = {"reason": None, "query": query, "legalDongCode": None}
    parcels = inputs.get("parcels", [])
    if not parcels:
        result["reason"] = "개발 대상 필지를 선택해야 비교사례와 예상 금액을 계산할 수 있습니다."
        return result
    codes, names = set(), set()
    for parcel in parcels:
        pnu = str(parcel.get("pnu") or "")
        code = str(parcel.get("legalDongCode") or "")
        if not re.fullmatch(r"\d{19}", pnu) or (code and (not re.fullmatch(r"\d{10}", code) or code != pnu[:10])):
            result["reason"] = "선택 필지의 PNU·법정동코드를 확인한 뒤 비교사례를 다시 조회하세요."
            return result
        codes.add(pnu[:10])
        name = _canonical_dong(parcel.get("dong") or parcel.get("legalDongName"))
        if name:
            names.add(name)
    if len(codes) != 1:
        result["reason"] = "선택 필지가 서로 다른 법정동에 걸쳐 있습니다. 현재는 같은 법정동의 필지만 함께 분석할 수 있습니다."
        return result
    code = next(iter(codes))
    result["legalDongCode"] = code
    # Old API snapshots may have no editable filter object; their actual query
    # still provides the region/period against which the selected PNU is checked.
    expected = filters if any(k in filters for k in ("sgg", "dong", "start", "end", "landStart", "revenueStart")) else query
    sgg, dong = str(expected.get("sgg") or ""), expected.get("dong")
    expected_code = str(expected.get("legalDongCode") or "")
    if (sgg != code[:5] or (expected_code and expected_code != code)
            or any(not _same_dong(name, dong) for name in names)):
        result["reason"] = "선택 필지와 비교 지역이 다릅니다. 필지의 시군구·법정동으로 비교사례를 다시 조회하세요."
    elif not query:
        result["reason"] = "선택 필지·지역·기간에 맞는 비교사례를 다시 조회하세요."
    elif (not _same_dong(expected.get("dong"), query.get("dong"))
          or str(expected.get("sgg", "")) != str(query.get("sgg", ""))
          or _comparison_period(expected, dataset) != _comparison_period(query, dataset)):
        result["reason"] = "비교 지역·기간이 변경되었습니다. 현재 조건으로 비교사례를 다시 조회하세요."
    elif not all(_valid_month(value) for value in _comparison_period(query, dataset)) or _comparison_period(query, dataset)[0] > _comparison_period(query, dataset)[1]:
        result["reason"] = "비교사례의 조회 기간을 확인하고 다시 조회하세요."
    elif (filters.get("periodMode")=="rolling60" or query.get("periodMode")=="rolling60") and (
          query.get("periodMode")!="rolling60" or not _rolling_query_valid(query,dataset)
          or any(filters.get(k) and filters[k]!=query.get(k) for k in ("endExclusive",dataset+"StartDate",dataset+"EndDate"))):
        result["reason"] = "완료된 60개월의 시작·종료 경계가 변경되었습니다. 필지 선택 후 비교사례를 다시 조회하세요."
    elif filters.get("periodMode")=="latest" and (query.get("periodMode")!="latest"
          or query.get(dataset+"StartDate")!=("2020-02-04" if dataset=="revenue" else "2006-01-01")
          or any(filters.get(dataset+suffix) and filters[dataset+suffix]!=query.get(dataset+suffix) for suffix in ("StartDate","EndDate"))):
        result["reason"] = "최신 범위의 시작·종료일이 변경되었습니다. 비교사례를 다시 조회하세요."
    elif query.get("asOf") and str(query["asOf"]) != str(expected.get("asOf") or inputs.get("project", {}).get("asOf") or ""):
        result["reason"] = "분석 기준일이 변경되었습니다. 현재 기준일로 비교사례를 다시 조회하세요."
    return result


def _revenue_radius_context(inputs):
    """Do not reuse a prior site's prices after changing parcel or query scope."""
    filters = inputs.get("comparisonFilters") or {}
    query = inputs.get("comparables", {}).get("query") or {}
    if filters.get("scope", query.get("scope", "dong")) != "radius":
        return None
    result = {"center": None, "radiusKm": None, "reason": None}
    try:
        center = _parcel_center(inputs.get("parcels", []))
        # Dong snapshots store radiusKm:null. Match the UI's nullish default
        # when the user switches back to radius, without treating 0/"" as absent.
        raw_radius = filters.get("radiusKm")
        radius = number(5 if raw_radius is None else raw_radius, "분양 검색 반경", minimum=.1, maximum=10, required=True)
        result.update(center=center, radiusKm=radius)
        if not center:
            result["reason"] = "주변 분양사례 검색을 위해 도형이 확인된 개발 필지를 선택하세요."
        elif query.get("scope") != "radius":
            result["reason"] = "주변 분양사례를 현재 조건으로 조회하세요."
        else:
            fetched = query.get("center") or {}
            qlon = number(fetched.get("lon"), "조회 중심 경도", required=True)
            qlat = number(fetched.get("lat"), "조회 중심 위도", required=True)
            qradius = number(query.get("radiusKm"), "조회 반경", required=True)
            changed = abs(center["lon"]-qlon) > 0.000001 or abs(center["lat"]-qlat) > 0.000001 or abs(radius-qradius) > .000001
            changed = changed or any(str(filters.get(k, "")) != str(query.get(k, "")) for k in ("sgg", "dong"))
            changed = changed or _comparison_period(filters, "revenue") != _comparison_period(query, "revenue")
            if changed:
                result["reason"] = "필지·지역·기간·반경이 변경되어 주변 분양사례 재조회가 필요합니다."
    except (ValueError, TypeError, AttributeError):
        result["reason"] = "주변 분양사례의 위치·조회 조건을 확인하고 다시 조회하세요."
    return result


def _collection_incomplete(inputs, dataset=None):
    incomplete = {"partial", "failed", "수집 미완료", "조회 실패"}
    if dataset is None:
        return _collection_incomplete(inputs, "applyhome") or _collection_incomplete(inputs, "land")
    statuses = []
    if dataset == "land":
        comparisons = inputs.get("comparables") or {}
        land_query = comparisons.get("landQuery") or {}
        if isinstance(land_query, dict): statuses.append(land_query.get("collectionStatus"))
        statuses.append(comparisons.get("landCollectionStatus"))
    for source in inputs.get("sources", []):
        if isinstance(source, dict) and source.get("id") == dataset:
            statuses.extend((source.get("collectionStatus"), source.get("status")))
    if any(isinstance(status, str) and status in incomplete for status in statuses):
        return True
    if "complete" in statuses or "최신 조회 완료" in statuses:
        return False
    # An undifferentiated partial flag cannot prove either dataset is complete.
    fallback = [inputs.get("collectionStatus"), inputs.get("comparables", {}).get("collectionStatus")]
    return any(isinstance(status, str) and status in incomplete for status in fallback)


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


def _adjustment(assumptions, key):
    pct = number(assumptions.get(key, 0), key, required=True)
    if pct <= -100:
        raise ValueError("가격 보정률은 -100%보다 커야 합니다.")
    return 1 + pct / 100


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
    return {"label": "최고가 사례 기준 잠재 분양수입", "points": points,
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


def _input_error(errors, section, path, message):
    if errors is None:
        raise ValueError(message)
    error = {"section": section, "path": path, "message": str(message)}
    if error not in errors:
        errors.append(error)


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
    from pf_boundary import recompute_boundary
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
