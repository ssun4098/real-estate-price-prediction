"""V5 parcel / zoning overlay. Recompute from public geometry, never client totals.

EPSG:5179 (metres) is used for intersection and areas. Invalid polygons are held;
no buffer(0), guessed CRS, hole filling, gap normalization or nearest-zone fill.
"""
from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
import math
import re
import threading
import struct
from collections import OrderedDict

VERSION = 'boundary-overlay-v1'
PARCEL_LAYER = 'LP_PA_CBND_BUBUN'
ZONE_LAYERS = ('LT_C_UQ111', 'LT_C_UQ112', 'LT_C_UQ113', 'LT_C_UQ114')
LAYER_LABELS = ('도시지역', '관리지역', '농림지역', '자연환경보전지역')
POLICY = {'absoluteToleranceM2': .01, 'relativeTolerance': 1e-8,
          'inputCrs': 'EPSG:4326', 'areaCrs': 'EPSG:5179',
          'allocationBasis': '대장 면적 × 경계 교차면적 / 필지 경계면적',
          'gapNormalization': False, 'invalidGeometryRepair': False,
          'adjacentResidualPolicy': 'aggregate-within-existing-tolerance-no-reallocation'}
_cache = OrderedDict()
_cache_lock = threading.RLock()
_BOUND_FIELDS = ('version', 'pnu', 'status', 'source', 'attributeBasis', 'parcelFeature',
    'parcelGeometry', 'sourceFeatures', 'registerAreaM2', 'parcelGeometryAreaM2',
    'coverageRatio', 'overlapAreaM2', 'gapAreaM2', 'parts', 'policy')


def evidence_binding(allocation):
    """Portable evidence consistency checksum, not an authenticity signature."""
    def canonical(value):
        if value is None: return 'z'
        if isinstance(value, bool): return 't' if value else 'f'
        if isinstance(value, (int, float)): return 'n' + struct.pack('>d', float(value)).hex()
        if isinstance(value, str): return 's' + json.dumps(value, ensure_ascii=False, separators=(',', ':'))
        if isinstance(value, (list, tuple)): return 'a[' + ','.join(canonical(v) for v in value) + ']'
        if isinstance(value, dict): return 'o{' + ','.join(canonical(str(k)) + ':' + canonical(value[k]) for k in sorted(value)) + '}'
        raise ValueError('경계 근거 형식 오류')
    state = 14695981039346656037
    for byte in canonical({key: allocation.get(key) for key in _BOUND_FIELDS}).encode('utf-8'):
        state = ((state ^ byte) * 1099511628211) & 0xffffffffffffffff
    return {'algorithm': 'fnv1a64-ieee754-v1', 'value': f'{state:016x}'}


def _number(value):
    if isinstance(value, bool): return None
    try: n = float(str(value).replace(',', ''))
    except (TypeError, ValueError): return None
    return n if math.isfinite(n) else None


def attribute_basis(parcel):
    attrs = parcel.get('attributes') if isinstance(parcel.get('attributes'), dict) else {}
    def rows(name):
        value = attrs.get(name) or {}
        return value.get('rows', []) if isinstance(value, dict) and isinstance(value.get('rows', []), list) else []
    zones = [{k: row.get(k) for k in ('pnu', 'prposAreaDstrcCode', 'prposAreaDstrcCodeNm', 'cnflcAt', 'cnflcAtNm', 'lastUpdtDt')}
             for row in rows('landUse') if isinstance(row, dict)]
    register = [{k: row.get(k) for k in ('pnu', 'lndpclAr', 'lndcgrCode', 'lndcgrCodeNm', 'lastUpdtDt')}
                for row in rows('landRegister') if isinstance(row, dict)]
    return {'pnu': str(parcel.get('pnu') or ''),
            'landUse': sorted(zones, key=lambda x: json.dumps(x, sort_keys=True, ensure_ascii=False)),
            'landRegister': sorted(register, key=lambda x: json.dumps(x, sort_keys=True, ensure_ascii=False))}


