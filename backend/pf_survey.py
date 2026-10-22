"""V2 public site survey. Transport and credentials are supplied by the caller.

No credential discovery, persistence, financial defaults, or synthetic geometry.
Current public data must not be presented as a historical site inspection.
"""
from __future__ import annotations

import copy
import datetime as dt
import json
import math
import re
from concurrent.futures import ThreadPoolExecutor

LABELS = {"success": "조회 성공", "empty": "자료 없음", "error": "조회 실패",
          "credentials_missing": "인증 미준비", "permission_required": "이용 권한 확인 필요",
          "unavailable": "미확보", "needs_configuration": "추가 설정 필요",
          "partial": "일부 조회·확인 필요", "not_requested": "조회 전"}
PRICE_URL = "https://www.vworld.kr/dtna/dtna_apiSvcFc_s001.do?apiNum=25"
SEARCH_URL = "https://www.vworld.kr/dev/v4dv_search2_s001.do"
KOSIS_URL = "https://kosis.kr/openapi/devGuide/devGuide_0201List.do"
SGIS_URL = "https://sgis.mods.go.kr/developer/html/openApi/api/data.html"
CURRENT_NOTE = "조회 시점의 공개자료이며 분석 기준일 당시의 현황을 재현한 자료가 아닙니다."
FACILITY_NOTE = "키워드 검색으로 확보한 후보이며 반경 안 전체 시설의 전수목록이나 실제 운영 여부를 보장하지 않습니다."
GROUPS = (("school", "학교"), ("mountain", "산"), ("river", "하천"),
          ("industrial", "산업단지"), ("sewage", "하수처리"))
FACILITY_GROUP_IDS = frozenset(group for group, _ in GROUPS)
ENTITY_RULE_VERSION = "facility-parent-candidates-v3"
FACILITY_DISTANCE_BANDS = (("within1", 0, 1), ("over1to3", 1, 3), ("over3to5", 3, 5))
LAYERS = (
    ("schoolDistrict", "초등학교통학구역", "LT_C_DESCH", "desch",
     ("objectid", "hakgudo_id", "hakgudo_nm", "hakgudo_gb", "sd_cd", "sgg_cd", "edu_up_nm", "edu_nm", "base_dt"), "hakgudo_nm"),
    ("naturalParkZone", "도시자연공원구역", "LT_C_UQ162", "uq162",
     ("uname", "sido_name", "sigg_name", "dyear", "dnum"), "uname"),
    ("nationalIndustrialZone", "국가산업단지", "LT_C_WGISIEGUG", "wgisiegug",
     ("e_name", "e_code"), "e_name"),
)
# Only the requested industrial-complex reference layer is queried. The older
# specifications remain usable when inspecting already collected evidence.
ACTIVE_LAYERS = tuple(spec for spec in LAYERS if spec[0] == "nationalIndustrialZone")


