"""V3 deterministic land comparison. No network and no caller-derived profiles trusted."""
from __future__ import annotations

import copy
import json
import math
import re

RULES_VERSION = "land-match-v7-48-groups-1"
FALLBACK_POLICY = 'valid-other-groups-median'
FALLBACK_REASON = '동일 그룹 비교사례 없음 · 중앙값 대체'
# 토지 비교그룹 = 용도지역 8그룹 × 지목 6그룹 (같은 시군구·법정동 안에서 비교).
# 근거: 팀 문서 '토지실거래가 데이터 전처리 개선 내용' — 학습 모델(CatBoost)과 같은 분류.
ZONE_OTHER = "용도미지정 등"      # 용도미지정·개발제한구역·기타, 그리고 거래의 용도지역 누락
JIMOK_OTHER = "기타"              # 전·답·임야·대·공장용지 외 23개 지목, 그리고 거래의 지목 누락
JIMOK_GROUPS = ("전", "답", "임야", "대", "공장용지")
ZONE_GROUPS = ("전용주거지역", "일반주거지역", "준주거지역", "상업지역", "공업지역", "녹지지역", "비도시지역", ZONE_OTHER)
# 거래 자료의 용도지역 값 중 '용도미지정 등'으로 묶는 이름 (필지 토지이용계획의 개발제한구역은 용도구역이라 해당 없음)
OTHER_ZONE_NAMES = {"용도미지정", "개발제한구역", "기타"}
MISSING_ZONE_NAMES = {'', '-', '미상', '미정', '미확인', '미지정', '없음', '용도미지정', '용도지역미지정', '용도지역미확인', '용도지역미상', '용도지역없음'}
MISSING_JIMOK_NAMES = {'', '-', '미상', '미정', '미확인', '미지정', '없음', '지목미상', '지목미확인', '지목없음'}
# Exact MOLIT/KLIS names only. Facilities such as 완충녹지 are not 녹지지역.
ZONE_CODES = {
    "UQA100": ("주거지역", "주거"), "UQA110": ("전용주거지역", "주거"),
    "UQA111": ("제1종전용주거지역", "주거"), "UQA112": ("제2종전용주거지역", "주거"),
    "UQA120": ("일반주거지역", "주거"), "UQA121": ("제1종일반주거지역", "주거"),
    "UQA122": ("제2종일반주거지역", "주거"), "UQA123": ("제3종일반주거지역", "주거"),
    "UQA130": ("준주거지역", "주거"), "UQA200": ("상업지역", "상업"),
    "UQA210": ("중심상업지역", "상업"), "UQA220": ("일반상업지역", "상업"),
    "UQA230": ("근린상업지역", "상업"), "UQA240": ("유통상업지역", "상업"),
    "UQA300": ("공업지역", "공업"), "UQA310": ("전용공업지역", "공업"),
    "UQA320": ("일반공업지역", "공업"), "UQA330": ("준공업지역", "공업"),
    "UQA400": ("녹지지역", "녹지"), "UQA410": ("보전녹지지역", "녹지"),
    "UQA420": ("생산녹지지역", "녹지"), "UQA430": ("자연녹지지역", "녹지"),
    "UQB001": ("관리지역", "관리"), "UQB100": ("계획관리지역", "관리"),
    "UQB200": ("생산관리지역", "관리"), "UQB300": ("보전관리지역", "관리"),
    "UQC001": ("농림지역", "농림"), "UQD001": ("자연환경보전지역", "자연환경보전"),
}
ZONE_NAMES = {name: (code, broad) for code, (name, broad) in ZONE_CODES.items()}
# 용도지역 코드 → 8그룹. UQA100(주거지역, 세부 미구분)은 전용·일반·준주거 중 어디인지 알 수 없어 넣지 않는다.
ZONE_GROUP_OF_CODE = {
    "UQA110": "전용주거지역", "UQA111": "전용주거지역", "UQA112": "전용주거지역",
    "UQA120": "일반주거지역", "UQA121": "일반주거지역", "UQA122": "일반주거지역", "UQA123": "일반주거지역",
    "UQA130": "준주거지역",
    "UQA200": "상업지역", "UQA210": "상업지역", "UQA220": "상업지역", "UQA230": "상업지역", "UQA240": "상업지역",
    "UQA300": "공업지역", "UQA310": "공업지역", "UQA320": "공업지역", "UQA330": "공업지역",
    "UQA400": "녹지지역", "UQA410": "녹지지역", "UQA420": "녹지지역", "UQA430": "녹지지역",
    "UQB001": "비도시지역", "UQB100": "비도시지역", "UQB200": "비도시지역", "UQB300": "비도시지역",
    "UQC001": "비도시지역", "UQD001": "비도시지역",
}
JIMOK_NAMES = "전 답 과수원 목장용지 임야 광천지 염전 대 공장용지 학교용지 주차장 주유소용지 창고용지 도로 철도용지 제방 하천 구거 유지 양어장 수도용지 공원 체육용지 유원지 종교용지 사적지 묘지 잡종지".split()
JIMOK_CODES = {str(i + 1).zfill(2): name for i, name in enumerate(JIMOK_NAMES)}