def _geometry_engine():
    from server.domain.geometry import load_geometry
    load_geometry()
    from shapely.geometry import shape, mapping
    from shapely.ops import transform, unary_union
    from pyproj import Transformer
    return shape, mapping, transform, unary_union, Transformer


def _coordinates(geometry):
    value = geometry.get('coordinates', [])
    def visit(item):
        if isinstance(item, (list, tuple)) and item and isinstance(item[0], (int, float)):
            if len(item) != 2 or any(isinstance(v, bool) or not math.isfinite(v) for v in item): raise ValueError('경계 좌표 형식 오류')
            x, y = item
            if not (120 <= x <= 134 and 30 <= y <= 40): raise ValueError('경계 좌표계 또는 국내 범위 불일치')
            return 1
        if not isinstance(item, (list, tuple)): raise ValueError('경계 좌표 형식 오류')
        return sum(visit(v) for v in item)
    count = visit(value)
    if count < 4 or count > 500000: raise ValueError('경계 꼭짓점 수 확인 필요')


def _polygon(geometry, shape):
    if not isinstance(geometry, dict) or geometry.get('type') not in ('Polygon', 'MultiPolygon'):
        raise ValueError('면 경계 미확보')
    _coordinates(geometry)
    polygons = [geometry['coordinates']] if geometry['type'] == 'Polygon' else geometry['coordinates']
    if any(not polygon or any(len(ring) < 4 or ring[0] != ring[-1] for ring in polygon) for polygon in polygons):
        raise ValueError('닫히지 않은 경계 링')
    obj = shape(geometry)
    if obj.is_empty or not obj.is_valid or obj.area <= 0:
        raise ValueError('유효하지 않은 경계: 자가교차·빈 면 등 확인 필요')
    return obj


def _polygonal(geometry, union):
    """Zero-area shared edges are not map polygons; keep every positive-area part."""
    if geometry.geom_type in ('Polygon', 'MultiPolygon'): return geometry
    return union([_polygonal(g, union) for g in getattr(geometry, 'geoms', [])
                  if not g.is_empty and g.area > 0])


def tolerated_adjacent_zones(areas, expected, adjacent, tolerance):
    """Only declared-adjacent residuals, in aggregate, can use numeric tolerance."""
    extra = set(areas) - set(expected)
    if not expected or not extra or not extra.issubset(set(adjacent)):
        return set()
    values = [areas[code] for code in extra]
    if any(not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) or value < 0 for value in values):
        return set()
    return extra if sum(values) <= tolerance else set()


