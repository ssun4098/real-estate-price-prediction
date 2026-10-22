"""비교사례(토지 실거래·분양사례) 고르는 규칙: 조회 기간, 같은 동인지, 대상지와의 거리(반경).
"""
from __future__ import annotations

import datetime as dt
import math
import re

from server.domain.analysis.common import date_value, number


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


def _adjustment(assumptions, key):
    pct = number(assumptions.get(key, 0), key, required=True)
    if pct <= -100:
        raise ValueError("가격 보정률은 -100%보다 커야 합니다.")
    return 1 + pct / 100