def _text(value):
    return re.sub(r"\s+", "", str(value or ""))


def classify_zone(value, code=None):
    raw, code = copy.deepcopy(value) if value is not None else "", str(code or "").strip()
    name = _text(value)
    if name == "자연환경보전": name = "자연환경보전지역"
    named = ZONE_NAMES.get(name)
    coded = ZONE_CODES.get(code)
    if coded and name and (not named or named[1] != coded[1] or name != coded[0]):
        return {"status": "conflict", "raw": raw, "code": code, "broadClass": None, "matchKey": None}
    if code and not coded and named:
        return {"status": "conflict", "raw": raw, "code": code, "broadClass": None, "matchKey": None}
    broad = coded[1] if coded else named[1] if named and not code else None
    resolved = code or (named[0] if named else None)
    group = ZONE_GROUP_OF_CODE.get(resolved) if broad else None
    return {"status": "ready" if group else "unknown", "raw": raw,
            "code": resolved, "broadClass": broad,
            "matchKey": group}


def classify_jimok(value, code=None):
    raw, name, code = copy.deepcopy(value) if value is not None else "", _text(value), str(code or "").strip()
    if name == "대지": name = "대"
    coded = JIMOK_CODES.get(code.zfill(2)) if code else None
    conflict = bool(code and ((not coded and name in JIMOK_NAMES) or (coded and name and coded != name)))
    canonical = None if conflict else coded or (name if name in JIMOK_NAMES and not code else None)
    return {"status": "conflict" if conflict else "ready" if canonical else "unknown", "raw": raw,
            "code": code or None, "name": canonical,
            "matchKey": canonical if canonical in JIMOK_GROUPS else JIMOK_OTHER if canonical else None}


def _missing_value(value, names):
    return value is None or isinstance(value, str) and _text(value) in names


def classify_transaction_zone(value, code=None):
    """거래 자료의 용도미지정·개발제한구역·기타는 '용도미지정 등' 그룹. 진짜 누락도 그 그룹에 '미확인'으로 넣는다."""
    result = classify_zone(value, code)
    if result['status'] == 'unknown' and not code and _text(value) in OTHER_ZONE_NAMES:
        result.update(status='ready', broadClass=ZONE_OTHER, matchKey=ZONE_OTHER)
    elif result['status'] == 'unknown' and not code and _missing_value(value, MISSING_ZONE_NAMES):
        result.update(status='missing', matchKey=ZONE_OTHER)
    return result


def classify_transaction_jimok(value, code=None):
    result = classify_jimok(value, code)
    if result['status'] == 'unknown' and not code and _missing_value(value, MISSING_JIMOK_NAMES):
        result.update(status='missing', matchKey=JIMOK_OTHER)
    return result


def land_group_label(zone, jimok):
    return zone + ' · ' + jimok


def _classification_status(result):
    return 'known' if result['status'] == 'ready' else 'missing' if result['status'] == 'missing' else 'unclassified'