def recompute_boundary(parcel, evidence=None):
    raw = evidence if isinstance(evidence, dict) else parcel.get('boundaryAllocation')
    if not isinstance(raw, dict):
        result = _recompute_boundary(parcel, evidence)
        result['evidenceBinding'] = evidence_binding(result)
        return result
    # Cache is content-addressed over original polygons AND current attributes;
    # client-derived ratios/status never authorize the cache entry.
    try:
        attrs = parcel.get('attributes') if isinstance(parcel.get('attributes'), dict) else {}
        relevant = {'pnu': parcel.get('pnu'), 'areaM2': parcel.get('areaM2'),
            'attributes': {key: attrs.get(key) for key in ('landRegister', 'landUse')}, 'raw': raw}
        key = hashlib.sha256(json.dumps(relevant, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()
    except (TypeError, ValueError): return _recompute_boundary(parcel, evidence)
    with _cache_lock:
        if key in _cache:
            _cache.move_to_end(key)
            return copy.deepcopy(_cache[key])
    result = _recompute_boundary(parcel, evidence)
    result['evidenceBinding'] = evidence_binding(result)
    with _cache_lock:
        _cache[key] = copy.deepcopy(result)
        while len(_cache) > 24: _cache.popitem(last=False)
    return result


def _recompute_boundary(parcel, evidence=None):
    """Return recomputed allocation; supplied ratios/status/parts are discarded."""
    from server.domain.land import classify_zone
    raw = evidence if isinstance(evidence, dict) else parcel.get('boundaryAllocation')
    raw = raw if isinstance(raw, dict) else {}
    pnu = str(parcel.get('pnu') or '')
    source = copy.deepcopy(raw.get('source') or {}) if isinstance(raw.get('source'), dict) else {}
    result = {'version': VERSION, 'pnu': pnu, 'status': 'held', 'reasons': [],
              'parts': [], 'source': source, 'sources': copy.deepcopy(raw.get('sources') or []),
              'queriedAt': raw.get('queriedAt'), 'policy': copy.deepcopy(POLICY),
              'parcelGeometry': copy.deepcopy(raw.get('parcelGeometry')),
              'parcelFeature': copy.deepcopy(raw.get('parcelFeature')),
              'sourceFeatures': copy.deepcopy(raw.get('sourceFeatures') or []),
              'attributeBasis': attribute_basis(parcel), 'registerAreaM2': None,
              'parcelGeometryAreaM2': None, 'coverageRatio': None, 'overlapAreaM2': None,
              'gapAreaM2': None, 'toleranceM2': None, 'allocatedAreaM2': None,
              'note': '연속지적도·용도지역 경계를 이용한 사업성 검토 참고값이며 법적 측량성과가 아닙니다.'}
    reasons = result['reasons']
    if not raw: reasons.append('필지·용도지역 경계 조회 필요'); return result
    if raw.get('version') != VERSION or raw.get('pnu') != pnu or not re.fullmatch(r'\d{19}', pnu):
        reasons.append('경계 자료의 버전 또는 PNU 불일치')
    if source.get('crs') != POLICY['inputCrs'] or source.get('parcelLayer') != PARCEL_LAYER or not source.get('queriedAt'):
        reasons.append('경계 출처 또는 좌표계 미확인')
    source['areaCrs'] = POLICY['areaCrs']
    layers = source.get('zoningLayers')
    if source.get('complete') is not True or not isinstance(layers, list) or any(not isinstance(x, str) for x in layers) or set(layers) != set(ZONE_LAYERS):
        reasons.append('필지·용도지역 경계 페이지 수집 미완료')
    pages = source.get('pages')
    if not isinstance(pages, list) or any(not isinstance(r, dict) or not isinstance(r.get('layer'), str) for r in pages) or {r.get('layer') for r in pages} != {PARCEL_LAYER, *ZONE_LAYERS} or len(pages) != len(ZONE_LAYERS) + 1:
        reasons.append('경계 페이지 검증 근거 미확보')
    else:
        for record in pages:
            if not isinstance(record, dict) or record.get('complete') is not True or record.get('totalCount') != record.get('rawCount') or not isinstance(record.get('pageCount'), int) or record['pageCount'] < 1:
                reasons.append('경계 페이지 누락 또는 건수 불일치'); break
    attrs = parcel.get('attributes') if isinstance(parcel.get('attributes'), dict) else {}
    register = attrs.get('landRegister') if isinstance(attrs.get('landRegister'), dict) else {}
    regrows = register.get('rows', []) if isinstance(register, dict) else []
    areas = [_number(row.get('lndpclAr')) for row in regrows if isinstance(row, dict)]
    if len(areas) != 1 or areas[0] is None or areas[0] <= 0 or register.get('status') in ('조회 실패', 'failed', 'partial'):
        reasons.append('현재 대장 면적 미확보 또는 충돌')
    else:
        result['registerAreaM2'] = areas[0]
        selected = _number(parcel.get('areaM2'))
        if selected is None or abs(selected - areas[0]) > max(.01, areas[0] * 1e-8):
            reasons.append('계산용 면적과 현재 대장 면적 불일치')
    if raw.get('attributeBasis') != result['attributeBasis']:
        reasons.append('경계 조회 당시와 현재 필지 속성 불일치: 재조회 필요')
    feature = raw.get('parcelFeature')
    if not isinstance(feature, dict) or not isinstance(feature.get('properties'), dict) or str(feature['properties'].get('pnu')) != pnu or feature.get('geometry') != raw.get('parcelGeometry'):
        reasons.append('필지 경계 원자료의 PNU·도형 불일치')
    source_features = raw.get('sourceFeatures')
    if not isinstance(source_features, list) or any(not isinstance(f, dict) for f in source_features):
        reasons.append('용도지역 경계 원자료 형식 오류'); source_features = []
    if isinstance(pages, list):
        for record in pages:
            if isinstance(record, dict) and record.get('layer') in ZONE_LAYERS:
                if record.get('uniqueCount') != sum(f.get('sourceLayer') == record['layer'] for f in source_features):
                    reasons.append('저장된 용도지역 경계 건수 불일치')
    try:
        shape, mapping, transform, unary_union, Transformer = _geometry_engine()
    except (ImportError, RuntimeError):
        reasons.append('경계 계산 도구 미준비: V5 실행 환경의 Shapely·pyproj 설치 확인')
        return result
    try:
        parcel_poly = _polygon(raw.get('parcelGeometry'), shape)
        forward = Transformer.from_crs('EPSG:4326', 'EPSG:5179', always_xy=True).transform
        backward = Transformer.from_crs('EPSG:5179', 'EPSG:4326', always_xy=True).transform
        target = transform(forward, parcel_poly)
        if not target.is_valid: raise ValueError('투영 후 필지 경계 오류')
        area = float(target.area)
        tolerance = max(POLICY['absoluteToleranceM2'], area * POLICY['relativeTolerance'])
        result.update(parcelGeometryAreaM2=area, toleranceM2=tolerance)
        by_zone, names, seen_ids = {}, {}, {}
        for feature in source_features:
            if feature.get('sourceLayer') not in ZONE_LAYERS: raise ValueError('확인되지 않은 용도지역 레이어')
            geometry = _polygon(feature.get('geometry'), shape)
            # Invalid nearby candidates are deliberately held too: their relation
            # cannot safely be inferred from a broken polygon.
            projected = transform(forward, geometry)
            if not projected.is_valid: raise ValueError('투영 후 용도지역 경계 오류')
            clipped = _polygonal(target.intersection(projected), unary_union)
            if clipped.is_empty or clipped.area <= 1e-9: continue
            props = feature.get('properties') or {}
            zone = classify_zone(props.get('uname'), props.get('zoneCode'))
            if zone['status'] != 'ready': raise ValueError('교차한 용도지역 명칭·코드 미확정')
            key = zone['code']
            fid = (feature.get('sourceLayer'), str(feature.get('id') or ''))
            signature = hashlib.sha256(json.dumps(feature.get('geometry'), sort_keys=True).encode()).hexdigest()
            if fid[1] and fid in seen_ids and seen_ids[fid] != signature: raise ValueError('동일 경계 식별자의 도형 충돌')
            seen_ids[fid] = signature
            by_zone.setdefault(key, []).append(clipped)
            names[key] = zone
        merged = {code: unary_union(polys) for code, polys in by_zone.items()}
        union = unary_union(list(merged.values()))
        covered = float(union.area)
        gap = max(0., area - covered)
        overlap = max(0., sum(g.area for g in merged.values()) - covered)
        result.update(coverageRatio=covered / area, gapAreaM2=gap, overlapAreaM2=overlap)
        if gap > tolerance: reasons.append('필지 내부 용도지역 경계 누락')
        if overlap > tolerance: reasons.append('서로 다른 용도지역 경계 중복·충돌')
        expected, adjacent = set(), set()
        planning = attrs.get('landUse') or {}
        rows = planning.get('rows', []) if isinstance(planning, dict) else []
        for row in rows:
            if not isinstance(row, dict): continue
            zone = classify_zone(row.get('prposAreaDstrcCodeNm'), row.get('prposAreaDstrcCode'))
            relation, relation_name = str(row.get('cnflcAt') or ''), str(row.get('cnflcAtNm') or '').strip()
            valid_relation = not relation_name or relation_name == {'1': '포함', '2': '저촉', '3': '접함'}.get(relation)
            if zone['status'] == 'ready' and valid_relation:
                if relation in ('1', '2'): expected.add(zone['code'])
                elif relation == '3': adjacent.add(zone['code'])
        actual = set(merged)
        ignored = tolerated_adjacent_zones({code: geom.area for code, geom in merged.items()}, expected, adjacent, tolerance)
        if actual - ignored != expected: reasons.append('현재 토지이용계획 속성과 교차 경계의 용도지역 불일치')
        for code, geom in sorted(merged.items()):
            zone = names[code]
            if geom.equals(target): geom = target
            ratio = float(geom.area / area)
            result['parts'].append({'allocationId': pnu + ':' + code,
                'zoneName': zone['raw'], 'zoneCode': code, 'zoneMatchKey': zone['matchKey'],
                'geometry': json.loads(json.dumps(mapping(transform(backward, geom)))), 'geometryAreaM2': float(geom.area),
                'ratio': ratio, 'allocatedAreaM2': result['registerAreaM2'] * ratio if result['registerAreaM2'] else None,
                **({'pricingExcluded': True, 'exclusionReason': '접함 경계의 허용오차 이내 미세 교차', 'sourceRelation': '접함'} if code in ignored else {})})
        result['allocatedAreaM2'] = sum(part['allocatedAreaM2'] or 0 for part in result['parts'])
        result['geometryRegisterDifferenceM2'] = area - result['registerAreaM2'] if result['registerAreaM2'] else None
    except ValueError as exc:
        reasons.append(str(exc))
    except Exception:
        reasons.append('경계 교차 연산 오류: 원자료 확인 필요')
    result['reasons'] = list(dict.fromkeys(reasons))
    result['status'] = 'held' if result['reasons'] else 'ready'
    return result


def _request_features(client, layer, *, pnu=None, bbox=None):
    features, seen, total, raw_count, page_count, page_signatures = [], {}, None, 0, 0, set()
    for page in range(1, 101):
        params = {'service': 'data', 'request': 'GetFeature', 'version': '2.0',
            'data': layer, 'key': client.require('vworld'), 'domain': client.domain,
            'format': 'json', 'crs': 'EPSG:4326', 'size': 100, 'page': page,
            'geometry': 'true', 'attribute': 'true'}
        if pnu: params['attrFilter'] = 'pnu:=:' + pnu
        else: params['geomFilter'] = 'BOX(' + ','.join(str(x) for x in bbox) + ')'
        payload = client.request('https://api.vworld.kr/req/data', params)
        response = payload.get('response', {})
        page_count += 1
        if response.get('status') == 'NOT_FOUND':
            if total not in (None, 0): raise ValueError('경계 페이지 수집 중단')
            total = 0; break
        if response.get('status') != 'OK': raise ValueError('경계 API 조회 실패: 인증·한도·응답 상태 확인')
        rows = response.get('result', {}).get('featureCollection', {}).get('features')
        if not isinstance(rows, list) or any(not isinstance(f, dict) for f in rows): raise ValueError('경계 API 응답 형식 오류')
        count = _number(response.get('record', {}).get('total'))
        current = _number(response.get('record', {}).get('current'))
        if count is None or count < 0 or int(count) != count or current != len(rows): raise ValueError('경계 API 응답 건수 불일치')
        if total is not None and total != int(count): raise ValueError('경계 페이지 조회 중 전체 건수 변경')
        actual_page = response.get('page', {}).get('current')
        if actual_page is not None and _number(actual_page) != page: raise ValueError('경계 페이지 번호 불일치')
        page_signature = json.dumps(rows, sort_keys=True, ensure_ascii=False)
        if rows and page_signature in page_signatures: raise ValueError('경계 페이지 반복 수신')
        page_signatures.add(page_signature)
        total = int(count); raw_count += len(rows)
        for f in rows:
            prop = f.get('properties') or {}
            fields = ('pnu', 'gosi_year', 'gosi_month') if pnu else ('uname', 'sido_name', 'sigg_name', 'dnum', 'dyear')
            feature = {'type': 'Feature', 'id': f.get('id'), 'sourceLayer': layer,
                       'geometry': copy.deepcopy(f.get('geometry')),
                       'properties': {k: prop[k] for k in fields if k in prop}}
            if pnu and str(prop.get('pnu')) != pnu: raise ValueError('경계 API 선택 PNU 불일치')
            signature = json.dumps(feature, sort_keys=True, ensure_ascii=False)
            if signature not in seen:
                seen[signature] = True; features.append(feature)
        if raw_count == total: break
        if raw_count > total or not rows: raise ValueError('경계 페이지 누락 또는 초과')
    if raw_count != total: raise ValueError('경계 페이지 수집 한도 초과')
    return features, {'layer': layer, 'complete': True, 'totalCount': total,
                      'rawCount': raw_count, 'uniqueCount': len(features), 'pageCount': page_count}


def collect_boundary(client, parcel):
    """Fetch by PNU, then all four published zoning layers covering its bbox."""
    pnu = str(parcel.get('pnu') or '')
    if not re.fullmatch(r'\d{19}', pnu): raise ValueError('19자리 PNU가 필요합니다.')
    queried = dt.datetime.now(dt.timezone.utc).isoformat()
    evidence = {'version': VERSION, 'pnu': pnu, 'sourceFeatures': [],
        'attributeBasis': attribute_basis(parcel), 'queriedAt': queried,
        'source': {'provider': 'VWorld / 국토교통부', 'parcelLayer': PARCEL_LAYER,
            'zoningLayers': list(ZONE_LAYERS), 'crs': 'EPSG:4326', 'areaCrs': 'EPSG:5179',
            'queriedAt': queried, 'complete': False, 'pages': []},
        'sources': [{'label': '연속지적도형정보', 'layer': PARCEL_LAYER,
            'url': 'https://www.data.go.kr/data/15123899/openapi.do', 'queriedAt': queried}] +
            [{'label': label, 'layer': layer, 'queriedAt': queried,
              'url': 'https://www.vworld.kr/dev/v4dv_2ddataguide2_s002.do?svcIde=' + layer[5:].lower()}
             for layer, label in zip(ZONE_LAYERS, LAYER_LABELS)]}
    try:
        parcel_features, record = _request_features(client, PARCEL_LAYER, pnu=pnu)
        evidence['source']['pages'].append(record)
        if len(parcel_features) != 1: raise ValueError('동일 PNU 필지 경계 누락 또는 중복')
        evidence['parcelFeature'] = parcel_features[0]
        evidence['parcelGeometry'] = parcel_features[0]['geometry']
        shape, _, _, _, _ = _geometry_engine()
        bbox = _polygon(evidence['parcelGeometry'], shape).bounds
        for layer in ZONE_LAYERS:
            features, record = _request_features(client, layer, bbox=bbox)
            evidence['sourceFeatures'].extend(features)
            evidence['source']['pages'].append(record)
        evidence['source']['complete'] = True
    except (ImportError, RuntimeError):
        evidence['collectionError'] = '경계 계산 도구 미준비: Shapely·pyproj 설치 확인'
    except ValueError as exc:
        evidence['collectionError'] = str(exc)
    except Exception:
        evidence['collectionError'] = '경계 API 조회 실패: 인증·한도·네트워크 상태 확인'
    result = recompute_boundary(parcel, evidence)
    if evidence.get('collectionError'):
        result['status'] = 'held'
        result['reasons'] = list(dict.fromkeys([evidence['collectionError'], *result['reasons']]))
        result['collectionError'] = evidence['collectionError']
        result['evidenceBinding'] = evidence_binding(result)
    return result