def _now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _num(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(str(value).replace(",", "").strip())
        return result if math.isfinite(result) else None
    except (ValueError, TypeError):
        return None


def _text(value):
    return "" if value is None else str(value).strip()


def _arg(query, key, default=None):
    value = query.get(key, default)
    return value[0] if isinstance(value, (list, tuple)) and value else value


def _component(status, title, url, rows=None, **extra):
    rows = rows or []
    result = {"status": status, "statusLabel": LABELS[status], "rows": rows,
              "count": len(rows), "source": {"title": title, "url": url},
              "queriedAt": _now(), "referencePeriods": [],
              "temporalBasis": "current", "warnings": []}
    result.update(extra)
    return result


def _missing(client, names):
    return [name for name in names if not getattr(client, "keys", {}).get(name)]


class _UpstreamError(Exception):
    def __init__(self, code="UPSTREAM_ERROR"):
        self.code = code


def _error(exc, title, url):
    # Never echo upstream messages, URLs, params, tokens or exception repr.
    code = getattr(exc, "code", "UPSTREAM_ERROR")
    allowed = {"KEY_MISSING", "UPSTREAM_AUTH", "UPSTREAM_RATE_LIMIT", "UPSTREAM_HTTP",
               "UPSTREAM_NETWORK", "INVALID_JSON", "INVALID_XML", "RESPONSE_TOO_LARGE",
               "UPSTREAM_SCHEMA", "UPSTREAM_ERROR", "UPSTREAM_REJECTED"}
    code = code if code in allowed else "UPSTREAM_ERROR"
    state = "credentials_missing" if code == "KEY_MISSING" else "permission_required" if code == "UPSTREAM_AUTH" else "error"
    return _component(state, title, url, errorCode=code,
                      warnings=["인증·서비스 이용 권한·요청 조건 또는 원천 응답을 확인해야 합니다."])


def _response(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get("response"), dict):
        raise _UpstreamError("UPSTREAM_SCHEMA")
    response = payload["response"]
    status = response.get("status")
    if status == "NOT_FOUND":
        return response, False
    if status != "OK":
        error = response.get("error", {})
        code = _text(error.get("code")) if isinstance(error, dict) else ""
        raise _UpstreamError("UPSTREAM_AUTH" if code in {"INVALID_KEY", "INCORRECT_KEY", "UNREGISTERED_KEY", "INVALID_DOMAIN", "UNAUTHORIZED_KEY"} else "UPSTREAM_REJECTED")
    return response, True


def _ned_rows(payload):
    if not isinstance(payload, dict):
        raise _UpstreamError("UPSTREAM_SCHEMA")
    candidates = [payload] + [v for v in payload.values() if isinstance(v, dict)]
    for value in candidates:
        if value.get("error") or value.get("resultCode") not in (None, "", "0", "00", 0):
            raise _UpstreamError("UPSTREAM_REJECTED")
    for value in candidates:
        if "field" in value or "totalCount" in value:
            rows = value.get("field", [])
            rows = [rows] if isinstance(rows, dict) else rows or []
            if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                raise _UpstreamError("UPSTREAM_SCHEMA")
            total = _num(value.get("totalCount"))
            if total is not None and total > 0 and not rows:
                raise _UpstreamError("UPSTREAM_SCHEMA")
            return rows, int(total) if total is not None else len(rows)
    raise _UpstreamError("UPSTREAM_SCHEMA")


def enrich_parcel(client, parcel, year):
    """Copy a parcel and add an independently sourced reference price only."""
    result = copy.deepcopy(parcel)
    title = "브이월드 개별공시지가정보"
    pnu = _text(parcel.get("pnu"))
    year = str(year)
    if not re.fullmatch(r"\d{19}", pnu) or not re.fullmatch(r"\d{4}", year):
        result["officialLandPrice"] = _component("needs_configuration", title, PRICE_URL,
                                                warnings=["19자리 PNU와 가격 기준연도가 필요합니다."])
        return result
    missing = _missing(client, ["vworld"])
    if missing:
        result["officialLandPrice"] = _component("credentials_missing", title, PRICE_URL, missingCredentials=missing)
        return result
    try:
        rows, seen, raw_count, total = [], set(), 0, 0
        for page in range(1, 6):
            payload = client.request("https://api.vworld.kr/ned/data/getIndvdLandPriceAttr", {
                "key": client.require("vworld"), "domain": getattr(client, "domain", ""),
                "pnu": pnu, "stdrYear": year, "format": "json", "numOfRows": 100, "pageNo": page})
            part, total = _ned_rows(payload)
            raw_count += len(part)
            for row in part:
                if _text(row.get("pnu")) != pnu or _text(row.get("stdrYear")) != year:
                    continue
                clean = {"pnu": pnu, "year": _text(row.get("stdrYear")), "month": _text(row.get("stdrMt")),
                         "priceWonPerM2": _num(row.get("pblntfPclnd")),
                         "publicationDate": _text(row.get("pblntfDe")), "sourceUpdatedAt": _text(row.get("lastUpdtDt"))}
                signature = json.dumps(clean, sort_keys=True)
                if signature not in seen:
                    seen.add(signature)
                    rows.append(clean)
            if raw_count >= total or not part:
                break
        status = "partial" if raw_count < total else "success" if rows else "empty"
        warnings = ["공시지가는 원/㎡ 참고자료이며 매입가·실거래가·장부가·감정가를 대체하지 않습니다.",
                    "가격 기준연도와 현재 조회 시점을 구별하며 당시 공개되어 있던 자료의 스냅샷은 아닙니다."]
        if raw_count < total:
            warnings.append("조회 상한에 도달해 일부 자료만 확보했습니다.")
        if rows and any(r["priceWonPerM2"] is None for r in rows):
            status = "partial"
            warnings.append("가격 결측은 0으로 처리하지 않았습니다.")
        result["officialLandPrice"] = _component(status, title, PRICE_URL, rows,
            referencePeriods=sorted({r["year"] + ("-" + r["month"].zfill(2) if r["month"] else "") for r in rows}),
            requestedYear=year, temporalBasis="reference_year_current_revision", warnings=warnings,
            unit="원/㎡", officialPath="getIndvdLandPriceAttr", rawCount=raw_count, sourceTotal=total)
    except Exception as exc:
        result["officialLandPrice"] = _error(exc, title, PRICE_URL)
    return result


def _distance(lon1, lat1, lon2, lat2):
    dlat, dlon = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return 6371.0088 * 2 * math.asin(min(1.0, math.sqrt(a)))


def _bbox(lon, lat, radius):
    dy = radius / 110.5
    dx = radius / (110.5 * math.cos(math.radians(lat)))
    return ",".join(str(round(n, 8)) for n in (lon-dx, lat-dy, lon+dx, lat+dy))


def is_retail_facility(row):
    if not isinstance(row, dict): return False
    row = row.get("properties", row)
    if not isinstance(row, dict): return False
    groups = row.get("groups", [])
    return (row.get("group") == "retail" or (isinstance(groups, list) and "retail" in groups)
            or row.get("sourceId") == "vworld-place-retail"
            or bool(re.search(r"(?:^|[>,/|;\s])(?:대형|할인|슈퍼|수퍼)?마트(?:$|[>,/|;\s])", str(row.get("category") or ""))))


def exclude_retail_facilities(survey):
    """Remove old cached retail items as well as newly returned category matches."""
    survey = copy.deepcopy(survey)
    facilities = survey.get("facilities")
    if isinstance(facilities, dict):
        facilities["items"] = [r for r in facilities.get("items", []) if not is_retail_facility(r)]
        services = facilities.get("services", {})
        services.pop("retail", None)
        for service in services.values():
            if isinstance(service, dict) and isinstance(service.get("rows"), list):
                service["rows"] = [r for r in service["rows"] if not is_retail_facility(r)]
                service["count"] = len(service["rows"])
        collection = facilities.get("featureCollection")
        if isinstance(collection, dict):
            collection["features"] = [f for f in collection.get("features", []) if not is_retail_facility(f)]
    survey["indicators"] = [r for r in survey.get("indicators", []) if r.get("id") != "retailNearestKm" and r.get("sourceId") != "vworld-place-retail"]
    survey["sources"] = [r for r in survey.get("sources", []) if r.get("id") != "vworld-place-retail"]
    return survey


def _facility_name_evidence(row, group):
    """Conservative name/category screening, never fabricate a parent point."""
    name = re.sub(r"\s+", "", _text(row.get("name")))
    category = _text(row.get("category"))
    terminals = {
        "school": r"(?:학교|대학|분교|캠퍼스)",
        "mountain": r"(?:산|봉)",
        "river": r"(?:하천|천|강|계곡)",
        "industrial": r"(?:산업단지|공업단지|농공단지)",
        "sewage": r"(?:하수종말처리장|하수처리장|공공하수처리시설|하수처리시설|수질복원센터|수질정화센터|물재생센터)",
    }
    terminal = terminals[group]
    # A primary-feature suffix followed only by a known accessory is evidence
    # of a subsidiary POI, not evidence of another mountain/industrial complex.
    accessory = r"(?:제?\d*[동서남북중앙]*입구|입구|주차장|공영주차장|노상주차장|등산로입구|등산로|매표소|관리사무소|관리소|방문자센터|안내소|정문|후문|북문|남문|동문|서문|전망대|쉼터|화장실|정류장|버스정류장|운동장|체육관|강당|도서관|기숙사)"
    sub = re.fullmatch(r"(.+?" + terminal + r")[\-·_()]*(" + accessory + r")(?:\([^)]*\))?", name)
    if sub:
        return {"kind": "subsidiary", "parentName": sub.group(1), "reason": "입구·주차장 등 부속 장소 · 시설 수·거리 집계 제외"}
    blocked_category = re.search(r"(?:음식|식당|카페|숙박|부동산|중개|의원|병원|약국|쇼핑|상점|학원|주유소|주차장|버스정류장|등산용품)", category) or (group != "school" and "학교" in category)
    if blocked_category or is_retail_facility(row) or re.search(r"(?:부동산|중개사|공인중개|재산관리)", name):
        return {"kind": "excluded", "parentName": None, "reason": "시설 본체가 아닌 장소 분류 · 집계 제외"}
    # The keyword '산' also matches 수산/농산/부동산 businesses. A plausible
    # suffix is insufficient: require an explicit source natural-feature type.
    # Keep missing/unrecognized classifications in evidence for later review.
    category_parts = {part.strip() for part in re.split(r"[>,/;|]", category) if part.strip()}
    positive_category = {
        "school": bool(category_parts & {"학교", "초등학교", "중학교", "고등학교", "대학교", "대학", "전문대학", "특수학교", "각종학교", "초등교육기관", "중등교육기관", "고등교육기관"}),
        "mountain": "자연지명" in category_parts and bool(category_parts & {"산", "산지", "산맥", "봉", "산봉", "산봉우리"}),
        "river": "자연지명" in category_parts and bool(category_parts & {"하천", "강", "천", "계곡"}),
        "industrial": bool(category_parts & {"산업단지구역", "산업단지", "국가산업단지", "일반산업단지", "농공단지", "공업단지"}),
        "sewage": bool(category_parts & {"환경기초시설", "하수처리", "하수처리장", "하수처리시설", "하수종말처리장", "물재생", "물재생센터", "수질정화", "수질정화센터"}),
    }
    if group in positive_category and not positive_category[group]:
        return {"kind": "excluded", "parentName": None, "reason": "원천 분류에서 해당 본시설 유형 미확정 · 명칭만으로 집계하지 않음"}
    primary = re.fullmatch(r"(.+?" + terminal + r")(?:\([^)]*\))?", name)
    if primary and primary.group(1) not in {"하천", "산업단지", "하수처리장"}:
        return {"kind": "primary", "parentName": primary.group(1), "reason": "본시설 명칭 후보 · 실제 경계·운영 여부 미확인"}
    if group == "sewage" and re.fullmatch(terminal, name):
        return {"kind": "primary", "parentName": name, "reason": "원천 환경시설 분류·하수처리시설 명칭 확인 · 일반 명칭은 원주소·식별자로 구별"}
    # Treatment plants often use names such as '푸른물센터'. Their source
    # category can establish the type without guessing from the brand name.
    if (group == "sewage" and re.search(r"(?:하수처리|물재생|수질정화)", category)
            and name and not re.search(accessory + r"$", name)):
        return {"kind": "primary", "parentName": name, "reason": "원천 하수처리시설 분류의 본시설 후보 · 운영 여부 미확인"}
    return {"kind": "excluded", "parentName": None, "reason": "시설 본체 명칭 미확정 · 키워드 일치만으로 집계하지 않음"}


def group_facility_candidates(rows, group):
    """Keep every candidate; attach accessories only to a unique nearby main POI.

    Same-name main points within 300 m are one *candidate* when their two-level
    address locality agrees. This is not an official feature/entity identifier.
    Remote homonyms, ambiguous accessory parents and orphan accessories stay
    distinguishable in evidence. No parent coordinate is inferred from an entry.
    """
    if group not in FACILITY_GROUP_IDS:
        return {"items": [], "candidates": [], "excludedCount": len(rows), "mergedCount": 0}
    evidence, entities = [], []
    for raw in rows:
        row = copy.deepcopy(raw)
        decision = _facility_name_evidence(row, group)
        row.update(candidateKind=decision["kind"], parentName=decision["parentName"],
                   inclusionReason=decision["reason"], included=False, entityId=None,
                   groupingRuleVersion=ENTITY_RULE_VERSION)
        evidence.append(row)
        if decision["kind"] != "primary":
            continue
        full_address = _text(row.get("parcelAddress") or row.get("roadAddress"))
        locality = " ".join(full_address.split()[:2])
        generic_name = decision["parentName"] in {"공공하수처리시설", "하수처리시설", "하수처리장", "하수종말처리장", "수질정화센터", "물재생센터"}
        matches = [entity for entity in entities if entity["normalizedName"] == decision["parentName"]
                   and locality and entity["locality"] == locality
                   and (not generic_name or full_address and full_address == entity["fullAddress"])
                   and _distance(row["lon"], row["lat"], entity["lon"], entity["lat"]) <= .3]
        if len(matches) == 1:
            entity = matches[0]
            entity["memberIds"].append(row["id"])
            entity["duplicateCount"] += 1
            row.update(entityId=entity["id"], inclusionReason="동명·동일 지역·300m 이내 대표점 중복 후보 · 1개로 묶음")
            continue
        entity = copy.deepcopy(raw)
        entity.update(id=group + ":" + _text(row["id"]), sourceRecordId=row["id"],
                      normalizedName=decision["parentName"], locality=locality, fullAddress=full_address, groups=[group],
                      memberIds=[row["id"]], subsidiaryIds=[], duplicateCount=0,
                      groupingRuleVersion=ENTITY_RULE_VERSION, entityStatus="main_feature_candidate",
                      pointBasis="본시설 명칭의 검색 대표점 · 경계까지 거리가 아님")
        entities.append(entity)
        row.update(included=True, entityId=entity["id"])
    for row in evidence:
        if row["candidateKind"] != "subsidiary":
            continue
        matches = [entity for entity in entities if entity["normalizedName"] == row["parentName"]
                   and _distance(row["lon"], row["lat"], entity["lon"], entity["lat"]) <= 2]
        if len(matches) == 1:
            entity = matches[0]
            entity["subsidiaryIds"].append(row["id"])
            row.update(entityId=entity["id"], inclusionReason="동명 본시설 후보(2km 이내)에 연결 · 부속 장소는 수·거리 집계 제외")
        elif len(matches) > 1:
            row["inclusionReason"] = "동명 본시설 후보가 여러 개 · 연결 보류·집계 제외"
        else:
            row["inclusionReason"] = "본시설 대표점 미확보 · 부속 장소 위치로 본시설 거리를 대체하지 않음"
    entities.sort(key=lambda row: (row["distanceKm"], row["id"]))
    return {"items": entities, "candidates": evidence,
            "excludedCount": sum(row["candidateKind"] != "primary" for row in evidence),
            "mergedCount": sum(entity["duplicateCount"] for entity in entities)}


def facility_distance_bands(items, services, radius_km=5):
    """Exclusive bands of retained main candidates, never cumulative counts.

    Partial/failed retrieval yields a lower bound if any candidates are known,
    otherwise null. A verified empty query can show zero; missing queries cannot.
    Distances at exactly 1 and 3 km belong to the closer band.
    """
    unique, seen = [], set()
    for row in items:
        group = row.get("group") or next(iter(row.get("groups") or []), None)
        identifier = row.get("entityId") or row.get("id") or row.get("sourceRecordId")
        distance = _num(row.get("distanceKm"))
        if group not in FACILITY_GROUP_IDS or identifier is None or distance is None or distance < 0 or row.get("included") is False:
            continue
        identity = (group, str(identifier))
        if identity not in seen:
            seen.add(identity)
            unique.append((group, distance, row))
    result = []
    for band_id, low, high in FACILITY_DISTANCE_BANDS:
        categories = []
        for group, label in GROUPS:
            service = services.get(group, {})
            status = service.get("status", "not_requested")
            rows = [row for g, distance, row in unique if g == group and distance <= high and (distance >= 0 if low == 0 else distance > low)]
            complete = status in {"success", "empty"} and _num(radius_km) is not None and float(radius_km) >= high
            count = len(rows) if rows or complete else None
            response_covers_band = status in {"success", "empty", "partial"} and _num(radius_km) is not None and float(radius_km) >= high
            categories.append({"group": group, "label": "하수처리장" if group == "sewage" else label,
                               "count": count, "status": status, "isLowerBound": not complete,
                               "observedCount": len(rows) if rows or response_covers_band else None,
                               "retrievalComplete": complete, "countBasis": "retrieved_distinct_facilities",
                               "entityIds": [row.get("id") for row in rows]})
        result.append({"id": band_id, "minExclusiveKm": low if low else None, "maxInclusiveKm": high,
                       "categories": categories, "unit": "개"})
    return result


def _search_group(client, group, keyword, lon, lat, radius):
    if group == "retail":
        return _component("not_requested", "표시 제외 시설", SEARCH_URL, warnings=["마트 시설 조회·표시는 제외했습니다."])
    title = "브이월드 장소 검색 · " + keyword
    missing = _missing(client, ["vworldSearch"])
    if missing:
        return _component("credentials_missing", title, SEARCH_URL, missingCredentials=missing)
    rows, seen, total, fetched, invalid = [], set(), 0, 0, 0
    try:
        for page in range(1, 4):
            payload = client.request("https://api.vworld.kr/req/search", {
                "service": "search", "request": "search", "version": "2.0", "format": "json", "type": "PLACE",
                "query": keyword, "bbox": _bbox(lon, lat, radius), "crs": "EPSG:4326", "size": 100, "page": page,
                "key": client.require("vworldSearch"), "domain": getattr(client, "domain", "")})
            response, ok = _response(payload)
            if not ok:
                break
            result = response.get("result", {})
            items = result.get("items", []) if isinstance(result, dict) else []
            if not isinstance(items, list):
                raise _UpstreamError("UPSTREAM_SCHEMA")
            total = int(_num(response.get("record", {}).get("total")) or len(items))
            fetched += len(items)
            for item in items:
                if not isinstance(item, dict):
                    invalid += 1
                    continue
                point = item.get("point") or {}
                x, y = _num(point.get("x")), _num(point.get("y"))
                if x is None or y is None or not (124 <= x <= 132 and 33 <= y <= 39.5):
                    invalid += 1
                    continue
                distance = _distance(lon, lat, x, y)
                if distance > radius:
                    continue
                identifier = _text(item.get("id")) or _text(item.get("title")) + ":" + str(x) + ":" + str(y)
                if identifier in seen:
                    continue
                seen.add(identifier)
                # Other keyword searches may also return a retail-category place.
                # Do not let excluded marts re-enter through a misleading name.
                if is_retail_facility(item):
                    continue
                address = item.get("address") or {}
                rows.append({"id": identifier, "group": group, "name": _text(item.get("title")),
                             "category": _text(item.get("category")), "lon": x, "lat": y,
                             "distanceKm": round(distance, 6), "pointBasis": "원천 장소 검색 대표점",
                             "sourceId": "vworld-place-" + group,
                             "roadAddress": _text(address.get("road")), "parcelAddress": _text(address.get("parcel"))})
            if fetched >= total or not items:
                break
        rows.sort(key=lambda row: (row["distanceKm"], row["id"]))
        warnings = [CURRENT_NOTE, FACILITY_NOTE, "검색 대표점까지의 거리이며 시설 경계까지 거리·보행거리가 아닙니다."]
        if invalid:
            warnings.append("유효한 원천 좌표가 없는 검색 후보는 지도·거리에서 제외했습니다.")
        if fetched < total:
            warnings.append("검색 상한으로 일부 후보만 확보했습니다.")
        return _component("partial" if fetched < total or invalid else "success" if rows else "empty", title, SEARCH_URL, rows,
                          sourceTotal=total, fetchedCount=fetched, invalidCoordinateCount=invalid, queryKeyword=keyword,
                          warnings=warnings, completeInventory=False)
    except Exception as exc:
        failed = _error(exc, title, SEARCH_URL)
        if rows:
            failed.update(status="partial", statusLabel=LABELS["partial"], rows=rows, count=len(rows))
        return failed


def _valid_geometry(geometry):
    if not isinstance(geometry, dict) or geometry.get("type") not in {"Point", "MultiPoint", "LineString", "MultiLineString", "Polygon", "MultiPolygon"}:
        return False
    count = [0]
    def visit(value):
        if not isinstance(value, list) or not value:
            return False
        if isinstance(value[0], (int, float)):
            count[0] += 1
            return len(value) >= 2 and all(_num(v) is not None for v in value) and 124 <= value[0] <= 132 and 33 <= value[1] <= 39.5
        return all(visit(child) for child in value)
    return visit(geometry.get("coordinates")) and count[0] > 0


def _layer(client, spec, lon, lat, radius):
    group, title, layer, service, fields, name_field = spec
    url = "https://www.vworld.kr/dev/v4dv_2ddataguide2_s002.do?svcIde=" + service
    if _missing(client, ["vworld"]):
        return _component("credentials_missing", title, url, missingCredentials=["vworld"], features=[])
    try:
        payload = client.request("https://api.vworld.kr/req/data", {
            "service": "data", "request": "GetFeature", "version": "2.0", "data": layer,
            "key": client.require("vworld"), "domain": getattr(client, "domain", ""),
            "format": "json", "crs": "EPSG:4326", "size": 100, "page": 1,
            "geomFilter": "POINT(%s %s)" % (lon, lat), "buffer": round(radius*1000, 3),
            "geometry": "true", "attribute": "true"})
        response, ok = _response(payload)
        features = response.get("result", {}).get("featureCollection", {}).get("features", []) if ok else []
        if not isinstance(features, list):
            raise _UpstreamError("UPSTREAM_SCHEMA")
        total = int(_num(response.get("record", {}).get("total")) or len(features))
        clean, rejected = [], 0
        for feature in features:
            if not isinstance(feature, dict) or not _valid_geometry(feature.get("geometry")):
                rejected += 1
                continue
            properties = feature.get("properties") or {}
            properties = {field: properties[field] for field in fields if field in properties}
            properties.update(sourceId="vworld-layer-"+group, group=group, layer=layer,
                              name=_text(properties.get(name_field)) or title, pointBasis="원천 제공 도형")
            clean.append({"type": "Feature", "id": _text(feature.get("id")),
                          "geometry": feature["geometry"], "properties": properties})
        warnings = [CURRENT_NOTE, "지정구역 도형을 운영시설의 개수·시설 대표점·입학 가능성으로 바꾸어 해석하지 않습니다.",
                    "원천 도형의 제공 기준시점은 속성에서 확인된 경우에만 표시합니다."]
        if rejected or total > len(features):
            warnings.append("일부 도형 누락 또는 조회 상한으로 전체 구역 확인이 필요합니다.")
        return _component("partial" if rejected or total > len(features) else "success" if clean else "empty", title, url,
                          features=clean, count=len(clean), sourceTotal=total, layer=layer, warnings=warnings,
                          referencePeriods=sorted({_text(f["properties"].get("base_dt")) for f in clean if f["properties"].get("base_dt")}))
    except Exception as exc:
        result = _error(exc, title, url)
        result["features"] = []
        return result


def _kosis_list(payload):
    if isinstance(payload, dict):
        if str(payload.get("err")) == "30":
            return []
        raise _UpstreamError("UPSTREAM_REJECTED")
    if not isinstance(payload, list) or any(not isinstance(row, dict) for row in payload):
        raise _UpstreamError("UPSTREAM_SCHEMA")
    if any("err" in row for row in payload):
        raise _UpstreamError("UPSTREAM_REJECTED")
    return payload


def _match_kosis_region(classifications, parcels, explicit_name=""):
    """Resolve exact source names through official parents, never code prefixes.

    No province aliasing, fuzzy name matching, or automatic broader-area fallback.
    Multiple selected parcels must resolve to the very same source region.
    """
    regions = [r for r in classifications if _text(r.get("OBJ_ID_SN")) == "1"
               and "행정구역" in _text(r.get("OBJ_NM"))]
    grouped = {}
    for row in regions:
        grouped.setdefault(_text(row.get("ITM_ID")), []).append(row)
    by_code = {code: rows[0] for code, rows in grouped.items() if len(rows) == 1}
    def region_path(code):
        seen, names = set(), []
        while code:
            if code in seen or code not in by_code:
                return []
            seen.add(code)
            row = by_code[code]
            name = _text(row.get("ITM_NM"))
            if name != "전국":
                names[:0] = name.split()
            code = _text(row.get("UP_ITM_ID"))
        return names
    paths = {code: region_path(code) for code in by_code}
    names = [explicit_name] if explicit_name else [_text(p.get("legalDongName")) for p in parcels]
    if not names or any(not name for name in names):
        return None
    matches = []
    for name in names:
        administrative = []
        for token in name.split():
            if token.endswith(("동", "읍", "면", "리")) or re.search(r"\d", token):
                break
            administrative.append(token)
        candidates = [(code, path) for code, path in paths.items() if path and path == administrative]
        if len(candidates) != 1:
            return None
        matches.append(candidates[0])
    if len({code for code, path in matches}) != 1:
        return None
    code, path = matches[0]
    return {"code": code, "name": " ".join(path), "method": "official_metadata_name_hierarchy",
            "source": "KOSIS getMeta type=ITM · ITM_NM/UP_ITM_ID", "matchedParcelCount": len(parcels)}


def _kosis(client, query, parcels, as_of, requested_year):
    title = "KOSIS 가구주의 연령 및 가구원수별 가구(일반가구)-시군구"
    if _missing(client, ["kosis"]):
        return _component("credentials_missing", title, KOSIS_URL, missingCredentials=["kosis"])
    try:
        config = _arg(query, "kosisConfig", {}) or {}
        if isinstance(config, str):
            config = json.loads(config)
        if not isinstance(config, dict):
            raise ValueError("config")
        org = _text(config.get("orgId", "101"))
        table = _text(config.get("tblId", "DT_1JC1511"))
        if not re.fullmatch(r"[0-9A-Za-z_]+", org) or not re.fullmatch(r"[0-9A-Za-z_]+", table):
            raise ValueError("config")
        base = {"apiKey": client.require("kosis"), "orgId": org, "tblId": table, "format": "json", "jsonVD": "Y"}
        def meta(kind, **options):
            return _kosis_list(client.request("https://kosis.kr/openapi/statisticsData.do", {**base, "method": "getMeta", "type": kind, **options}))
        periods = meta("PRD", detail="Y")
        cutoff = min(int(requested_year), as_of.year - 1)
        years = sorted({_text(r.get("PRD_DE")) for r in periods if re.fullmatch(r"\d{4}", _text(r.get("PRD_DE"))) and int(r["PRD_DE"]) <= cutoff})[-5:]
        if not years:
            return _component("empty", title, KOSIS_URL, temporalBasis="statistical_period", warnings=["선택 기준일 이전의 완료 연도 자료를 확인하지 못했습니다."])
        metadata = meta("ITM")
        items = [r for r in metadata if r.get("OBJ_ID") == "ITEM"]
        classifications = [r for r in metadata if r.get("OBJ_ID") != "ITEM"]
        region = _text(config.get("objL1", _arg(query, "kosisRegionCode", "")))
        region_name = _text(_arg(query, "kosisRegionName", ""))
        region_match = None
        if not region and table == "DT_1JC1511":
            region_match = _match_kosis_region(classifications, parcels, region_name)
            if region_match:
                region, region_name = region_match["code"], region_match["name"]
        if not region:
            return _component("needs_configuration", title, KOSIS_URL,
                temporalBasis="statistical_period", referencePeriods=years,
                tableId=table, orgId=org,
                warnings=["필지 지역 명칭을 공식 통계 지역명·상위지역 계층과 유일하게 연결하지 못했습니다. 지역명이 다르거나 여러 통계지역에 걸친 선택은 보류합니다. 법정동/PNU 코드를 변환하지 않았습니다."],
                availableItems=[{k: r[k] for k in ("ITM_ID", "ITM_NM", "UNIT_NM", "OBJ_ID") if k in r} for r in items][:60],
                availableRegions=[{k: r[k] for k in ("ITM_ID", "ITM_NM", "OBJ_ID", "UP_ITM_ID") if k in r} for r in classifications][:300])
        query_params = {key: _text(config[key]) for key in ["objL"+str(i) for i in range(1, 9)] + ["itmId"] if config.get(key)}
        query_params["objL1"] = region
        # T100 is the actual official ITM response for this table, and is checked
        # at run time before use. No made-up table or classification codes.
        if "itmId" not in query_params:
            selected = [r for r in items if r.get("ITM_ID") == "T100" and r.get("ITM_NM") == "일반가구"] if table == "DT_1JC1511" else []
            if not selected:
                return _component("needs_configuration", title, KOSIS_URL, warnings=["공식 항목코드 itmId 설정이 필요합니다."], tableId=table)
            # Household totals, household-size counts and average size remain
            # separate series/units, using only returned official item codes.
            query_params["itmId"] = "+".join(_text(r["ITM_ID"]) for r in items)
        if table == "DT_1JC1511" and "objL2" not in query_params:
            totals = [r for r in classifications if _text(r.get("OBJ_ID_SN")) == "2"
                      and "연령" in _text(r.get("OBJ_NM")) and _text(r.get("ITM_NM")) in {"합계", "계", "전체", "총계"}]
            if len(totals) != 1:
                return _component("needs_configuration", title, KOSIS_URL, referencePeriods=years,
                    warnings=["가구주 연령 합계의 공식 분류코드(kosisConfig.objL2)를 확인해야 합니다."],
                    tableId=table, orgId=org)
            query_params["objL2"] = _text(totals[0]["ITM_ID"])
        payload = client.request("https://kosis.kr/openapi/Param/statisticsParameterData.do", {
            **base, **query_params, "method": "getList", "prdSe": "Y", "startPrdDe": years[0], "endPrdDe": years[-1], "smblChk": "Y"})
        data = _kosis_list(payload)
        rows, mismatched = [], 0
        for row in data:
            if _text(row.get("PRD_DE")) not in years:
                continue
            allowed_items = set(query_params["itmId"].split("+"))
            mismatched_dimension = any(value != "ALL" and _text(row.get("C"+key[4:])) not in set(value.split("+"))
                                       for key, value in query_params.items() if key.startswith("objL"))
            if (mismatched_dimension
                    or (row.get("TBL_ID") and _text(row["TBL_ID"]) != table)
                    or (row.get("ORG_ID") and _text(row["ORG_ID"]) != org)
                    or (query_params["itmId"] != "ALL" and row.get("ITM_ID") and _text(row["ITM_ID"]) not in allowed_items)):
                mismatched += 1
                continue
            clean = {key: row[key] for key in ("ORG_ID", "TBL_ID", "TBL_NM", "ITM_ID", "ITM_NM", "UNIT_NM", "PRD_SE", "PRD_DE", "DT", "LST_CHN_DE") if key in row}
            clean["value"] = _num(row.get("DT"))
            clean["dimensions"] = [{"code": _text(row.get("C"+str(i))), "name": _text(row.get("C"+str(i)+"_NM")),
                                    "classification": _text(row.get("C"+str(i)+"_OBJ_NM"))}
                                   for i in range(1, 9) if row.get("C"+str(i)) is not None]
            rows.append(clean)
        series = {}
        for row in rows:
            signature = (_text(row.get("ITM_ID")), tuple(d["code"] for d in row["dimensions"]))
            item = series.setdefault(signature, {"id": _text(row.get("ITM_ID")), "name": _text(row.get("ITM_NM")),
                                     "unit": _text(row.get("UNIT_NM")), "dimensions": row["dimensions"], "points": []})
            item["points"].append({"period": _text(row.get("PRD_DE")), "value": row["value"]})
        for item in series.values():
            item["points"].sort(key=lambda p: p["period"])
        return _component("partial" if mismatched else "success" if rows else "empty", title if table == "DT_1JC1511" else "KOSIS 지정 통계표", KOSIS_URL, rows,
            referencePeriods=sorted({_text(r.get("PRD_DE")) for r in rows}), temporalBasis="statistical_period_current_revision",
            tableId=table, orgId=org, configUsed=query_params, regionCode=region, regionName=region_name,
            regionMatch=region_match, series=list(series.values()), rejectedIdentityCount=mismatched,
            warnings=["통계표의 지역 단위 자료이며 선택 반경의 가구·인구 실적이 아닙니다.",
                      "일반가구와 주민등록 세대는 정의가 다릅니다. 결측은 0으로 채우지 않습니다.",
                      "행정구역 개편 전후 통계의 경계 동일성을 보장하지 않으며 연도별 원천 정의를 따릅니다.",
                      "현재 수정 내역이 반영될 수 있으며 분석 기준일 당시 공개본을 재현하지 않습니다."]
                     + (["요청 지역·통계표·항목과 일치하지 않는 반환 행을 제외했습니다."] if mismatched else []))
    except (ValueError, TypeError):
        return _component("needs_configuration", title, KOSIS_URL, warnings=["KOSIS 표·지역·항목 설정 형식을 확인해야 합니다."])
    except Exception as exc:
        return _error(exc, title, KOSIS_URL)


def _sgis(client, query, as_of, requested_year):
    title = "SGIS 인구·가구·주택 총괄"
    missing = _missing(client, ["sgisId", "sgisSecret"])
    if missing:
        return _component("credentials_missing", title, SGIS_URL, missingCredentials=missing,
                          warnings=["서비스 ID와 비밀값을 함께 준비한 후 접근 토큰을 발급받아야 합니다. 서비스 ID를 토큰으로 사용하지 않습니다."])
    adm = _text(_arg(query, "sgisAdmCd", ""))
    if not re.fullmatch(r"(?:\d{2}|\d{5}|\d{7})", adm):
        return _component("needs_configuration", title, SGIS_URL,
                          warnings=["해당 기준연도의 공식 SGIS 통계 지역코드 sgisAdmCd가 필요합니다. PNU에서 생성하지 않습니다."])
    year = min(int(requested_year), as_of.year - 1)
    try:
        auth = client.request("https://sgisapi.kostat.go.kr/OpenAPI3/auth/authentication.json", {
            "consumer_key": client.require("sgisId"), "consumer_secret": client.require("sgisSecret")})
        if not isinstance(auth, dict) or auth.get("errCd") not in (0, "0"):
            raise _UpstreamError("UPSTREAM_AUTH")
        token = auth.get("result", {}).get("accessToken")
        if not token:
            raise _UpstreamError("UPSTREAM_SCHEMA")
        payload = client.request("https://sgisapi.kostat.go.kr/OpenAPI3/stats/population.json", {
            "accessToken": token, "year": year, "adm_cd": adm, "low_search": "0"})
        if not isinstance(payload, dict) or payload.get("errCd") not in (0, "0"):
            raise _UpstreamError("UPSTREAM_REJECTED")
        data = payload.get("result", [])
        if not isinstance(data, list):
            raise _UpstreamError("UPSTREAM_SCHEMA")
        rows = []
        for row in data:
            if not isinstance(row, dict) or _text(row.get("adm_cd")) != adm:
                continue
            if row.get("year") is not None and _text(row["year"]) != str(year):
                continue
            rows.append({"adm_cd": adm, "adm_nm": _text(row.get("adm_nm")), "year": str(year),
                         **{key: _num(row.get(key)) for key in ("tot_ppltn", "tot_family", "tot_house", "avg_age", "ppltn_dnsty")}})
        return _component("success" if rows else "empty", title, SGIS_URL, rows,
                          temporalBasis="statistical_period_current_revision", referencePeriods=[str(year)] if rows else [],
                          warnings=["통계 지역코드에 해당하는 자료이며 선택 반경의 실적이 아닙니다.", "자료가 없는 기준연도를 다른 연도로 채우지 않습니다."],
                          units={"tot_ppltn": "명", "tot_family": "가구", "tot_house": "호", "avg_age": "세", "ppltn_dnsty": "명/㎢"})
    except Exception as exc:
        return _error(exc, title, SGIS_URL)


def _unavailable():
    entries = {
        "registry": ("등기·권리부담", "등기사항증명서 확인 필요", "https://www.iros.go.kr/"),
        "ownerNames": ("개인 소유자 성명", "현재 공개 속성 API에서 소유자 성명을 확보하지 않음", "https://www.iros.go.kr/"),
        "bookValue": ("위탁자 장부가", "위탁자 장부 확인 필요", ""),
        "appraisalValue": ("사업 감정평가액", "해당 사업 감정평가서 확인 필요", ""),
        "roadWidth": ("도로 폭·통행권", "공식 폭 속성과 통행권 자료 미확보. 도로접면 코드로 폭을 추정하지 않음", "https://www.vworld.kr/dev/v4apiRefer.do"),
        "traffic": ("교통량·이동시간", "해당 교통 실측자료 미확보. 직선거리로 교통량·이동시간을 대체하지 않음", ""),
        "demolition": ("철거·나대지·점유", "건물정보 미조회·0건으로 나대지나 철거 완료를 확정하지 않음", "https://www.data.go.kr/data/15134735/openapi.do"),
        "developmentPlan": ("개발계획·인허가", "공식 고시·사업단계·인허가 개별 확인 필요", "https://www.eum.go.kr/web/op/sv/svItemList.jsp"),
        "environmentalImpact": ("소음·악취·민원", "시설 존재만으로 피해·민원 발생 여부를 판단하지 않음", ""),
    }
    return {key: _component("unavailable", title, url, warnings=[note], manualEvidenceInput=False)
            for key, (title, note, url) in entries.items()}


def _demand_indicators(kosis):
    """Derive only unambiguous, same-region household measures; never sum rows."""
    region = _text(kosis.get("regionCode"))
    region_name = _text(kosis.get("regionName")) or "통계지역 미확정"
    config = kosis.get("configUsed") or {}
    rows = kosis.get("rows", [])
    years = sorted({_text(r.get("PRD_DE")) for r in rows if re.fullmatch(r"\d{4}", _text(r.get("PRD_DE")))})
    latest = years[-1] if years else None
    eligible = (kosis.get("status") == "success" and kosis.get("tableId") == "DT_1JC1511"
                and kosis.get("orgId") == "101" and region and region != "ALL" and "+" not in region)
    def one(item, name, year):
        if not eligible or not year:
            return None
        selected = []
        for row in rows:
            dims = row.get("dimensions", [])
            if (row.get("ITM_ID") != item or row.get("ITM_NM") != name or row.get("UNIT_NM") != "가구"
                    or _text(row.get("PRD_DE")) != year or len(dims) != 2 or dims[0].get("code") != region
                    or dims[1].get("name") not in {"합계", "계", "전체", "총계"}):
                continue
            if any(value == "ALL" or "+" in value or len(dims) < int(key[4:]) or dims[int(key[4:])-1].get("code") != value
                   for key, value in config.items() if key.startswith("objL")):
                continue
            selected.append(row)
        if len(selected) != 1:
            return None
        value = _num(selected[0].get("value"))
        return value if value is not None and value >= 0 else None
    total = one("T100", "일반가구", latest)
    singles = one("T210", "1인", latest)
    observed = [(year, one("T100", "일반가구", year)) for year in years]
    observed = [(year, value) for year, value in observed if value is not None]
    first_year, first_total = observed[0] if observed else (None, None)
    share = singles / total * 100 if total is not None and total > 0 and singles is not None and singles <= total else None
    change = (total / first_total - 1) * 100 if total is not None and first_total is not None and first_total > 0 and first_year != latest else None
    period = latest or "기준연도 미확보"
    change_period = first_year+"~"+latest if first_year and latest else "관측기간 미확보"
    base = {"sourceId": "kosis", "regionCode": region or None, "regionName": region_name,
            "scope": "공식 시군구 통계지역", "referenceYear": latest,
            "note": "일반가구 기준 공식 지역통계이며 선택 반경의 수요·분양성공률을 뜻하지 않습니다. 행을 합산하지 않았습니다."}
    values = [("householdsLatest", region_name+" 일반가구 수 ("+period+")", total, "가구", "T100 원천값"),
              ("onePersonHouseholdSharePct", region_name+" 1인가구 비중 ("+period+")", share, "%", "동일 연도 T210 / T100 × 100"),
              ("householdObservedChangePct", region_name+" 일반가구 증감률 ("+change_period+")", change, "%", "(관측 마지막해 T100 / 첫해 T100 - 1) × 100; 연평균 증가율 아님")]
    return [{**base, "id": ident, "label": label, "value": value, "unit": unit, "calculation": formula,
             "status": "success" if value is not None else kosis.get("status") if kosis.get("status") != "success" else "unavailable",
             "startYear": first_year if ident == "householdObservedChangePct" else latest,
             "endYear": latest} for ident, label, value, unit, formula in values]


def site_survey(client, query_dict):
    """Collect independent public components. Bad input raises ValueError pre-I/O."""
    query = dict(query_dict)
    as_of = dt.date.fromisoformat(_text(_arg(query, "asOf", dt.date.today().isoformat())))
    if as_of > dt.date.today():
        raise ValueError("분석 기준일은 미래일 수 없습니다.")
    year = int(_arg(query, "year", as_of.year))
    if not 2000 <= year <= as_of.year:
        raise ValueError("자료 기준연도는 2000년부터 분석 기준연도 사이여야 합니다.")
    pnus = list(dict.fromkeys(p.strip() for p in _text(_arg(query, "pnus", "")).split(",") if p.strip()))
    if len(pnus) > 50 or any(not re.fullmatch(r"\d{19}", pnu) for pnu in pnus):
        raise ValueError("선택 필지는 최대 50개, 19자리 PNU여야 합니다.")
    lon, lat = _num(_arg(query, "lon")), _num(_arg(query, "lat"))
    supplied_center = _arg(query, "lon") not in (None, "") or _arg(query, "lat") not in (None, "")
    if supplied_center and (lon is None or lat is None or not (124 <= lon <= 132 and 33 <= lat <= 39.5)):
        raise ValueError("한국 대상지의 경도·위도 좌표를 확인해야 합니다.")
    radius = _num(_arg(query, "radiusKm", 5))
    if radius is None or not 0 < radius <= 20:
        raise ValueError("조회 반경은 0km 초과 20km 이하여야 합니다.")
    parcels = []
    for pnu in pnus:
        try:
            parcel = client.parcel(pnu, year)
            if "officialLandPrice" not in parcel:
                parcel = enrich_parcel(client, parcel, year)
            parcels.append(parcel)
        except Exception as exc:
            error = _error(exc, "선택 필지 기본조사", "https://www.vworld.kr/dev/v4apiRefer.do")
            parcels.append({"pnu": pnu, "surveyStatus": error["status"], "surveyError": error,
                            "officialLandPrice": enrich_parcel(client, {"pnu": pnu}, year)["officialLandPrice"]})
    services, layers = {}, {}
    if supplied_center:
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [(key, pool.submit(_search_group, client, key, keyword, lon, lat, radius)) for key, keyword in GROUPS]
            layer_futures = [(spec[0], pool.submit(_layer, client, spec, lon, lat, radius)) for spec in ACTIVE_LAYERS]
            services = {key: future.result() for key, future in futures}
            layers = {key: future.result() for key, future in layer_futures}
    else:
        services = {key: _component("not_requested", "브이월드 장소 검색 · "+keyword, SEARCH_URL, warnings=["시설 검색에 대상지 중심점이 필요합니다."]) for key, keyword in GROUPS}
    items, candidates = [], []
    for group, component in services.items():
        grouped = group_facility_candidates(component["rows"], group)
        component.update(rows=grouped["items"], count=len(grouped["items"]),
                         candidates=grouped["candidates"], candidateCount=len(grouped["candidates"]),
                         excludedCandidateCount=grouped["excludedCount"], mergedCandidateCount=grouped["mergedCount"],
                         groupingRuleVersion=ENTITY_RULE_VERSION)
        if grouped["candidates"]:
            component["warnings"].append("원천 시설 분류와 본시설 명칭을 함께 확인한 검색 대표점만 집계합니다. 부속 장소·키워드 오탐은 제외하고 원자료와 사유를 보관합니다. 동명 본시설의 300m 이내 중복은 같은 지역일 때 후보로 묶되 공공하수처리시설 같은 일반명칭은 전체주소도 일치해야 합니다. 공식 시설 식별 판정이 아닙니다.")
        items.extend(grouped["items"])
        candidates.extend(grouped["candidates"])
    items.sort(key=lambda row: (row["distanceKm"], row["id"]))
    statuses = {s["status"] for s in services.values()}
    status = next(iter(statuses)) if len(statuses) == 1 else "success" if statuses <= {"success", "empty"} else "partial"
    facilities = {"status": status, "statusLabel": LABELS[status], "items": items, "candidates": candidates,
                  "candidateCount": len(candidates), "entityCandidateCount": len(items),
                  "groupingRuleVersion": ENTITY_RULE_VERSION, "allowedGroups": [group for group, _ in GROUPS],
                  "services": services, "referenceLayers": layers,
                  "distanceBands": facility_distance_bands(items, services, radius),
                  "featureCollection": {"type": "FeatureCollection", "features": [
                      {"type": "Feature", "id": row["id"], "geometry": {"type": "Point", "coordinates": [row["lon"], row["lat"]]}, "properties": row} for row in items]},
                  "referenceFeatureCollection": {"type": "FeatureCollection", "features": [f for layer in layers.values() for f in layer.get("features", [])]},
                  "distanceMethod": "WGS84 경위도 Haversine 직선거리, 지구평균반경 6371.0088km",
                  "centerBasis": "요청에 제공한 대상지 대표 중심점", "completeInventory": False,
                  "warnings": [CURRENT_NOTE, FACILITY_NOTE]}
    statistics = {"kosis": _kosis(client, query, parcels, as_of, year), "sgis": _sgis(client, query, as_of, year)}
    indicators = []
    for group, keyword in GROUPS:
        component = services[group]
        rows = component["rows"]
        indicators.append({"id": group+"NearestKm", "label": keyword+" 본시설 후보 대표점 중 최근접 직선거리", "value": min((r["distanceKm"] for r in rows), default=None),
                           "unit": "km", "status": component["status"], "sourceId": "vworld-place-"+group,
                           "note": "학교·산·하천·산업단지·하수처리장만 집계. 본시설 검색 대표점 기준이며 경계까지 거리·보행거리·이동시간이 아닙니다. 입구·주차장 등은 제외."})
    indicators.extend(_demand_indicators(statistics["kosis"]))
    sources = [{"id": "vworld-place-"+key, **{k: v for k, v in component.items() if k not in {"rows", "features", "candidates"}}} for key, component in services.items()]
    sources += [{"id": "vworld-layer-"+key, **{k: v for k, v in component.items() if k not in {"rows", "features"}}} for key, component in layers.items()]
    sources += [{"id": key, **{k: v for k, v in component.items() if k not in {"rows", "features"}}} for key, component in statistics.items()]
    sources += [{"id": "officialLandPrice-"+parcel["pnu"], "pnu": parcel["pnu"],
                 **{k: v for k, v in parcel["officialLandPrice"].items() if k != "rows"}}
                for parcel in parcels if parcel.get("officialLandPrice")]
    return exclude_retail_facilities({"query": {"pnus": pnus, "year": year, "asOf": as_of.isoformat(), "lon": lon, "lat": lat, "radiusKm": radius},
            "queriedAt": _now(), "parcels": parcels, "facilities": facilities, "statistics": statistics,
            "indicators": indicators, "unavailable": _unavailable(), "sources": sources,
            "warnings": [CURRENT_NOTE, "공개자료 조사는 등기 확인·현장조사·인허가 판단을 완료한 결과가 아닙니다."],
            "scoring": {"status": "not_configured", "score": None, "note": "사용자의 평가 방향·구간·가중치 설정 전에는 점수를 산출하지 않습니다."}})