def parcel_profile(parcel):
    """Use current register and plan only; annual characteristics remain reference."""
    reasons, zones, adjacent, categories = [], [], [], []
    raw_attrs = parcel.get("attributes")
    attrs = raw_attrs if isinstance(raw_attrs, dict) else {}
    if raw_attrs is not None and not isinstance(raw_attrs, dict): reasons.append("필지 속성 원자료 형식 오류")
    def component(name, label):
        raw = attrs.get(name)
        source = raw if isinstance(raw, dict) else {}
        raw_rows = source.get("rows", [])
        malformed = (raw is not None and not isinstance(raw, dict)) or not isinstance(raw_rows, list) or any(not isinstance(row, dict) for row in raw_rows)
        if malformed: reasons.append(label + " 원자료 행 형식 오류")
        rows = [row for row in raw_rows if isinstance(row, dict)] if isinstance(raw_rows, list) else []
        return source, rows, copy.deepcopy(raw_rows)
    register, reg_rows, reg_raw = component("landRegister", "토지임야대장")
    planning, zone_rows, zone_raw = component("landUse", "토지이용계획")
    pnu = str(parcel.get("pnu") or "")
    if not re.fullmatch(r"\d{19}", pnu): reasons.append("19자리 필지고유번호 미확정")
    if any(str(row.get("pnu")) != pnu for row in [*reg_rows, *zone_rows] if row.get("pnu")):
        reasons.append("선택 필지와 속성 원자료 PNU 불일치")
    if register.get("status") in ("조회 실패", "failed", "partial") or not reg_rows:
        reasons.append("현재 토지임야대장 지목 미확보")
    else:
        for row in reg_rows:
            category = classify_transaction_jimok(row.get("lndcgrCodeNm"), row.get("lndcgrCode"))
            categories.append(category)
            if category["status"] not in {'ready', 'missing'}: reasons.append("대장 지목 코드·명칭 미확정")
            if category['status'] == 'missing' and register.get('status') not in {'호출 확인', 'complete', 'ready', 'success'}:
                reasons.append('지목 누락을 확인할 현재 대장 조회 완료 근거 미확보')
    if planning.get("status") in ("조회 실패", "failed", "partial") or not zone_rows:
        reasons.append("현재 토지이용계획 용도지역 미확보")
    else:
        for row in zone_rows:
            zone = classify_zone(row.get("prposAreaDstrcCodeNm"), row.get("prposAreaDstrcCode"))
            # Unknown facilities/overlays do not become zoning evidence.
            if zone["status"] == "unknown":
                if str(row.get("prposAreaDstrcCode") or "").startswith(("UQA", "UQB", "UQC", "UQD")) and row.get("prposAreaDstrcCode") not in {"UQA01X", "UQA001"}:
                    if str(row.get('cnflcAt') or '') == '3' and str(row.get('cnflcAtNm') or '').strip() in ('', '접함'):
                        adjacent.append(copy.deepcopy(row))
                    else:
                        reasons.append("분류되지 않은 용도지역 코드")
                continue
            relation, relation_name = str(row.get("cnflcAt") or ""), str(row.get("cnflcAtNm") or "").strip()
            expected = {"1": "포함", "2": "저촉", "3": "접함"}.get(relation)
            if expected is None or (relation_name and relation_name != expected):
                reasons.append("용도지역 포함·저촉·접함 관계 미확정")
                continue
            if relation == "3":
                adjacent.append(copy.deepcopy(row))
                continue
            if zone["status"] != "ready": reasons.append("용도지역 코드·명칭 불일치")
            else: zones.append(zone)
    zone_keys = sorted({z["matchKey"] for z in zones if z["matchKey"]})
    category_names = sorted({j["name"] for j in categories if j["name"]})
    category_keys = sorted({j['matchKey'] for j in categories if j['matchKey']})
    missing_category = any(j['status'] == 'missing' for j in categories)
    if not zone_keys: reasons.append("선택 필지의 적용 용도지역 미확정")
    if len(zone_keys) > 1: reasons.append("혼합 용도지역·면적 배분 미확인")
    if not category_keys: reasons.append("선택 필지의 지목 미확정")
    if len(category_names) > 1 or (missing_category and category_names): reasons.append("대장 지목이 여러 값으로 확인됨")
    reasons = list(dict.fromkeys(reasons))
    status = "ready" if not reasons else "ambiguous" if len(zone_keys) > 1 or len(category_names) > 1 or any("불일치" in x for x in reasons) else "missing"
    source = {"zoning": "current-land-use-plan", "jimok": "current-land-register", "historicalReconstruction": False,
              "planningStatus": planning.get("status", "미확보"), "registerStatus": register.get("status", "미확보"),
              "planningQueriedAt": planning.get("queriedAt"), "registerQueriedAt": register.get("queriedAt"),
              "planningUpdatedAt": sorted({str(r.get("lastUpdtDt")) for r in zone_rows if r.get("lastUpdtDt")}),
              "registerUpdatedAt": sorted({str(r.get("lastUpdtDt")) for r in reg_rows if r.get("lastUpdtDt")})}
    fingerprint = json.dumps([RULES_VERSION, str(parcel.get("pnu") or ""), status, zone_keys, category_names, reasons], ensure_ascii=False, separators=(",", ":"))
    return {"pnu": str(parcel.get("pnu") or ""), "status": status, "ruleVersion": RULES_VERSION,
            "zoneMatchKey": zone_keys[0] if len(zone_keys) == 1 and not reasons else None,
            "jimokMatchKey": category_keys[0] if len(category_keys) == 1 and not reasons else None,
            "zoneBroadClasses": sorted({z["broadClass"] for z in zones}), "jimokRaw": category_names,
            "jimokStatus": 'missing' if missing_category else 'known' if category_names else 'unclassified',
            "jimokGroupKeys": category_keys,
            "zoneRawRows": zone_raw, "jimokRawRows": reg_raw,
            "adjacentRows": adjacent, "sourceBasis": source, "reasons": reasons, "fingerprint": fingerprint}


def parcel_area_profile(parcel):
    """Classifications plus independently recomputed, mandatory V5 allocation."""
    from server.domain.boundary import recompute_boundary
    profile = parcel_profile(parcel)
    allocation = recompute_boundary(parcel)
    reasons = [r for r in profile['reasons'] if r != '혼합 용도지역·면적 배분 미확인']
    reasons.extend(allocation['reasons'])
    jimok = profile['jimokGroupKeys'][0] if len(profile['jimokGroupKeys']) == 1 else None
    if allocation['status'] != 'ready' and not allocation['reasons']: reasons.append('필지·용도지역 경계 확인 필요')
    profile.update(status='missing' if reasons else 'ready', reasons=list(dict.fromkeys(reasons)),
                   boundaryStatus=allocation['status'], areaAllocations=[],
                   zoneMatchKey=profile['zoneMatchKey'] if not reasons else None,
                   jimokMatchKey=jimok if not reasons else None)
    if not reasons:
        profile['areaAllocations'] = [{
            'allocationId': part['allocationId'], 'zoneName': part['zoneName'], 'zoneCode': part['zoneCode'],
            'zoneMatchKey': part['zoneMatchKey'], 'ratio': part['ratio'], 'areaM2': part['allocatedAreaM2'],
            'geometryAreaM2': part['geometryAreaM2'], 'geometry': part['geometry']}
            for part in allocation['parts'] if not part.get('pricingExcluded')]
        keys = {part['zoneMatchKey'] for part in profile['areaAllocations']}
        profile['zoneMatchKey'] = next(iter(keys)) if len(keys) == 1 else None
    return profile


def _reference_targets(parcels):
    """Current plan/register can support reference samples without valid geometry."""
    groups = {}
    for parcel in parcels:
        profile = parcel_profile(parcel)
        if any(r != '혼합 용도지역·면적 배분 미확인' for r in profile['reasons']) or len(profile['jimokGroupKeys']) != 1: continue
        jimok_key = profile['jimokGroupKeys'][0]
        for row in profile['zoneRawRows']:
            zone = classify_zone(row.get('prposAreaDstrcCodeNm'), row.get('prposAreaDstrcCode'))
            if zone['status'] != 'ready' or str(row.get('cnflcAt')) not in {'1', '2'}: continue
            gid = f"{zone['matchKey']}|{jimok_key}"
            groups.setdefault(gid, {'id': gid, 'label': land_group_label(zone['matchKey'], jimok_key), 'zoneMatchKey': zone['matchKey'],
                'jimokMatchKey': jimok_key, 'points': [], 'caseIds': [], 'unknownZoneCount': 0,
                'knownZoneCount': 0, 'unknownJimokCount': 0, 'knownJimokCount': 0, 'referenceOnly': True})
    return groups


def _add_reference_case(groups, case, decision, base_reasons, positive):
    zone = classify_transaction_zone(case.get('landUse'), case.get('landUseCode'))
    jimok = classify_transaction_jimok(case.get('jimok'), case.get('jimokCode'))
    missing_zone = zone['status'] == 'missing'
    reasons = list(base_reasons)
    if jimok['status'] not in {'ready', 'missing'}: reasons.append('거래 지목 코드·명칭 미확정')
    if zone['status'] not in {'ready', 'missing'}: reasons.append('거래 용도지역 분류 미확정 · 단순 누락과 구분')
    matches = [g for g in groups.values() if g['jimokMatchKey'] == jimok['matchKey'] and g['zoneMatchKey'] == zone['matchKey']]
    if not matches: reasons.append('선택 필지의 용도지역·지목 참고군과 불일치' if groups else '선택 필지의 현재 분류 확인 필요')
    area, price = positive(case.get('areaM2')), positive(case.get('priceManwon'))
    unit = price * 10000 / area if area and price else None
    if positive(unit) is None: reasons.append('유효한 거래 단가 미확보')
    decision.update(referenceEligible=not reasons, referenceGroupIds=[g['id'] for g in matches] if not reasons else [],
                    referenceReasons=list(dict.fromkeys(reasons)), zoningStatus=_classification_status(zone), jimokStatus=_classification_status(jimok))
    if reasons: return
    for group in matches:
        group['points'].append({'id': decision['id'], 'label': str(case.get('date') or decision['id']), 'unitPriceWonM2': unit,
            'zoningStatus': decision['zoningStatus'], 'jimokStatus': decision['jimokStatus'], 'landUse': str(case.get('landUse') or ''), 'jimok': str(case.get('jimok') or ''),
            'referenceOnly': True, 'caseIds': [decision['id']]})
        group['caseIds'].append(decision['id'])
        group['unknownZoneCount' if missing_zone else 'knownZoneCount'] += 1
        group['unknownJimokCount' if jimok['status'] == 'missing' else 'knownJimokCount'] += 1


def land_completeness(profiles, groups, assignments, complete, extra_reasons=()):
    """Explain a held total without treating confirmed subtotals as total costs."""
    priced = {g['id'] for g in groups if isinstance(g.get('representativeWon'), (int, float)) and not isinstance(g.get('representativeWon'), bool) and math.isfinite(g['representativeWon'])}
    parcels = []
    for profile in profiles:
        parts = [a for a in assignments if a['pnu'] == profile['pnu'] and a.get('groupId')]
        priced_parts = [a for a in parts if a['groupId'] in priced]
        full = profile['status'] == 'ready' and bool(parts) and len(parts) == len(priced_parts)
        reasons = [*profile.get('reasons', []), *[a['groupId'].replace('|', ' · ') + ' 비교사례 단가 미산출' for a in parts if a['groupId'] not in priced]]
        parcels.append({'pnu': profile['pnu'], 'status': 'priced' if full else 'partial' if priced_parts else 'held', 'reasons': reasons})
    reasons = [*[r for r in extra_reasons if r], *[r for p in parcels for r in p['reasons']], *([] if profiles else ['개발 대상 필지 미선택'])]
    return {'complete': complete, 'parcelCount': len(profiles),
        'classificationReadyParcelCount': sum(p['status'] == 'ready' for p in profiles),
        'classificationHeldParcelCount': sum(p['status'] != 'ready' for p in profiles),
        'pricedParcelCount': sum(p['status'] == 'priced' for p in parcels),
        'partiallyPricedParcelCount': sum(p['status'] == 'partial' for p in parcels),
        'unpricedParcelCount': sum(p['status'] != 'priced' for p in parcels),
        'groupCount': len(groups), 'pricedGroupCount': len(priced), 'unpricedGroupCount': len(groups) - len(priced),
        'parcelRows': parcels, 'reasons': list(dict.fromkeys(reasons))}


def calculate_land(inputs, development, *, stats, context, date_reason, incomplete, positive, adjustment=1):
    """Evaluate immutable evidence and explicit manual exclusions, then sum cohorts."""
    method = inputs.get("assumptions", {}).get("landMethod", "median")
    if method not in {"mean", "median"}: raise ValueError("토지 대표값은 mean 또는 median이어야 합니다.")
    filters = inputs.get("comparisonFilters") or {}
    scope = filters.get("landScope", (context or {}).get("query", {}).get("landScope", "dong"))
    if scope not in {"dong", "sgg"}: raise ValueError("토지 비교 범위는 dong 또는 sgg여야 합니다.")
    reason = (context or {}).get("reason")
    query = (context or {}).get("query") or {}
    profiles, groups, assignments, seen_parcels = [], {}, [], set()
    for parcel in inputs.get("parcels", []):
        pnu = str(parcel.get("pnu") or "")
        if pnu in seen_parcels: continue
        seen_parcels.add(pnu)
        profile = parcel_area_profile(parcel)
        profiles.append(profile)
        area = positive(parcel.get("areaM2"))
        if profile['status'] != 'ready':
            assignments.append({'pnu': pnu, 'groupId': None, 'areaM2': area, 'status': profile['status'], 'reasons': profile['reasons']})
        for part in profile['areaAllocations']:
            group_id = f"{part['zoneMatchKey']}|{profile['jimokMatchKey']}"
            assignments.append({'pnu': pnu, 'groupId': group_id, 'areaM2': part['areaM2'], 'status': 'ready', 'reasons': [],
                **{k: part[k] for k in ('allocationId', 'zoneName', 'zoneCode', 'zoneMatchKey', 'ratio', 'geometryAreaM2', 'geometry')},
                'jimokMatchKey': profile['jimokMatchKey']})
            group = groups.setdefault(group_id, {"id": group_id, "label": land_group_label(part['zoneMatchKey'], profile['jimokMatchKey']), "zoneMatchKey": part["zoneMatchKey"], "jimokMatchKey": profile["jimokMatchKey"], "areaM2": 0., "missingArea": False, "parcelPnus": [], "points": [], "caseIds": [], 'unknownZoneCount': 0, 'knownZoneCount': 0, 'unknownJimokCount': 0, 'knownJimokCount': 0})
            if pnu not in group['parcelPnus']: group['parcelPnus'].append(pnu)
            group['areaM2'] += part['areaM2']
    reference_groups = _reference_targets(inputs.get('parcels', []))
    decisions, excluded, seen_cases, donor_cases = [], [], set(), []
    for i, case in enumerate(inputs.get("comparables", {}).get("landCases", [])):
        cid = str(case.get("id") or f"land-{i}")
        reasons = []
        if reason: reasons.append(reason)
        if incomplete: reasons.append("부분 수집: 전체 표본 판정 보류")
        if cid in seen_cases: reasons.append("같은 거래 식별자 중복")
        seen_cases.add(cid)
        if case.get("cancelled") is True or case.get("cancellationDate"): reasons.append("취소 거래")
        if case.get("shareTrade") is True or str(case.get("shareDealingType") or "").strip() not in {"", "전체", "전체거래", "전체 거래", "N", "0", "-"}: reasons.append("지분 거래 또는 거래 범위 확인 필요")
        if case.get("sourceEligible") is False: reasons.extend(case.get("sourceExclusionReasons") or ["수집 검증 제외"])
        elif "sourceEligible" not in case and (case.get("apiEligible") is False or (not case.get("manualExclusion") and case.get("baseEligible", case.get("eligible")) is False)):
            reasons.append(case.get("baseExclusionReason") or case.get("exclusionReason") or "수집 검증 제외")
        if case.get("userExcluded") or case.get("manualExclusion"): reasons.append(case.get("userExclusionReason") or case.get("manualExclusionReason") or case.get("baseExclusionReason") or case.get("exclusionReason") or "사용자 제외")
        area, price = positive(case.get("areaM2")), positive(case.get("priceManwon"))
        if not area or not price: reasons.append("양수 금액·거래면적 미확보")
        date_issue = date_reason(case) if not reason else None
        if date_issue: reasons.append(date_issue)
        if context:
            from server.domain.analysis.comparables import _same_dong
            if str(case.get("sggCode") or "") != str(query.get("sgg") or ""):
                reasons.append("선택 필지의 시군구 밖 거래 또는 지역 미확정")
            elif scope == "dong" and not _same_dong(case.get("dong"), query.get("dong")):
                reasons.append("선택 필지의 법정동 밖 토지거래 또는 거래 지역 미확정")
        if str(filters.get('jimok') or '').strip() and str(case.get('jimok') or '').strip() != str(filters['jimok']).strip(): reasons.append('사용자 지목 필터 불일치')
        if str(filters.get('landUse') or '').strip() and str(filters['landUse']).strip() not in str(case.get('landUse') or ''): reasons.append('사용자 용도지역 필터 불일치')
        base_reasons = list(reasons)
        zone = classify_transaction_zone(case.get('landUse'), case.get('landUseCode'))
        jimok = classify_transaction_jimok(case.get('jimok'), case.get('jimokCode'))
        if zone["status"] not in {'ready', 'missing'}: reasons.append("거래 용도지역 코드·명칭 미확정")
        if jimok["status"] not in {'ready', 'missing'}: reasons.append("거래 지목 코드·명칭 미확정")
        group_id = f"{zone['matchKey']}|{jimok['matchKey']}" if zone["matchKey"] and jimok["matchKey"] else None
        unit = price * 10000 / area if area and price else None
        if positive(unit) is None: reasons.append('유효한 거래 단가 미확보')
        donor_eligible = not reasons
        if donor_eligible:
            donor_cases.append({'id': cid, 'groupId': group_id, 'unitPriceWonM2': unit})
        if group_id not in groups: reasons.append("선택 필지의 용도지역·지목 비교군과 불일치")
        reasons = list(dict.fromkeys(reasons))
        decision = {"id": cid, "eligible": not reasons, "groupId": group_id if group_id in groups else None, "reasons": reasons, "exclusionReason": " · ".join(reasons), "zoneMatchKey": zone["matchKey"], "jimokMatchKey": jimok["matchKey"], 'classificationBasis': {'ruleVersion': RULES_VERSION, 'zone': copy.deepcopy(zone), 'jimok': copy.deepcopy(jimok), 'missingPolicy': 'missing-zone-fourth-group;missing-jimok-other-group', 'fallbackUsed': False}}
        decision.update(fallbackEligible=donor_eligible, fallbackGroupIds=[])
        decisions.append(decision)
        _add_reference_case(reference_groups, case, decision, base_reasons, positive)
        if reasons: excluded.append({"id": cid, "reason": decision["exclusionReason"], "reasons": reasons})
        else:
            group = groups[group_id]
            base = None if group["missingArea"] else unit * group["areaM2"]
            group["points"].append({"id": cid, "label": str(case.get("date") or cid), "unitPriceWonM2": unit, "baseValueWon": base, "valueWon": base * adjustment if base is not None else None, "caseIds": [cid], 'zoningStatus': decision['zoningStatus'], 'jimokStatus': decision['jimokStatus'], 'landUse': str(case.get('landUse') or ''), 'jimok': str(case.get('jimok') or '')})
            group["caseIds"].append(cid)
            group['unknownZoneCount' if zone['status'] == 'missing' else 'knownZoneCount'] += 1
            group['unknownJimokCount' if jimok['status'] == 'missing' else 'knownJimokCount'] += 1
    for group in groups.values():
        if group.pop("missingArea"): group["areaM2"] = None
        group["stats"] = stats([p["valueWon"] for p in group["points"] if p["valueWon"] is not None])
        group["baseStats"] = stats([p["baseValueWon"] for p in group["points"] if p["baseValueWon"] is not None])
        group["unitPriceStats"] = stats([p["unitPriceWonM2"] for p in group["points"]])
        group['fallback'] = {'used': False}
        unit = group['unitPriceStats'][method]
        if not group['points'] and group['areaM2'] is not None and not reason and not incomplete:
            donors = [case for case in donor_cases if case['groupId'] != group['id']]
            if donors:
                unit = stats([case['unitPriceWonM2'] for case in donors])['median']
                source_groups = list(dict.fromkeys(case['groupId'] for case in donors))
                group['fallback'] = {'used': True, 'policy': FALLBACK_POLICY, 'reason': FALLBACK_REASON,
                    'sourceCaseCount': len(donors), 'sourceGroupCount': len(source_groups),
                    'sourceGroupIds': source_groups, 'sourceCaseIds': [case['id'] for case in donors],
                    'unitPriceWonM2': unit}
        group['representativeUnitPriceWonM2'] = unit
        group["representativeWon"] = unit * group['areaM2'] * adjustment if unit is not None and group['areaM2'] is not None else None
        group["status"] = "토지사례 재조회 필요" if reason else "대장 면적 미확보" if group["areaM2"] is None else FALLBACK_REASON if group['fallback']['used'] else group["stats"]["status"]
    rows = list(groups.values())
    for assignment in assignments:
        if assignment['status'] != 'ready': continue
        group = groups[assignment['groupId']]
        unit = group['representativeUnitPriceWonM2']
        assignment['fallback'] = copy.deepcopy(group['fallback'])
        assignment['representativeUnitPriceWonM2'] = unit
        assignment['appliedUnitPriceWonM2'] = unit * adjustment if unit is not None and group['representativeWon'] is not None else None
        assignment['representativeWon'] = assignment['appliedUnitPriceWonM2'] * assignment['areaM2'] if assignment['appliedUnitPriceWonM2'] is not None else None
    boundary_parts = [{**row, 'allocatedAreaM2': row['areaM2'], 'estimatedWon': row['representativeWon'],
        'pricingStatus': FALLBACK_REASON if row['fallback']['used'] else '산출 완료' if row['representativeWon'] is not None else '비교사례 확인 필요'} for row in assignments if row['status'] == 'ready']
    complete = bool(profiles) and all(p["status"] == "ready" for p in profiles) and bool(rows) and all(g["representativeWon"] is not None for g in rows) and not reason and not incomplete
    partial = sum(g["representativeWon"] for g in rows if g["representativeWon"] is not None)
    covered = sum(g["areaM2"] or 0 for g in rows if g["representativeWon"] is not None)
    total = development.get("landAreaM2")
    fallback_groups = [group for group in rows if group['fallback']['used']]
    source_case_ids = list(dict.fromkeys(cid for group in fallback_groups for cid in group['fallback']['sourceCaseIds']))
    source_group_ids = list(dict.fromkeys(gid for group in fallback_groups for gid in group['fallback']['sourceGroupIds']))
    fallback = {'used': bool(fallback_groups), 'policy': FALLBACK_POLICY, 'groupCount': len(fallback_groups),
        'parcelCount': len({pnu for group in fallback_groups for pnu in group['parcelPnus']}),
        'sourceCaseCount': len(source_case_ids), 'sourceGroupCount': len(source_group_ids),
        'sourceCaseIds': source_case_ids, 'sourceGroupIds': source_group_ids,
        'groupIds': [group['id'] for group in fallback_groups]}
    for decision in decisions:
        decision['fallbackGroupIds'] = [group['id'] for group in fallback_groups if decision['fallbackEligible'] and decision['id'] in group['fallback']['sourceCaseIds']]
        decision['classificationBasis']['fallbackUsed'] = bool(decision['fallbackGroupIds'])
    reference_rows = []
    for group in reference_groups.values():
        row = {**group, 'stats': stats([point['unitPriceWonM2'] for point in group['points']])}
        matched = groups.get(group['id'])
        row['fallback'] = copy.deepcopy(matched['fallback']) if matched else {'used': False}
        row['representativeUnitPriceWonM2'] = matched['representativeUnitPriceWonM2'] if matched else row['stats'][method]
        reference_rows.append(row)
    completeness = land_completeness(profiles, rows, assignments, complete, [reason, '토지거래 수집 미완료' if incomplete else None])
    return {"groups": rows, "referenceGroups": reference_rows, "referencePolicy": 'same-48-groups-v1', "representativeWon": partial if complete else None, "partialRepresentativeWon": partial if any(g["representativeWon"] is not None for g in rows) else None,
            "completeness": completeness, "fallback": fallback,
            "excluded": excluded, "caseDecisions": decisions, "parcelProfiles": profiles, "parcelAssignments": assignments, "boundaryParts": boundary_parts,
            "coverage": {"coveredAreaM2": covered, "totalAreaM2": total, "coveredPct": covered / total * 100 if total else None, "unresolvedParcelCount": sum(p["status"] != "ready" for p in profiles)},
            "comparisonReason": reason, "comparisonScope": scope, "ruleVersion": RULES_VERSION, "matchingMode": "custom-48-groups", "method": method,
            'matchingPolicy': {'zoneGroups': list(ZONE_GROUPS), 'jimokGroups': [*JIMOK_GROUPS, JIMOK_OTHER], 'missingZoneGroup': ZONE_OTHER, 'missingJimokGroup': JIMOK_OTHER, 'noCasePolicy': FALLBACK_POLICY, 'boundaryPolicy': 'hold-missing-or-conflicting-evidence'},
            "label": "사용자 지정 비교군 대표액 합계" if len(rows) > 1 else "예상 토지매입대금",
            "status": "토지사례 재조회 필요" if reason else "부분 수집 · 판정 보류" if incomplete else "산출 완료 · 중앙값 대체 포함" if complete and fallback['used'] else "산출 완료" if complete else "필지 분류·비교사례 확인 필요",
            "sourceStatus": "공개자료 기반 추정", "assumption": "같은 지역·용도지역·지목 비교군 우선. 동일 그룹 사례가 없으면 다른 유효 그룹 거래 단가 중앙값 대체. 경제적 동질성·개발 가능성 보장이 아님"}
