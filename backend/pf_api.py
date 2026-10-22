"""PF Study public data adapters. Standard library only; never persist credentials.

All public-price fields are excluded by positive response-field selection. API
response errors are deliberately replaced by messages which cannot contain keys.
"""
from __future__ import annotations

import calendar
import copy
import datetime as dt
import json
import math
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import OrderedDict, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pf_regions import RegionCatalog
from pf_land import parcel_profile, RULES_VERSION
from pf_land_store import LandStore, LandStoreError

VERSION = "4.0.0"
DEFAULT_DOMAIN = "http://127.0.0.1:4175"
MAX_BODY = 16 * 1024 * 1024
COVERAGE_SEED = {"minMonth":"2020-02","maxMonth":"2026-10","observedMinDate":"2020-02-04","observedMaxDate":"2026-10-08","checkedAt":"2026-10-09T10:58:29.879402+00:00","status":"observed_seed","officialCoverageGuarantee":False,"sourceUrl":"https://www.data.go.kr/data/15098547/openapi.do","dateBasis":"모집공고일"}
LAND_START_DATE = "2006-01-01"
REVENUE_START_DATE = "2020-02-04"
KOREA_TIMEZONE = dt.timezone(dt.timedelta(hours=9))


def korea_today():
    """Avoid the PC's configured timezone changing the monthly cutoff."""
    return dt.datetime.now(KOREA_TIMEZONE).date()


def rolling_period(today=None):
    """Exactly 60 complete calendar months; the current month's first is excluded."""
    today = today or korea_today()
    if isinstance(today, dt.datetime):
        today = today.astimezone(KOREA_TIMEZONE).date()
    boundary = today.replace(day=1)
    start = boundary.replace(year=boundary.year-5)
    end = boundary-dt.timedelta(days=1)
    return {"periodMode":"rolling60", "start":start.strftime("%Y-%m"),
            "end":end.strftime("%Y-%m"), "startDate":start.isoformat(),
            "endDate":end.isoformat(), "endExclusive":boundary.isoformat(),
            "asOf":today.isoformat(), "timezone":"Asia/Seoul", "months":60}


def selected_region(sgg, selected_pnus, legal_dong_code=None):
    """Verify selected PNU context before any price-data request is issued."""
    if isinstance(selected_pnus, str):
        selected_pnus = selected_pnus.split(",")
    if not isinstance(selected_pnus, (list, tuple)) or not selected_pnus:
        raise ValueError("개발 대상 필지를 선택하고 필지의 지역코드를 확인한 뒤 비교사례를 조회하세요.")
    pnus = sorted(set(str(p).strip() for p in selected_pnus))
    if any(not re.fullmatch(r"\d{19}", p) for p in pnus):
        raise ValueError("선택 필지의 19자리 PNU를 확인하세요.")
    codes = {p[:10] for p in pnus}
    if len(codes) != 1:
        raise ValueError("선택 필지가 서로 다른 법정동에 걸쳐 있어 비교사례 조회를 보류합니다.")
    code = next(iter(codes))
    if sgg != code[:5] or (legal_dong_code and legal_dong_code != code):
        raise ValueError("선택 필지의 PNU와 시군구·법정동코드가 일치하지 않습니다.")
    return {"selectedPnus":pnus, "legalDongCode":code, "sgg":code[:5]}


class ApiError(Exception):
    def __init__(self, code, message, status=502):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def number(value):
    if value is None or isinstance(value, bool) or str(value).strip() == "":
        return None
    try:
        result = float(str(value).replace(",", "").strip())
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def text(value):
    return "" if value is None else str(value).strip()


def canonical_dong(value):
    """Keep an 읍/면 + 리 pair, and never substring-match unrelated places."""
    parts=text(value).split()
    if not parts:return ""
    last=parts[-1]
    if last.endswith("리"):
        if len(parts)>1 and parts[-2].endswith(("읍","면")):
            return parts[-2]+" "+last
        return last
    return last


def same_dong(left,right):
    """Caller must separately constrain/validate sgg code."""
    a,b=canonical_dong(left),canonical_dong(right)
    # A bare 리 can name several villages within one 시군구. Its parent is
    # mandatory; no automatic broadening to any village with the same suffix.
    if (a.endswith("리") and " " not in a) or (b.endswith("리") and " " not in b):
        return False
    return bool(a and b and a==b)


PROVINCE_ALIASES = {
    "서울":"서울특별시", "서울시":"서울특별시", "부산":"부산광역시", "부산시":"부산광역시",
    "대구":"대구광역시", "대구시":"대구광역시", "인천":"인천광역시", "인천시":"인천광역시",
    "광주":"광주광역시", "광주시":"광주광역시", "대전":"대전광역시", "대전시":"대전광역시",
    "울산":"울산광역시", "울산시":"울산광역시", "세종":"세종특별자치시", "세종시":"세종특별자치시",
    "경기":"경기도", "강원":"강원특별자치도", "강원도":"강원특별자치도",
    "충북":"충청북도", "충남":"충청남도", "전북":"전북특별자치도", "전라북도":"전북특별자치도",
    "전남":"전라남도", "경북":"경상북도", "경남":"경상남도", "제주":"제주특별자치도", "제주도":"제주특별자치도",
}


def normalized_address(value):
    value=re.sub(r"\([^)]*\)","",text(value))
    parts=value.split()
    if parts:parts[0]=PROVINCE_ALIASES.get(parts[0],parts[0])
    return " ".join(parts)


def address_identity(value):
    """Compare a numbered address, never a dong name or geocoder fallback centroid.

    Building names and '번지 일대' are annotations. A first numbered parcel in
    an '일대' announcement is a representative point, not the entire site.
    """
    value=normalized_address(value)
    for kind,ending in (("PARCEL",r"(?:동|가|읍|면|리)"),("ROAD",r"(?:대로|로|길)")):
        match=re.match(r"^(.+?\s[^\s]+"+ending+r")\s+(산\s*)?(\d+)(?:\s*-\s*(\d+))?(?:번지)?(?=\s|,|$)",value)
        if match:
            prefix,mountain,main,sub=match.groups()
            if mountain and kind!="PARCEL":continue
            core=f"{prefix} {'산 ' if mountain else ''}{int(main)}"+(f"-{int(sub)}" if sub and int(sub) else "")
            return kind,core
    return None


GEOCODER_SOURCE = "https://www.vworld.kr/dev/v4dv_geocoderguide2_s001.do"
GEOCODING_LABELS = {"V":"공급주소 일치 확인", "C":"좌표 후보·검토 필요",
                    "U":"위치 미확정", "E":"호출 실패", "P":"대기·미처리"}


def parcel_identity(value):
    """A complete numbered parcel, including its administration and mountain flag."""
    identity = address_identity(value)
    if not identity or identity[0] != "PARCEL":
        return None
    parts = identity[1].split()
    if parts[0] not in set(PROVINCE_ALIASES.values()):
        return None
    if parts[0] != "세종특별자치시" and (len(parts) < 4 or not parts[1].endswith(("시", "군", "구"))):
        return None
    return identity


def compatible_parcel_structure(full_identity, structure_identity):
    """VWorld may omit the 리 in structure.level4L while refined.text has it.

    Accept only that precise loss of detail. Province, city, 읍/면, mountain
    flag, and parcel numbers must still agree, and the caller separately checks
    the complete refined address against the original supply address.
    """
    if full_identity == structure_identity: return True
    if not full_identity or not structure_identity or full_identity[0] != "PARCEL" or structure_identity[0] != "PARCEL": return False
    full = full_identity[1]
    reduced = re.sub(r"(?<=읍)\s+[^\s]+리(?=\s+(?:산\s+)?\d+(?:-\d+)?$)", "", full)
    reduced = re.sub(r"(?<=면)\s+[^\s]+리(?=\s+(?:산\s+)?\d+(?:-\d+)?$)", "", reduced)
    return reduced != full and reduced == structure_identity[1]


def parcel_candidates(address):
    """Extract only explicit parcel numbers; never manufacture a block's parcel.

    A parenthesized '서초동 123' may inherit the explicit outer 시도/시군구.
    No location lookup or road-address conversion occurs here.
    """
    outer = re.sub(r"\([^)]*\)", " ", text(address))
    parts = normalized_address(outer).split()
    admin = []
    if parts and parts[0] in set(PROVINCE_ALIASES.values()):
        admin = parts[:1]
        if len(parts) > 1 and parts[1].endswith(("시", "군", "구")):
            admin.append(parts[1])
            if len(parts) > 2 and parts[1].endswith("시") and parts[2].endswith("구"):
                admin.append(parts[2])
    result = []
    for fragment in [outer, *re.findall(r"\(([^()]*)\)", text(address))]:
        identity = parcel_identity(fragment)
        if identity is None and admin:
            identity = parcel_identity(" ".join(admin) + " " + fragment.strip())
        if identity and identity[1] not in result:
            result.append(identity[1])
    return result


def geocoding_stats(outcomes):
    counts = {state: 0 for state in GEOCODING_LABELS}
    for row in outcomes:
        counts[row["geocodingState"]] += 1
    total = len(outcomes)
    returned = counts["V"] + counts["C"]
    ratio = lambda count: count / total * 100 if total else None
    return {"D": total, **counts, "denominator": total,
            "denominatorBasis": "좌표 변환 대상으로 확정한 고유 공고 수",
            "coordinateReturnedCount": returned, "verifiedCount": counts["V"],
            "coordinateReturnedPercent": ratio(returned), "verifiedPercent": ratio(counts["V"]),
            "unresolvedPercent": ratio(counts["U"]), "errorPercent": ratio(counts["E"]),
            "processedPercent": ratio(total - counts["P"]),
            "errorEventCount": sum(len(row.get("geocodingErrors", [])) for row in outcomes),
            "originalVerifiedCount": sum(row["geocodingState"] == "V" and row.get("geocodingMethod") == "original" for row in outcomes),
            "candidateVerifiedCount": sum(row["geocodingState"] == "V" and row.get("geocodingMethod") == "parcel_candidate" for row in outcomes),
            "withinRadiusCount": sum(row.get("withinRadius") is True for row in outcomes),
            "eligibleNoticeCount": sum(row.get("eligible") is True for row in outcomes),
            "realtimeOnly": True, "persistencePolicy": "session_only"}


def haversine_km(lon1,lat1,lon2,lat2):
    a,b=math.radians(lat1),math.radians(lat2)
    h=math.sin((b-a)/2)**2+math.cos(a)*math.cos(b)*math.sin(math.radians(lon2-lon1)/2)**2
    return 6371.0088*2*math.asin(min(1,math.sqrt(max(0,h))))


def radius_bounds(lon,lat,radius_km):
    lon,lat,radius_km=number(lon),number(lat),number(radius_km)
    if lon is None or lat is None or not 120<lon<134 or not 30<lat<40:
        raise ValueError("반경 비교에는 선택 부지의 유효한 중심 좌표가 필요합니다.")
    if radius_km is None or not 0.1<=radius_km<=10:
        raise ValueError("분양사례 검색 반경은 0.1~10km로 입력하세요.")
    angle=radius_km/6371.0088
    dy=math.degrees(angle);dx=math.degrees(math.asin(math.sin(angle)/math.cos(math.radians(lat))))
    return [lon-dx,lat-dy,lon+dx,lat+dy]


def months(start, end, *, max_months=60):
    try:
        a, b = dt.date.fromisoformat(start + "-01"), dt.date.fromisoformat(end + "-01")
    except (ValueError, TypeError):
        raise ValueError("조회 기간은 YYYY-MM 형식이어야 합니다.") from None
    count = (b.year-a.year)*12+b.month-a.month+1
    if count < 1 or (max_months is not None and count > max_months):
        raise ValueError("조회 기간은 시작월부터 종료월까지 1~60개월이어야 합니다.")
    return [f"{(a.year*12+a.month-1+i)//12:04d}{(a.month-1+i)%12+1:02d}" for i in range(count)]


def comparison_period(start,end,min_month,max_month,as_of,label,*,automatic=False):
    # Bounds must be checked before constructing a potentially long month list.
    if start<min_month or end>max_month:
        raise ValueError(f"{label} 조회 가능 범위는 {min_month}~{max_month}입니다. 자료 범위를 갱신하거나 기간을 다시 선택하세요.")
    period=months(start,end,max_months=None if automatic else 60)
    cutoff=min(dt.date.fromisoformat(as_of),dt.date.today())
    if end>cutoff.strftime("%Y-%m"):
        raise ValueError("종료월은 분석 기준일 또는 현재월보다 늦을 수 없습니다.")
    last=dt.date(int(end[:4]),int(end[5:]),calendar.monthrange(int(end[:4]),int(end[5:]))[1])
    return period,min(last,cutoff).isoformat()


class MemoryCache:
    """Bounded process-memory cache: no raw payloads or credentials on disk."""
    def __init__(self, limit=128, ttl=1800):
        self.limit, self.ttl = limit, ttl
        self.entries, self.lock = OrderedDict(), threading.RLock()

    def get(self, key):
        with self.lock:
            entry = self.entries.get(key)
            if not entry or time.monotonic()-entry[0] > self.ttl:
                self.entries.pop(key, None)
                return None
            self.entries.move_to_end(key)
            return copy.deepcopy(entry[1])

    def set(self, key, value):
        with self.lock:
            self.entries[key] = (time.monotonic(), copy.deepcopy(value))
            self.entries.move_to_end(key)
            while len(self.entries) > self.limit:
                self.entries.popitem(last=False)

    def discard(self, key):
        with self.lock:
            self.entries.pop(key, None)

    def invalidate(self,prefixes):
        with self.lock:
            for key in list(self.entries):
                if isinstance(key,tuple) and key and key[0] in prefixes:self.entries.pop(key,None)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ApiError("UPSTREAM_REDIRECT", "공식 API가 다른 주소로 이동했습니다. 경로 확인이 필요합니다.")


NED = {
    "landRegister": ("ladfrlList", 128, "pnu ldCode ldCodeNm mnnmSlno regstrSeCode regstrSeCodeNm lndcgrCode lndcgrCodeNm lndpclAr posesnSeCode posesnSeCodeNm cnrsPsnCo ladFrtlSc ladFrtlScNm lastUpdtDt"),
    "characteristics": ("getLandCharacteristics", 18, "pnu ldCode ldCodeNm regstrSeCode regstrSeCodeNm mnnmSlno stdrYear stdrMt lndcgrCode lndcgrCodeNm lndpclAr prposArea1Nm prposArea2Nm ladUseSittnNm tpgrphHgCodeNm tpgrphFrmCodeNm roadSideCodeNm lastUpdtDt"),
    "landUse": ("getLandUseAttr", 51, "pnu ldCode ldCodeNm regstrSeCodeNm mnnmSlno manageNo cnflcAt cnflcAtNm prposAreaDstrcCode prposAreaDstrcCodeNm registDt lastUpdtDt"),
    "ownership": ("getPossessionAttr", 47, "pnu ldCode ldCodeNm stdrYm lndcgrCodeNm lndpclAr posesnSeCode posesnSeCodeNm resdncSeCodeNm nationInsttSeCodeNm ownshipChgCauseCodeNm ownshipChgDe cnrsPsnCo lastUpdtDt"),
    "buildings": ("getBuildingUse", 6, "gisIdntfcNo pnu ldCode ldCodeNm buldIdntfcNo buldKndCodeNm buldNm buldDongNm buldMainAtachSeCodeNm buldPlotAr buldBildngAr buldTotar strctCodeNm mainPrposCodeNm detailPrposCodeNm buldPrposClCodeNm buldHg groundFloorCo undgrndFloorCo prmisnDe useConfmDe lastUpdtDt"),
}


def ned_container(payload):
    if not isinstance(payload, dict):
        raise ApiError("SCHEMA_CHANGED", "토지 속성 응답 형식을 확인할 수 없습니다.")
    error = payload.get("response", payload).get("resultCode")
    if error not in (None, "", "0", "00"):
        raise ApiError("UPSTREAM_REJECTED", "토지 속성 API가 조회를 거절했습니다. 인증·이용 설정을 확인하세요.")
    for v in [payload, *payload.values()]:
        if isinstance(v, dict) and ("field" in v or "totalCount" in v):
            if v.get("error"):
                raise ApiError("UPSTREAM_REJECTED", "토지 속성 API의 인증·이용 설정을 확인하세요.")
            rows = v.get("field", v.get("ladfrlVOList", []))
            if isinstance(rows, dict):
                rows = [rows]
            if rows is None:
                rows = []
            if not isinstance(rows, list):
                raise ApiError("SCHEMA_CHANGED", "토지 속성 행 구조가 변경되었습니다.")
            total = number(v.get("totalCount"))
            total = int(total) if total is not None else len(rows)
            if total>0 and not rows:
                raise ApiError("SCHEMA_CHANGED", "토지 속성 건수와 자료 행이 일치하지 않습니다.")
            return rows, total
    raise ApiError("SCHEMA_CHANGED", "토지 속성 응답의 자료 행을 찾을 수 없습니다.")


class Collector:
    def __init__(self, keys=None, domain=DEFAULT_DOMAIN, transport=None, land_store=None):
        self.keys = dict(keys or {})
        self.domain = domain.rstrip("/")
        if urllib.parse.urlsplit(self.domain).scheme not in ("http", "https"):
            raise ValueError("브이월드 등록 서비스 주소는 http 또는 https 주소여야 합니다.")
        self.transport = transport
        self.cache = MemoryCache()
        # Geocoder-derived responses have a dedicated process-only lifetime.
        # Do not replace these caches with the persistent snapshot store.
        self.geocode_cache = MemoryCache(512, 900)
        self.session_cache = MemoryCache()
        self.tile_cache = MemoryCache(100, 300)
        self.gate = threading.BoundedSemaphore(6)
        self.opener = urllib.request.build_opener(NoRedirect())
        self._regions = None
        self.coverage_lock = threading.RLock()
        self.coverage_revenue = copy.deepcopy(COVERAGE_SEED)
        self.coverage_warning = None
        self.coverage_attempt_at = 0
        self.coverage_attempt_day = None
        self.land_cache = MemoryCache(512, 21600)
        self.land_store = land_store
        self.land_store_error = None
        self.land_reads = {}
        self.land_locks = defaultdict(threading.RLock)
        self.land_network_lock = threading.Lock()
        self.land_next_request = 0

    def status(self):
        return {"mode": "local", "version": VERSION, "canUpload": False,
                "landStorage":{"enabled":self.land_store is not None,"error":self.land_store_error,
                    "fileName":self.land_store.path.name if self.land_store else None},
                "apiStatus": {k: "준비" if self.keys.get(k) else "키 미입력" for k in ("vworld", "vworldGeocoder", "dataGoKr", "juso")}}

    def land_storage(self,sgg=None):
        if self.land_store is None:return {"enabled":False,"error":self.land_store_error}
        try:return self.land_store.summary(sgg)
        except LandStoreError as exc:raise ApiError('LAND_STORAGE',str(exc)) from None

    def regions(self,**kwargs):
        with self.coverage_lock:
            if self._regions is None:self._regions=RegionCatalog()
        return self._regions.search(**kwargs)

    def _coverage_count(self,conditions):
        result=self.request("https://api.odcloud.kr/api/ApplyhomeInfoDetailSvc/v1/getAPTLttotPblancDetail",{"serviceKey":self.require("dataGoKr"),"page":1,"perPage":1,"cond[HOUSE_SECD::EQ]":"01","cond[HOUSE_DTL_SECD::EQ]":"01",**conditions})
        count=number(result.get("matchCount"))
        if not isinstance(result.get("data"),list) or count is None or count<0:
            raise ApiError("COVERAGE_SCHEMA","청약홈 자료 범위 응답을 검증하지 못했습니다.")
        return int(count)

    def _refresh_coverage(self):
        """At most ~25 count/month calls; no per-keystroke or whole-history fetch."""
        today=dt.date.today();end_date=today.isoformat()
        if self._coverage_count({"cond[RCRIT_PBLANC_DE::LT]":"2000-01-01"}):
            raise ApiError("COVERAGE_BOUNDARY","2000년 이전 공고가 확인돼 범위 탐색 하한을 재검토해야 합니다.")
        base=2000*12;top=today.year*12+today.month-1
        month=lambda n:f"{n//12:04d}-{n%12+1:02d}"
        if not self._coverage_count({"cond[RCRIT_PBLANC_DE::GTE]":"2000-01-01","cond[RCRIT_PBLANC_DE::LTE]":end_date}):
            raise ApiError("COVERAGE_EMPTY","청약홈 자료 범위 조회가 0건입니다. 이전 확인 범위를 유지합니다.")
        low,high=base,top
        while low<high:
            mid=(low+high)//2
            final=dt.date(mid//12,mid%12+1,calendar.monthrange(mid//12,mid%12+1)[1]).isoformat()
            if self._coverage_count({"cond[RCRIT_PBLANC_DE::GTE]":"2000-01-01","cond[RCRIT_PBLANC_DE::LTE]":min(final,end_date)}):high=mid
            else:low=mid+1
        earliest=month(low);low,high=base,top
        while low<high:
            mid=(low+high+1)//2
            if self._coverage_count({"cond[RCRIT_PBLANC_DE::GTE]":month(mid)+"-01","cond[RCRIT_PBLANC_DE::LTE]":end_date}):low=mid
            else:high=mid-1
        latest=month(low);boundaries=[]
        for value in dict.fromkeys((earliest,latest)):
            month_end=dt.date(int(value[:4]),int(value[5:]),calendar.monthrange(int(value[:4]),int(value[5:]))[1]).isoformat()
            rows=self.odcloud("getAPTLttotPblancDetail",{"cond[HOUSE_SECD::EQ]":"01","cond[HOUSE_DTL_SECD::EQ]":"01","cond[RCRIT_PBLANC_DE::GTE]":value+"-01","cond[RCRIT_PBLANC_DE::LTE]":min(month_end,end_date)})
            dates=[text(r.get("RCRIT_PBLANC_DE")) for r in rows if text(r.get("HOUSE_SECD"))=="01" and text(r.get("HOUSE_DTL_SECD"))=="01" and text(r.get("RENT_SECD"))=="0" and value+"-01"<=text(r.get("RCRIT_PBLANC_DE"))<=min(month_end,end_date)]
            if not dates:raise ApiError("COVERAGE_PRIVATE_BOUNDARY","경계 월의 민영 분양주택을 확인하지 못해 이전 확인 범위를 유지합니다.")
            for date in dates:dt.date.fromisoformat(date)
            boundaries.extend(dates)
        return {**COVERAGE_SEED,"minMonth":earliest,"maxMonth":latest,"observedMinDate":min(boundaries),"observedMaxDate":max(boundaries),"checkedAt":now(),"status":"observed_api","verification":"전국 APT 날짜 경계 제한 조회 후 경계 월 민영 분양주택 확인; 모든 월·주택형 완전성 보장 아님"}

    def data_coverage(self,as_of=None,refresh=False,auto=False,*,allow_network=False):
        # V4's displayed window is calendar arithmetic, not a source availability
        # probe. Opening the app or focusing it must not consume portal quota.
        # Legacy internal checks may explicitly request the former bounds probe.
        if not allow_network:
            period=rolling_period()
            common={"minMonth":period["start"],"maxMonth":period["end"],"available":True}
            shared={**common,"effectiveStartDate":period["startDate"],"effectiveEndDate":period["endDate"],
                    "endExclusive":period["endExclusive"],"status":"requested_window","collectionStatus":"not_requested"}
            return {"land":{**shared,"dateBasis":"계약일","sourceUrl":"https://www.data.go.kr/data/15126466/openapi.do"},
                    "revenue":{**shared,"dateBasis":"모집공고일","sourceUrl":"https://www.data.go.kr/data/15098547/openapi.do",
                               "officialCoverageGuarantee":False},"common":common,"rollingPeriod":period,
                    "periodMode":"rolling60","maxMonths":60,"automaticMaxMonths":60,"asOf":period["asOf"],
                    "checkedAt":None,"status":"requested_window","warnings":["최근 완료된 60개월의 요청 범위입니다. 자료 수집 완료 또는 제공기관의 완전성 보장이 아니며, 필지 선택 후 조회합니다."]}
        try:as_of=dt.date.fromisoformat(as_of) if as_of else dt.date.today()
        except (ValueError,TypeError):raise ValueError("분석 기준일은 YYYY-MM-DD 형식이어야 합니다.") from None
        with self.coverage_lock:
            today=dt.date.today()
            elapsed=time.monotonic()-self.coverage_attempt_at
            due=(not self.coverage_attempt_at or self.coverage_attempt_day!=today.isoformat()
                 or elapsed >= (60 if self.coverage_warning else 3600))
            if refresh or (auto and due):
                self.coverage_attempt_at=time.monotonic()
                self.coverage_attempt_day=today.isoformat()
                try:self.coverage_revenue=self._refresh_coverage();self.coverage_warning=None
                except (ApiError,ValueError):self.coverage_warning="청약홈 자료 범위 갱신 실패: 마지막 확인 범위와 확인시각을 유지합니다."
            revenue=copy.deepcopy(self.coverage_revenue)
            revenue["observedMaxMonth"]=revenue["maxMonth"]
            ceiling=min(as_of,dt.date.today()).strftime("%Y-%m")
            revenue["maxMonth"]=min(revenue["maxMonth"],ceiling)
            revenue["available"]=revenue["minMonth"]<=revenue["maxMonth"]
            if self.coverage_warning:revenue["status"]="last_known"
            land={"minMonth":"2006-01","maxMonth":ceiling,"available":ceiling>="2006-01","dateBasis":"계약일","status":"official_start_current_month","sourceUrl":"https://rt.molit.go.kr/pt/info/info.do?mobileat=v","completenessNote":"최근월은 신고 반영 중이며 과거 자료도 추가·정정될 수 있음"}
            cutoff=min(as_of,today).isoformat()
            land.update(fixedStartDate=LAND_START_DATE,effectiveEndDate=cutoff)
            revenue.update(fixedStartDate=REVENUE_START_DATE,effectiveEndDate=min(cutoff,revenue["observedMaxDate"]))
            return {"land":land,"revenue":revenue,"common":{"minMonth":max(land["minMonth"],revenue["minMonth"]),"maxMonth":min(land["maxMonth"],revenue["maxMonth"]),"available":revenue["available"] and land["available"]},"maxMonths":60,"automaticMaxMonths":None,"asOf":as_of.isoformat(),"checkedAt":revenue["checkedAt"],"status":"last_known" if self.coverage_warning else revenue["status"],"warnings":([self.coverage_warning] if self.coverage_warning else [])+["청약홈 범위는 관측값이며 공식 제공기간 보장이 아닙니다. 과거를 재조회한 결과는 당시 시점에 저장된 자료와 다를 수 있습니다."]}

    def require(self, key):
        if not self.keys.get(key):
            raise ApiError("KEY_MISSING", "해당 API 인증키를 입력한 뒤 Python을 다시 실행하세요.", 503)
        return self.keys[key]

    def request(self, url, params=None, kind="json"):
        if self.transport:
            return self.transport(url, params or {}, kind)
        encoded = urllib.parse.urlencode(params or {})
        target = url + ("?"+encoded if encoded else "")
        req = urllib.request.Request(target, headers={"User-Agent": "PF-Study/1.0",
             "Origin": self.domain, "Referer": self.domain+"/", "Accept": "*/*"})
        with self.gate:
            try:
                with self.opener.open(req, timeout=25) as response:
                    body = response.read(MAX_BODY+1)
                    if len(body) > MAX_BODY:
                        raise ApiError("RESPONSE_TOO_LARGE", "API 응답이 처리 한도를 초과했습니다. 조회 범위를 줄이세요.")
            except urllib.error.HTTPError as exc:
                code = "UPSTREAM_AUTH" if exc.code in (401,403) else "UPSTREAM_RATE_LIMIT" if exc.code == 429 else "UPSTREAM_HTTP"
                message = "공식 API 조회 한도를 초과했습니다. 제공기관의 한도가 회복된 후 다시 조회하세요." if exc.code == 429 else "공식 API 응답 오류입니다. 키의 승인·만료·조회 한도와 서비스 상태를 확인하세요."
                raise ApiError(code, message) from None
            except (urllib.error.URLError, TimeoutError, OSError):
                raise ApiError("UPSTREAM_NETWORK", "공식 API 연결에 실패했습니다. 네트워크와 제공기관 상태를 확인하세요.") from None
        if kind == "bytes":
            return body
        if kind == "xml":
            if b"<!DOCTYPE" in body.upper() or b"<!ENTITY" in body.upper():
                raise ApiError("INVALID_XML", "허용하지 않는 XML 응답입니다.")
            try:
                return ET.fromstring(body)
            except ET.ParseError:
                raise ApiError("INVALID_XML", "공식 API가 정상 XML을 반환하지 않았습니다.") from None
        try:
            return json.loads(body)
        except (ValueError, UnicodeError):
            raise ApiError("INVALID_JSON", "공식 API가 정상 JSON을 반환하지 않았습니다.") from None

    def tile(self, z, y, x):
        if not (6 <= z <= 19 and 0 <= x < 2**z and 0 <= y < 2**z):
            raise ValueError("지원하지 않는 지도 타일 좌표입니다.")
        ck = (z,y,x)
        hit = self.tile_cache.get(ck)
        if hit is not None:
            return hit
        key = self.require("vworld")
        body = self.request(f"https://api.vworld.kr/req/wmts/1.0.0/{urllib.parse.quote(key,safe='')}/Satellite/{z}/{y}/{x}.jpeg", kind="bytes")
        if not body.startswith(b"\xff\xd8"):
            raise ApiError("TILE_UNAVAILABLE", "위성영상 응답이 없습니다. 브이월드 키·등록 도메인·지도 범위를 확인하세요.")
        self.tile_cache.set(ck, body)
        return body

    def parcels(self, bbox):
        if len(bbox) != 4 or not all(math.isfinite(v) for v in bbox):
            raise ValueError("지도 범위 좌표가 올바르지 않습니다.")
        a,b,c,d = bbox
        if not (120 <= a < c <= 134 and 30 <= b < d <= 40 and c-a <= .04 and d-b <= .04):
            raise ValueError("필지를 보려면 지도를 확대하세요. 한 번에 조회할 범위는 경위도 각 0.04도 이하입니다.")
        cache_key = ("parcels", *[round(x,7) for x in bbox])
        hit=self.cache.get(cache_key)
        if hit is not None:
            hit["fromCache"] = True
            return hit
        features, total, seen = [], None, set()
        for page in range(1, 21):
            p={"service":"data","request":"GetFeature","version":"2.0","data":"LP_PA_CBND_BUBUN","key":self.require("vworld"),"domain":self.domain,"format":"json","crs":"EPSG:4326","geomFilter":f"BOX({a},{b},{c},{d})","size":100,"page":page,"geometry":"true","attribute":"true"}
            r=self.request("https://api.vworld.kr/req/data",p).get("response",{})
            if r.get("status") == "NOT_FOUND":
                total=0 if total is None else total
                break
            if r.get("status") != "OK":
                raise ApiError("CADASTRAL_REJECTED","필지 API 조회가 거절되었습니다. 인증키·등록 도메인·조회 범위를 확인하세요.")
            raw=r.get("result",{}).get("featureCollection",{}).get("features",[])
            total=int(r.get("record",{}).get("total",len(raw)))
            for f in raw:
                props=f.get("properties",{});pnu=text(props.get("pnu"))
                if re.fullmatch(r"\d{19}",pnu) and pnu not in seen:
                    seen.add(pnu)
                    features.append({"type":"Feature","id":pnu,"geometry":f.get("geometry"),"properties":{"pnu":pnu,"address":text(props.get("addr") or props.get("address") or props.get("jibun")),"sourceStatus":"호출 확인"}})
            if page*100 >= total:
                break
            if not raw:
                raise ApiError("PARTIAL_COLLECTION","필지 페이지 수집이 중단됐습니다. 범위를 줄여 다시 조회하세요.")
        complete=total is not None and page*100>=total
        result={"type":"FeatureCollection","features":features,"crs":"EPSG:4326","totalCount":total,"collectedCount":len(features),"collectionStatus":"complete" if complete else "partial","queriedAt":now(),"warnings":[] if complete else ["조회 한도 2,000개 초과: 지도를 확대하세요. 일부 필지만 표시됩니다."]}
        if complete:self.cache.set(cache_key,result)
        return result

    def ned(self, name, pnu, year):
        path, doc, fields=NED[name]
        rows=[]
        for page in range(1, 21):
            params={"key":self.require("vworld"),"domain":self.domain,"pnu":pnu,"format":"json","numOfRows":100,"pageNo":page}
            if name=="characteristics":params["stdrYear"]=year
            data,total=ned_container(self.request("https://api.vworld.kr/ned/data/"+path,params))
            rows.extend([{k:r.get(k) for k in fields.split() if k in r} for r in data if text(r.get("pnu"))==pnu])
            if page*100>=total:break
            if not data:raise ApiError("PARTIAL_COLLECTION","토지 속성 페이지 수집이 중단됐습니다.")
        if page*100<total:raise ApiError("PARTIAL_COLLECTION","토지 속성 수집 한도를 초과했습니다.")
        return {"rows":rows,"status":"호출 확인","count":len(rows),"sourceUrl":f"https://www.vworld.kr/dtna/dtna_apiSvcFc_s001.do?apiNum={doc}","queriedAt":now()}

    def parcel(self,pnu,year,refresh=False):
        if not re.fullmatch(r"\d{19}",pnu):raise ValueError("필지고유번호는 19자리 문자열이어야 합니다.")
        if not 2000<=int(year)<=dt.date.today().year:raise ValueError("유효한 토지특성 기준연도를 입력하세요.")
        cache_key=("parcel",pnu,int(year))
        if refresh:self.cache.discard(cache_key)
        hit=None if refresh else self.cache.get(cache_key)
        if hit is not None:hit["fromCache"]=True;return hit
        attributes,warnings={},[]
        def one(name):
            try:return name,self.ned(name,pnu,year)
            except ApiError as e:return name,{"rows":[],"status":"조회 실패","errorCode":e.code,"message":e.message,"sourceUrl":f"https://www.vworld.kr/dtna/dtna_apiSvcFc_s001.do?apiNum={NED[name][1]}"}
        with ThreadPoolExecutor(max_workers=3) as pool:
            attributes=dict(pool.map(one,NED))
        for name,a in attributes.items():
            if a["status"]!="호출 확인":warnings.append(f"{name}: {a['message']}")
        register=attributes["landRegister"]["rows"]
        characteristic=attributes["characteristics"]["rows"]
        r=register[0] if len(register)==1 else characteristic[0] if len(characteristic)==1 else {}
        reference_area=number(characteristic[0].get("lndpclAr")) if len(characteristic)==1 else None
        area=number(register[0].get("lndpclAr")) if len(register)==1 else None
        area=area if area and area>0 else None
        if not register and reference_area is not None:warnings.append(f"대장 면적 미확보: {year}년 토지특성 면적은 참고값이며 매입비 계산에 자동 적용하지 않습니다. 현재 대장 면적 확인이 필요합니다.")
        if len(register)>1: warnings.append("대장 정보가 여러 행입니다. 면적·기준일을 확인하세요.")
        result={"pnu":pnu,"address":" ".join(filter(None,[text(r.get("ldCodeNm")),text(r.get("mnnmSlno"))])),"areaM2":area,"referenceAreaM2":reference_area,"referenceAreaYear":int(year),"legalDongCode":text(r.get("ldCode")) or pnu[:10],"legalDongName":text(r.get("ldCodeNm")),"dong":canonical_dong(r.get("ldCodeNm")),"attributes":attributes,"sourceStatus":"공개자료" if register and area is not None else "추가 확인 필요","areaBasis":"토지임야대장" if register and area is not None else "현재 대장 면적 미확보","sources":[{"id":"ned-"+name,"pnu":pnu,"name":name,"url":a["sourceUrl"],"status":a["status"],"queriedAt":a.get("queriedAt"),"basisYear":int(year) if name=="characteristics" else None} for name,a in attributes.items()],"warnings":warnings}
        failed=sum(a["status"]!="호출 확인" for a in attributes.values())
        result.update(collectionStatus="failed" if failed==len(attributes) else "partial" if failed else "complete",fromCache=False)
        result["comparisonProfile"] = parcel_profile(result)
        # A failed source must be retried on the next request, not held for the
        # normal 30-minute success lifetime. Successful empty rows remain valid.
        if not failed:self.cache.set(cache_key,result)
        return result

    def boundary_allocation(self, pnu, year, refresh=False):
        """PNU-bound current evidence and polygon overlay, independent of map state."""
        from pf_boundary import collect_boundary, VERSION as BOUNDARY_VERSION
        parcel = self.parcel(pnu, year, refresh=refresh)
        cache_key = ('boundary', BOUNDARY_VERSION, pnu, int(year))
        if refresh: self.cache.discard(cache_key)
        allocation = None if refresh else self.cache.get(cache_key)
        if allocation is None:
            allocation = collect_boundary(self, parcel)
            if allocation.get('source', {}).get('complete') is True:
                self.cache.set(cache_key, allocation)
        parcel['boundaryAllocation'] = allocation
        if allocation.get('parcelGeometry'):
            parcel['geometry'] = allocation['parcelGeometry']
        return {'pnu': pnu, 'boundaryAllocation': allocation, 'parcel': parcel}

    def geocode(self, address):
        """Original supply text -> PARCEL -> explicit parcel retries, in memory only.

        A coordinate, a verified source address and a PNU are separate facts.
        This method never needs Juso/search or a PNU and never falls back to the
        map credential. All returned errors are locally defined, key-free codes.
        """
        original = "" if address is None else str(address)
        ck = ("supply-geocode", "ri-structure-v2", original)
        hit = self.geocode_cache.get(ck)
        if hit is not None:
            hit["fromCache"] = True
            return hit
        result = {"inputAddress": original, "geocodingState": "U", "coordinateReturned": False,
                  "coordinateVerified": False, "addressVerified": False, "lon": None, "lat": None,
                  "pnu": None, "pnuStatus": "별도 필지 확인 필요", "legalDongCode": None,
                  "legalDongName": None, "dong": None, "refinedAddress": None,
                  "geocodingMethod": None, "geocodingErrors": [], "attempts": [],
                  "coordinateSourceUrl": GEOCODER_SOURCE, "coordinateBasis": "공급공고 대표 주소점",
                  "realtimeOnly": True, "persistencePolicy": "session_only", "fromCache": False}

        def finish(state, reason):
            result.update(geocodingState=state, coordinateStatus=GEOCODING_LABELS[state], reason=reason)
            result["coordinateVerified"] = result["addressVerified"] = state == "V"
            if state not in ("E", "P") and not result["geocodingErrors"]:
                self.geocode_cache.set(ck, result)
            return result

        if not original.strip():
            return finish("U", "공급위치 입력 없음")
        if not self.keys.get("vworldGeocoder"):
            result["geocodingErrors"].append("GEOCODER_KEY_MISSING")
            return finish("E", "Geocoder 전용 인증 미준비")

        # Constructing candidates must not alter or short-circuit the first request.
        candidates = parcel_candidates(original)
        expected = {parcel_identity(value) for value in candidates}
        expected.discard(None)
        queries = [(original, "original")]
        queries.extend((value, "parcel_candidate") for value in candidates if value != original)
        points = []
        for query_address, method in queries:
            attempt = {"address": query_address, "method": method, "status": None}
            result["attempts"].append(attempt)
            try:
                payload = self.request("https://api.vworld.kr/req/address", {
                    "service": "address", "request": "getCoord", "version": "2.0",
                    "key": self.keys["vworldGeocoder"], "domain": self.domain, "format": "json",
                    "type": "PARCEL", "address": query_address, "crs": "EPSG:4326",
                    "refine": "true", "simple": "false"})
                data = payload.get("response") if isinstance(payload, dict) else None
                if not isinstance(data, dict):
                    raise ApiError("GEOCODE_RESPONSE", "좌표 응답 형식 확인 필요")
                status = data.get("status")
                if status == "NOT_FOUND":
                    attempt["status"] = "NOT_FOUND"
                    continue
                if status != "OK":
                    error = data.get("error") or {}
                    upstream = error.get("code") if isinstance(error, dict) else None
                    code = ("GEOCODE_AUTH" if upstream in ("INVALID_KEY", "INCORRECT_KEY", "UNAVAILABLE_KEY")
                            else "GEOCODE_RATE_LIMIT" if upstream == "OVER_REQUEST_LIMIT" else "GEOCODE_REJECTED")
                    raise ApiError(code, "좌표 API가 요청을 거절했습니다.")
                geo = data.get("result") or {}
                point = geo.get("point") or {}
                lon, lat = number(point.get("x")), number(point.get("y"))
                if text(geo.get("crs")).upper() not in ("", "EPSG:4326"):
                    raise ApiError("GEOCODE_CRS", "좌표계 확인 필요")
                if lon is None or lat is None or not 120 < lon < 134 or not 30 < lat < 40:
                    raise ApiError("GEOCODE_POINT", "유효한 국내 경위도 없음")
                # Retain a valid point even if later address metadata is broken.
                point_result = {"lon": lon, "lat": lat, "refinedAddress": None,
                                "geocodingMethod": method, "matchedParcelAddress": None}
                points.append(point_result)
                result.update(point_result, coordinateReturned=True)
                refined = data.get("refined") or {}
                structure = refined.get("structure") or {}
                refined_text = text(refined.get("text"))
                structured_text = " ".join(text(structure.get(k)) for k in
                                           ("level1", "level2", "level3", "level4L", "level5"))
                identity = parcel_identity(refined_text) or parcel_identity(structured_text)
                structured_identity = parcel_identity(structured_text)
                if structured_identity and not compatible_parcel_structure(identity, structured_identity):
                    identity = None
                verified = len(expected) == 1 and identity in expected
                point_result.update(refinedAddress=refined_text or structured_text.strip(),
                                    matchedParcelAddress=identity[1] if verified else None)
                attempt["status"] = "VERIFIED" if verified else "COORDINATE_CANDIDATE"
                result.update(point_result, coordinateReturned=True)
                if verified:
                    name = re.sub(r"\s+(?:산\s*)?\d+(?:-\d+)?$", "", identity[1])
                    result.update(legalDongName=name, dong=canonical_dong(name))
                    # Local official legal-dong reference only; no additional API.
                    try:
                        matches = self.regions(q=name, current=True, limit=100).get("items", [])
                        codes = {r["code"] for r in matches if r.get("level") in ("dong", "ri")
                                 and normalized_address(r.get("name")) == name and re.fullmatch(r"\d{10}",text(r.get("code")))}
                        if len(codes) == 1:
                            result["legalDongCode"] = next(iter(codes))
                    except (ApiError, OSError, ValueError, KeyError):
                        # Missing local region metadata does not invalidate a
                        # verified parcel coordinate or manufacture its PNU.
                        result["legalDongCode"] = None
                    return finish("V", "원공급주소의 법정지역·산 여부·본번·부번 일치")
            except (ApiError, AttributeError, TypeError, ValueError) as exc:
                # No raw upstream text/URL is ever returned, even on malformed data.
                safe_codes = {"UPSTREAM_AUTH", "UPSTREAM_RATE_LIMIT", "UPSTREAM_HTTP", "UPSTREAM_NETWORK",
                              "UPSTREAM_REDIRECT", "INVALID_JSON", "RESPONSE_TOO_LARGE", "GEOCODE_RESPONSE",
                              "GEOCODE_AUTH", "GEOCODE_RATE_LIMIT", "GEOCODE_REJECTED", "GEOCODE_CRS", "GEOCODE_POINT"}
                code = exc.code if isinstance(exc, ApiError) and exc.code in safe_codes else "GEOCODE_RESPONSE"
                attempt.update(status="ERROR", errorCode=code)
                result["geocodingErrors"].append(code)
                # Retrying another address cannot fix authentication, rate, network
                # or schema failures. Preserve any previously returned coordinate.
                break
        if points:
            return finish("C", "좌표는 반환됐으나 공급주소 일치 또는 대표 지번 확인 필요")
        if result["geocodingErrors"]:
            return finish("E", "좌표 요청을 완료하지 못했습니다.")
        return finish("U", "명확한 지번주소 결과 없음")

    def districts_near(self,lon,lat,radius_km):
        bounds=radius_bounds(lon,lat,radius_km);ck=("districts-near",lon,lat,radius_km)
        hit=self.cache.get(ck)
        if hit is not None:return hit
        districts=[];total=None
        for page in range(1,11):
            p={"service":"data","request":"GetFeature","version":"2.0","data":"LT_C_ADSIGG_INFO","key":self.require("vworld"),"domain":self.domain,"format":"json","crs":"EPSG:4326","geomFilter":"BOX("+",".join(str(v) for v in bounds)+")","size":100,"page":page,"geometry":"false","attribute":"true"}
            response=self.request("https://api.vworld.kr/req/data",p).get("response",{})
            if response.get("status")=="NOT_FOUND":break
            if response.get("status")!="OK":raise ApiError("BOUNDARY_REJECTED","주변 시군구 경계 조회에 실패했습니다. 반경 비교의 조회 범위를 확인할 수 없습니다.")
            rows=response.get("result",{}).get("featureCollection",{}).get("features",[])
            total=number(response.get("record",{}).get("total"))
            if total is None:raise ApiError("SCHEMA_CHANGED","주변 시군구 경계 전체 건수가 확인되지 않습니다.")
            for row in rows:
                p=row.get("properties",{});code=text(p.get("sig_cd"));name=text(p.get("full_nm"))
                if not re.fullmatch(r"\d{5}",code) or not name:raise ApiError("SCHEMA_CHANGED","시군구 경계 코드·명칭 응답을 확인할 수 없습니다.")
                districts.append({"code":code,"name":name})
            if page*100>=total:break
            if not rows:raise ApiError("PARTIAL_COLLECTION","주변 시군구 경계 페이지가 누락되었습니다.")
        if not districts:raise ApiError("BOUNDARY_NOT_FOUND","선택 부지 주변의 시군구 경계를 찾지 못했습니다.")
        if total and page*100<total:raise ApiError("PARTIAL_COLLECTION","주변 시군구 경계 수집 한도를 초과했습니다.")
        self.cache.set(ck,districts)
        return districts

    def sale_location(self,address,coordinates=False):
        """Preserve the legacy pair interface without a Juso/search prerequisite."""
        result = self.geocode(address)
        return (result if result["coordinateReturned"] else None), {"candidates": [], "geocoding": result}

    @staticmethod
    def candidate_district(address,districts):
        """Use official bbox districts; unresolved administration stays a candidate."""
        address=normalized_address(address)
        if any(address==normalized_address(d["name"]) or address.startswith(normalized_address(d["name"])+" ") for d in districts):return True
        parts=address.split()
        provinces=set(PROVINCE_ALIASES.values())
        # An unparseable or historical administration is not silently dropped.
        if not parts or parts[0] not in provinces:return True
        if len(parts)<2 or not parts[1].endswith(("시","군","구")):return True
        if len(parts)>2 and parts[2].endswith("구") and not parts[1].endswith("시"):return True
        admin=parts[:2]
        if len(parts)>2 and parts[1].endswith("시") and parts[2].endswith("구"):admin.append(parts[2])
        # Old notices may omit a district established later (e.g. 부천시).
        if any(normalized_address(d["name"]).startswith(" ".join(admin)+" ") for d in districts):return True
        return False

    def address(self, keyword, geocode=False):
        keyword=text(keyword)
        if not 2<=len(keyword)<=200:raise ValueError("주소는 2~200자로 입력하세요.")
        cache=self.session_cache if geocode else self.cache
        ck=("address",keyword,bool(geocode));hit=cache.get(ck)
        if hit is not None:return hit
        p={"confmKey":self.require("juso"),"currentPage":1,"countPerPage":20,"keyword":keyword,"resultType":"json"}
        data=self.request("https://business.juso.go.kr/addrlink/addrLinkApi.do",p).get("results",{})
        c=data.get("common",{})
        if str(c.get("errorCode"))!="0":raise ApiError("ADDRESS_REJECTED","주소 검색이 거절됐습니다. 인증키·검색어를 확인하세요.")
        candidates=[]
        for r in data.get("juso",[]) or []:
            candidates.append({"label":text(r.get("roadAddr")),"address":text(r.get("jibunAddr")),"roadAddress":text(r.get("roadAddr")),"legalDongCode":text(r.get("admCd")),"legalDongName":" ".join(filter(None,[text(r.get("siNm")),text(r.get("sggNm")),text(r.get("emdNm")),text(r.get("liNm"))])),"dong":canonical_dong(" ".join(filter(None,[text(r.get("emdNm")),text(r.get("liNm"))]))),"lon":None,"lat":None,"coordinateStatus":"주소검색 API에는 좌표 없음"})
        if geocode and self.keys.get("vworldGeocoder"):
            for candidate in candidates[:5]:
                try:
                    point=self.geocode(candidate["address"])
                    if point.get("coordinateReturned"):candidate.update(point)
                except ApiError:pass
        result={"candidates":candidates,"totalCount":int(c.get("totalCount") or 0),"queriedAt":now(),"warnings":["주소 후보는 사업지 원문과 확인하세요. 견본주택 주소를 사용하지 마세요."]}
        if geocode:result.update(realtimeOnly=True,persistencePolicy="session_only")
        cache.set(ck,result)
        return result

    def odcloud(self,path,conditions):
        data,total=[],None
        for page in range(1,101):
            p={"serviceKey":self.require("dataGoKr"),"page":page,"perPage":100,**conditions}
            result=self.request("https://api.odcloud.kr/api/ApplyhomeInfoDetailSvc/v1/"+path,p)
            if not isinstance(result.get("data"),list):raise ApiError("APPLYHOME_REJECTED","청약홈 응답에 자료가 없습니다. 인증키·승인 상태를 확인하세요.")
            rows=result["data"];count=number(result.get("matchCount",result.get("totalCount")))
            if count is None:raise ApiError("SCHEMA_CHANGED","청약홈 전체 건수가 확인되지 않아 수집 완료로 처리하지 않았습니다.")
            total=int(count);data.extend(rows)
            if len(data)>=total:break
            if not rows:raise ApiError("PARTIAL_COLLECTION","청약홈 페이지 일부가 누락되었습니다. 다시 조회하세요.")
        if len(data)<(total or 0):raise ApiError("PARTIAL_COLLECTION","청약홈 수집 한도 10,000행을 초과했습니다. 기간을 줄이세요.")
        return data

    def _land_page(self,sgg,month,page):
        if self.land_store is not None and self.transport is None:
            # Start requests at most twice a second; waiting workers stay bounded.
            with self.land_network_lock:
                wait=max(0,self.land_next_request-time.monotonic())
                if wait:time.sleep(wait)
                self.land_next_request=time.monotonic()+.5
        root=self.request("https://apis.data.go.kr/1613000/RTMSDataSvcLandTrade/getRTMSDataSvcLandTrade",{"serviceKey":self.require("dataGoKr"),"LAWD_CD":sgg,"DEAL_YMD":month,"pageNo":page,"numOfRows":100},"xml")
        code=root.findtext(".//resultCode")
        if code in ("22","022") or root.findtext(".//returnReasonCode") in ("22","022"):
            raise ApiError("UPSTREAM_RATE_LIMIT","토지거래 API 일일 조회 한도를 초과했습니다. 제공기관 한도 초기화 후 다시 조회하세요.")
        if code not in ("000","00","0"):raise ApiError("LAND_REJECTED","토지거래 API 조회가 거절되었습니다. 키·승인 상태·조회 한도를 확인하세요.")
        count=number(root.findtext(".//totalCount"))
        if count is None or count<0 or int(count)!=count:raise ApiError("SCHEMA_CHANGED","토지거래 전체 건수가 확인되지 않습니다.")
        total=int(count);rows=root.findall(".//item");data=[]
        for index,item in enumerate(rows):
            row={child.tag:text(child.text) for child in item}
            amount,area=number(row.get("dealAmount")),number(row.get("dealArea"))
            cancelled=text(row.get("cdealType")).upper() in ("O","Y","1") or bool(text(row.get("cdealDay")))
            share=text(row.get("shareDealingType"))
            shared=bool(share and share not in ("전체","전체거래","전체 거래","N","0","-"))
            reasons=[]
            if cancelled:reasons.append("취소 거래")
            if shared:reasons.append("지분 거래 또는 거래 범위 확인 필요")
            if area is None or area<=0 or amount is None or amount<=0:reasons.append("금액·면적 미확보 또는 0 이하")
            try:date=dt.date(int(row.get("dealYear","0")),int(row.get("dealMonth","0")),int(row.get("dealDay","0"))).isoformat()
            except ValueError:date=None;reasons.append("거래일 미확인")
            data.append({"id":f"land-{sgg}-{month}-{page}-{index}","date":date,"dong":row.get("umdNm",""),"jimok":row.get("jimok",""),"landUse":row.get("landUse",""),"areaM2":area,"priceManwon":amount,"cancelled":cancelled,"shareTrade":shared,"eligible":not reasons,"exclusionReason":" · ".join(reasons),"group":"기본","sourceUrl":"https://www.data.go.kr/data/15126466/openapi.do","jibun":row.get("jibun",""),"sggCode":row.get("sggCd",sgg),"shareDealingType":share,"cancellationDate":row.get("cdealDay",""),"coordinateStatus":"가려진 지번으로 PNU·좌표 생성 안 함"})
            data[-1].update(sourceEligible=not reasons, sourceExclusionReasons=list(reasons), ruleVersion=RULES_VERSION)
        return data,total

    def land_month(self,sgg,month,refresh=False):
        with self.land_locks[(sgg,month)]:
            try:return self._land_month(sgg,month,refresh)
            except LandStoreError as exc:raise ApiError('LAND_STORAGE',str(exc)) from None
            except ApiError as exc:
                if self.land_store is not None:
                    try:self.land_store.failure(sgg,month,exc.code)
                    except LandStoreError:pass
                raise

    def _land_month(self,sgg,month,refresh=False):
        key=(sgg,month);store=self.land_store
        cacheable=month < (dt.date.today().replace(day=1)-dt.timedelta(days=1)).strftime('%Y%m')
        if store is not None:
            hit=store.complete(sgg,month,force=refresh)
            if hit is not None:
                self.land_reads[key]={'origin':'local','fetchedAt':hit['fetchedAt'],'resumedPages':0}
                return hit['rows']
        elif cacheable and not refresh:
            hit=self.land_cache.get(key)
            if hit is not None:return hit
        pending=store.pending(sgg,month,force=refresh) if store is not None else []
        data=[];total=None;resumed=0;page=1
        while page<=100:
            rows,count=self._land_page(sgg,month,page)
            if total is not None and count!=total:
                raise ApiError('PARTIAL_COLLECTION','월별 전체 건수가 수집 도중 변경됐습니다. 해당 월을 다시 확인해야 합니다.')
            total=count
            expected=min(100,max(0,total-(page-1)*100))
            if len(rows)!=expected:
                raise ApiError('PARTIAL_COLLECTION','토지거래 일부 페이지가 누락되거나 건수가 일치하지 않습니다.')
            if page==1 and pending and pending[0]['total']==total and pending[0]['page_size']==100 and pending[0]['rows']==rows:
                if all(len(p['rows'])==min(100,max(0,total-(p['page']-1)*100)) for p in pending):
                    data=[r for p in pending for r in p['rows']]
                    resumed=len(pending);page=len(pending)
                else:pending=[]
            else:pending=[]
            if not pending:
                if store is not None:store.save_page(sgg,month,page,rows,total,100)
                data.extend(rows)
            pending=[]
            if len(data)==total:break
            page+=1
        if total is None or len(data)!=total:raise ApiError('PARTIAL_COLLECTION','한 달 토지거래 수집 한도를 초과했습니다.')
        stamp=store.finish(sgg,month,data,total) if store is not None else now()
        self.land_reads[key]={'origin':'api','fetchedAt':stamp,'resumedPages':resumed}
        if cacheable and store is None:self.land_cache.set(key,data)
        return data

    def revenue(self,sgg,dong,start,end,scope="dong",lon=None,lat=None,radius_km=5,end_date=None,start_date=None):
        end_date=end_date or dt.date(int(end[:4]),int(end[5:]),calendar.monthrange(int(end[:4]),int(end[5:]))[1]).isoformat()
        conditions={"cond[HOUSE_SECD::EQ]":"01","cond[HOUSE_DTL_SECD::EQ]":"01","cond[RCRIT_PBLANC_DE::GTE]":start_date or start+"-01","cond[RCRIT_PBLANC_DE::LTE]":end_date}
        districts=[];coverage_warnings=[]
        if scope=="radius":
            radius_bounds(lon,lat,radius_km)
            districts=self.districts_near(lon,lat,radius_km)
        else:conditions["cond[HSSPLY_ADRES::LIKE]"]=dong
        cache_key=("apt-basic",tuple(sorted(conditions.items())))
        basic=self.cache.get(cache_key)
        if basic is None:basic=self.odcloud("getAPTLttotPblancDetail",conditions);self.cache.set(cache_key,basic)
        queried_basic_count=len(basic)
        if scope=="radius":basic=[row for row in basic if self.candidate_district(row.get("HSSPLY_ADRES"),districts)]
        # A notice, not a model row or an HTTP attempt, is the denominator unit.
        grouped={};by_house=defaultdict(set);invalid_notices=0;excluded_types=0
        for b in basic:
            if any(text(b.get(k))!=v for k,v in (("HOUSE_SECD","01"),("HOUSE_DTL_SECD","01"),("RENT_SECD","0"))):
                excluded_types+=1;continue
            house,notice=text(b.get("HOUSE_MANAGE_NO")),text(b.get("PBLANC_NO"))
            if not house or not notice:invalid_notices+=1;continue
            grouped.setdefault((house,notice),[]).append(b)
            by_house[house].add(notice)
        output=[];failures=[];outcomes=[];eligible_houses=set();stop_reason=None;model_requested=0;model_skipped=0
        for (house,notice),duplicates in grouped.items():
            b=duplicates[0]
            # Keep the supplier's exact string for the first PARCEL request.
            address="" if b.get("HSSPLY_ADRES") is None else str(b["HSSPLY_ADRES"])
            reasons=[];found={"candidates":[]};resolved=None
            date=text(b.get("RCRIT_PBLANC_DE"))
            try:
                dt.date.fromisoformat(date)
                if not start+"-01"<=date<=end_date:reasons.append("조회 기간 또는 분석 기준일 밖 사례")
            except ValueError:reasons.append("모집공고일 미확인")
            if len(duplicates)>1:reasons.append("기본정보 복합키 중복")
            if len(by_house[house])>1:reasons.append("같은 단지 복수 공고: 유효 대표공고 확인 필요")
            if stop_reason:
                geo={"geocodingState":"P","coordinateReturned":False,"coordinateVerified":False,
                     "geocodingErrors":[],"coordinateStatus":GEOCODING_LABELS["P"],
                     "reason":"앞선 인증·한도 오류로 처리 대기","pendingReason":stop_reason}
            else:
                try:
                    resolved,found=self.sale_location(address,coordinates=scope=="radius")
                    geo=found.get("geocoding")
                    # Preserve the legacy adapter seam used by other collectors.
                    if geo is None:
                        geo=dict(resolved or {})
                        returned=number(geo.get("lon")) is not None and number(geo.get("lat")) is not None
                        state="V" if returned and geo.get("coordinateVerified") else "C" if returned else "U"
                        geo.update(geocodingState=state,coordinateReturned=returned,coordinateVerified=state=="V",
                                   coordinateStatus=GEOCODING_LABELS[state],geocodingErrors=[])
                except ApiError:
                    geo={"geocodingState":"E","coordinateReturned":False,"coordinateVerified":False,
                         "geocodingErrors":["GEOCODE_RESPONSE"],"coordinateStatus":GEOCODING_LABELS["E"],
                         "reason":"좌표 요청을 완료하지 못했습니다."}
                blocking={"GEOCODER_KEY_MISSING","GEOCODE_AUTH","GEOCODE_RATE_LIMIT","UPSTREAM_AUTH","UPSTREAM_RATE_LIMIT"}
                stop_reason=next((code for code in geo.get("geocodingErrors",[]) if code in blocking),None)
            geo=dict(geo)
            if geo["geocodingState"]=="V" and len({text(row.get("HSSPLY_ADRES")) for row in duplicates})>1:
                geo.update(geocodingState="C",coordinateVerified=False,addressVerified=False,
                           coordinateStatus=GEOCODING_LABELS["C"],reason="같은 공고 복합키의 공급위치 원문 충돌")
            verified=geo["geocodingState"]=="V"
            if not verified:reasons.append(geo.get("reason") or GEOCODING_LABELS[geo["geocodingState"]])
            elif scope=="dong":
                code=text(geo.get("legalDongCode"))
                if not re.fullmatch(r"\d{10}",code) or not code.startswith(sgg) or not same_dong(geo.get("dong"),dong):
                    reasons.append("지정 시군구·법정동 밖 사례 또는 법정동코드 확인 필요")
            distance=None;within=None
            if scope=="radius" and verified:
                distance=haversine_km(float(lon),float(lat),geo["lon"],geo["lat"])
                within=distance<=float(radius_km)+1e-9
                if not within:reasons.append("설정 반경 밖 사례")
            outcome={"id":f"apt-{house}-{notice}","houseManageNo":house,"announcementNo":notice,
                     "name":text(b.get("HOUSE_NM")),"address":address,"date":date,
                     **geo,"distanceKm":distance,"withinRadius":within,"eligible":False,
                     "queryScope":scope,"modelCount":0,"eligibleModelCount":0,
                     "realtimeOnly":True,"persistencePolicy":"session_only"}
            outcomes.append(outcome)
            # Price models cannot become radius comparables without a verified
            # location inside the radius. Keep the notice and its reason, but
            # do not spend quota on unrelated or unresolved projects.
            if scope=="radius" and (not verified or within is not True):
                model_skipped+=1
                outcome.update(modelCollectionStatus="not_requested",exclusionReason=" · ".join(reasons))
                continue
            model_requested+=1
            try:models=self.odcloud("getAPTLttotPblancMdl",{"cond[HOUSE_MANAGE_NO::EQ]":house,"cond[PBLANC_NO::EQ]":notice})
            except ApiError as exc:
                failures.append({"houseManageNo":house,"announcementNo":notice,"code":exc.code})
                outcome.update(modelCollectionStatus="failed",modelErrorCode=exc.code,exclusionReason=" · ".join(reasons+["주택형 조회 실패"]))
                continue
            outcome.update(modelCount=len(models),modelCollectionStatus="complete")
            seen=defaultdict(int)
            for m in models:seen[(text(m.get("HOUSE_MANAGE_NO")),text(m.get("PBLANC_NO")),text(m.get("MODEL_NO")))]+=1
            for m in models:
                mr=list(reasons);model=text(m.get("MODEL_NO"));area=number(m.get("SUPLY_AR"));price=number(m.get("LTTOT_TOP_AMOUNT"))
                if (text(m.get("HOUSE_MANAGE_NO")),text(m.get("PBLANC_NO")))!=(house,notice):mr.append("기본정보 연결 키 불일치")
                if not model:mr.append("주택형 식별키 미확보")
                if seen[(house,notice,model)]>1:mr.append("주택형 식별키 중복")
                if not area or area<0 or not price or price<0:mr.append("공급면적·최고금액 미확보 또는 0 이하")
                counts_fields={k:m.get(k) for k in ("SUPLY_HSHLDCO","SPSPLY_HSHLDCO","MNYCH_HSHLDCO","NWWDS_HSHLDCO","LFE_FRST_HSHLDCO","OLD_PARNTS_SUPORT_HSHLDCO","INSTT_RECOMEND_HSHLDCO","ETC_HSHLDCO","TRANSR_INSTT_ENFSN_HSHLDCO","NWBB_HSHLDCO","YGMN_HSHLDCO") if k in m}
                if not mr:
                    eligible_houses.add(house);outcome["eligible"]=True;outcome["eligibleModelCount"]+=1
                output.append({"id":f"apt-{house}-{notice}-{model}","complexId":house,"houseManageNo":house,"announcementNo":notice,"modelNo":model,"name":text(b.get("HOUSE_NM")),"address":address,"legalDongCode":geo.get("legalDongCode"),"legalDongName":geo.get("legalDongName"),"date":date,"supplyAreaM2":area,"priceManwon":price,"eligible":not mr,"exclusionReason":" · ".join(mr),"sourceUrl":"https://www.data.go.kr/data/15098547/openapi.do","announcementUrl":text(b.get("PBLANC_URL")),"houseType":text(m.get("HOUSE_TY")),"contractor":text(b.get("CNSTRCT_ENTRPS_NM")),"developer":text(b.get("BSNS_MBY_NM")),"priceCap":text(b.get("PARCPRC_ULS_AT")),"supplyCounts":counts_fields,"addressCandidates":found.get("candidates",[]),"geocodingState":geo["geocodingState"],"geocodingMethod":geo.get("geocodingMethod"),"geocodingErrors":geo.get("geocodingErrors",[]),"coordinateStatus":geo.get("coordinateStatus"),"coordinateReturned":geo.get("coordinateReturned",False),"coordinateVerified":verified,"coordinateBasis":geo.get("coordinateBasis"),"lon":geo.get("lon"),"lat":geo.get("lat"),"pnu":None,"distanceKm":distance,"queryScope":scope,"addressVerified":verified,"realtimeOnly":True,"persistencePolicy":"session_only"})
            outcome["exclusionReason"]=" · ".join(reasons if reasons else [] if outcome["eligible"] else ["가격·면적이 적합한 연결 주택형 없음"])
        stats=geocoding_stats(outcomes)
        stats["targetSetStatus"]="ready"
        unresolved=stats["C"]+stats["U"]+stats["E"]+stats["P"]
        if unresolved:coverage_warnings.append(f"공고 위치: 일치 확인 {stats['V']}건, 좌표 후보 {stats['C']}건, 미확정 {stats['U']}건, 호출 실패 {stats['E']}건, 대기 {stats['P']}건. 확인된 위치 사례로만 계산하며 주변 전체 분양사례 수를 보장하지 않습니다.")
        if stats["errorEventCount"]:coverage_warnings.append(f"위치 호출 오류 이력 {stats['errorEventCount']}건이 있어 전체 정상 주소 연결률로 해석할 수 없습니다.")
        if invalid_notices:coverage_warnings.append(f"공고 복합키 미확보 {invalid_notices}행은 좌표 변환 대상 공고 수에서 제외했습니다.")
        if scope=="dong":coverage_warnings.append("동명 원문 검색으로 기본공고를 선별했습니다. 공급주소에 동명이 없으면 후보 조회에서 빠질 수 있습니다.")
        if scope=="radius":coverage_warnings.extend(["거리는 선택 부지 중심과 모집공고 대표 주소점의 직선거리입니다. 단지 전체 경계 간 거리가 아닙니다.","주변 시군구 경계의 현행 명칭으로 후보를 선별합니다. 행정구역 개편 전 주소·비표준 주소는 추가 확인이 필요합니다."])
        return output,{"basicCount":len(basic),"queriedBasicCount":queried_basic_count,"nationalBasicCount":queried_basic_count if scope=="radius" else None,"candidateBasicCount":len(basic),"candidateNoticeCount":len(grouped),"prefilterExcludedCount":queried_basic_count-len(basic),"prefilterExclusionBasis":"시군구 명칭 후보 선별이며 실제 반경 밖 판정이 아님","invalidNoticeCount":invalid_notices,"excludedTypeCount":excluded_types,"modelCount":len(output),"failures":len(failures),"modelFailures":failures,"modelRequestedNoticeCount":model_requested,"modelSkippedNoticeCount":model_skipped,"modelCollectionScope":"verified_within_radius" if scope=="radius" else "dong_candidates","locationFailures":stats["errorEventCount"],"locatedCount":stats["V"],"withinRadiusCount":stats["withinRadiusCount"],"outsideRadiusCount":sum(row.get("withinRadius") is False for row in outcomes),"unresolvedLocationCount":unresolved,"eligibleComplexCount":len(eligible_houses),"queryScope":scope,"radiusKm":float(radius_km) if scope=="radius" else None,"center":{"lon":float(lon),"lat":float(lat)} if scope=="radius" else None,"districts":districts,"coverageWarnings":coverage_warnings,"geocodingStats":stats,"geocodingOutcomes":outcomes,"realtimeOnly":True,"persistencePolicy":"session_only"}

    def comparables(self,sgg,dong,start="",end="",refresh=False,scope="dong",lon=None,lat=None,radius_km=5,land_start=None,land_end=None,revenue_start=None,revenue_end=None,as_of=None,land_scope="dong",period_mode="manual",selected_pnus=None,legal_dong_code=None):
        if not re.fullmatch(r"\d{5}",sgg):raise ValueError("시군구 코드는 5자리여야 합니다.")
        if not dong or len(dong)>40:raise ValueError("법정동·리 이름을 입력하세요.")
        dong=canonical_dong(dong)
        if dong.endswith("리") and " " not in dong:raise ValueError("리 이름만으로 비교할 수 없습니다. 소속 읍·면을 포함해 '와부읍 도곡리'처럼 입력하세요.")
        if scope not in ("dong","radius"):raise ValueError("분양사례 범위는 같은 법정동 또는 반경으로 선택하세요.")
        if land_scope not in ("dong", "sgg"):raise ValueError("토지 비교 범위는 같은 법정동 또는 같은 시군구로 선택하세요.")
        if scope=="radius":
            radius_bounds(lon,lat,radius_km);lon,lat,radius_km=float(lon),float(lat),float(radius_km)
        if period_mode not in ("manual","common","separate","latest","rolling60"):raise ValueError("기간 적용 방식을 확인하세요.")
        rolling=period_mode=="rolling60"
        selection=selected_region(sgg,selected_pnus,legal_dong_code) if rolling else None
        automatic=period_mode in ("latest","rolling60")
        explicit_as_of=bool(as_of) or automatic
        if automatic:as_of=korea_today().isoformat() if rolling else dt.date.today().isoformat()
        as_of=as_of or dt.date.today().isoformat()
        coverage=self.data_coverage(as_of,refresh=refresh and automatic,auto=automatic,allow_network=not rolling)
        land_start,land_end=land_start or start,land_end or end
        revenue_start,revenue_end=revenue_start or start,revenue_end or end
        if rolling:
            window=coverage["rollingPeriod"]
            land_start=revenue_start=window["start"]
            land_end=revenue_end=window["end"]
            period=revenue_period=months(land_start,land_end)
            land_first=revenue_first=window["startDate"]
            land_cutoff=revenue_cutoff=window["endDate"]
            as_of=window["asOf"]
        elif automatic:
            land_start,land_end=LAND_START_DATE[:7],coverage["land"]["maxMonth"]
            revenue_start,revenue_end=REVENUE_START_DATE[:7],coverage["revenue"]["maxMonth"]
        if not rolling:
            period,land_cutoff=comparison_period(land_start,land_end,LAND_START_DATE[:7],coverage["land"]["maxMonth"],as_of,"토지 실거래",automatic=automatic)
            revenue_period,revenue_cutoff=comparison_period(revenue_start,revenue_end,REVENUE_START_DATE[:7] if automatic else coverage["revenue"]["minMonth"],coverage["revenue"]["maxMonth"],as_of,"청약홈",automatic=automatic)
            land_first=LAND_START_DATE if automatic else land_start+"-01"
            revenue_first=REVENUE_START_DATE if automatic else revenue_start+"-01"
            if automatic:revenue_cutoff=coverage["revenue"]["effectiveEndDate"]
        ck=("comparables","verified-radius-models-v2",period_mode,sgg,dong,land_start,land_end,revenue_start,revenue_end,land_cutoff,revenue_cutoff,as_of,scope,land_scope,lon if scope=="radius" else None,lat if scope=="radius" else None,radius_km if scope=="radius" else None,tuple(selection["selectedPnus"]) if selection else None)
        if refresh:
            self.land_cache=MemoryCache(512,21600)
            self.cache.invalidate({"comparables","apt-basic","verified-geocode","address","districts-near"})
            self.session_cache.invalidate({"comparables","address"})
            self.geocode_cache.invalidate({"supply-geocode"})
        if not refresh:
            cached=self.session_cache.get(ck)
            if cached is not None:cached["fromCache"]=True;return cached
        land,revenue,warnings,sources=[],[],list(coverage.get("warnings",[])) if automatic else [],[];complete=True;revenue_complete=False;land_complete=True
        outcomes=[];location_stats=geocoding_stats([]);location_stats["targetSetStatus"]="unavailable"
        def date_summary(rows):
            dates=[r.get("date") for r in rows if re.fullmatch(r"\d{4}-\d{2}-\d{2}",text(r.get("date")))]
            return {"actualMinDate":min(dates) if dates else None,"actualMaxDate":max(dates) if dates else None,"eligibleCount":sum(r.get("eligible") is True for r in rows)}
        def guard_dates(rows,first,last):
            for row in rows:
                value=text(row.get("date"))
                # Adapters already mark absent/invalid dates ineligible. Apply the
                # explicit cutoff again even if an upstream filter misbehaves.
                if value and not first<=value<=last:
                    row["eligible"]=False
                    row["exclusionReason"]=" · ".join(filter(None,[row.get("exclusionReason"),"조회 기간 또는 분석 기준일 밖 사례"]))
        try:
            extra={"end_date":revenue_cutoff} if explicit_as_of or revenue_cutoff[:7]==dt.date.today().strftime("%Y-%m") else {}
            if automatic:extra["start_date"]=revenue_first
            if scope=="radius":extra.update(scope=scope,lon=lon,lat=lat,radius_km=radius_km)
            revenue,meta=self.revenue(sgg,dong,revenue_start,revenue_end,**extra)
            guard_dates(revenue,revenue_first,revenue_cutoff)
            outcomes=meta.get("geocodingOutcomes",[])
            location_stats=meta.get("geocodingStats",geocoding_stats(outcomes))
            location_incomplete=bool(location_stats.get("errorEventCount") or location_stats.get("P"))
            # Source-page completeness and geocoder progress are independent.
            # The legacy engine rejects all prices on incomplete source pages;
            # a failed location must not discard other verified source records.
            rev_status="partial" if meta["failures"] else "complete"
            revenue_complete=not meta["failures"]
            if meta["failures"]:complete=False;warnings.append("일부 분양 주택형 조회 실패: 분양 자료의 전체성 확인 필요")
            if location_incomplete:complete=False
            warnings.extend(meta.get("coverageWarnings",[]))
            sources.append({"id":"applyhome","name":"한국부동산원 청약홈 APT","url":"https://www.data.go.kr/data/15098547/openapi.do","queriedAt":now(),"collectionStatus":rev_status,"geocodingCollectionStatus":"partial" if location_incomplete else "complete","dataStatus":"available" if revenue else "empty","period":revenue_start+"~"+revenue_end,"requestedStart":revenue_start,"requestedEnd":revenue_end,"effectiveEndDate":revenue_cutoff,"dateBasis":"모집공고일","rawCount":len(revenue),"requestedMonths":revenue_period,**meta,**date_summary(revenue)})
        except ApiError as e:complete=False;warnings.append(e.message);sources.append({"id":"applyhome","name":"청약홈","status":"조회 실패","dataStatus":"failed","collectionStatus":"failed","errorCode":e.code,"requestedStart":revenue_start,"requestedEnd":revenue_end,"effectiveEndDate":revenue_cutoff})
        completed_months=[];failed_months=[];skipped_months=[];stop_land=threading.Event()
        stop_codes={"UPSTREAM_RATE_LIMIT","UPSTREAM_AUTH","KEY_MISSING","LAND_REJECTED","LAND_STORAGE"}
        def read_month(month):
            if stop_land.is_set():
                # A quota failure must not hide other months already on disk.
                if self.land_store is not None and not refresh:
                    try:
                        hit=self.land_store.complete(sgg,month)
                        if hit is not None:
                            self.land_reads[(sgg,month)]={'origin':'local','fetchedAt':hit['fetchedAt'],'resumedPages':0}
                            return month,hit['rows'],None
                    except LandStoreError:pass
                return month,None,ApiError("LAND_NOT_REQUESTED","인증·조회 한도 오류 이후 미요청")
            try:return month,(self.land_month(sgg,month,refresh=True) if refresh and self.land_store is not None else self.land_month(sgg,month)),None
            except ApiError as error:
                if error.code in stop_codes:stop_land.set()
                return month,None,error
        def month_results():
            if automatic:
                # Bounded parallel reads keep initial multi-month queries usable.
                # map preserves chronological output despite response ordering.
                with ThreadPoolExecutor(max_workers=4) as pool:
                    yield from pool.map(read_month,period)
            else:
                yield from map(read_month,period)
        for month,data,month_error in month_results():
            try:
                if month_error:raise month_error
                guard_dates(data,land_first,land_cutoff)
                for row in data:
                    row["sourceEligible"] = row.get("eligible") is not False
                    row["sourceExclusionReasons"] = [row["exclusionReason"]] if row.get("exclusionReason") else []
                    if (land_scope == "dong" and not same_dong(row["dong"],dong)) or row.get("sggCode")!=sgg:
                        row["eligible"]=False
                        row["exclusionReason"]=" · ".join(filter(None,[row.get("exclusionReason"),"지정 토지 비교 범위 밖 사례"]))
                land.extend(data);completed_months.append(month)
                if len(land)>50000:
                    stop_land.set()
                    complete=False;land_complete=False;warnings.append("토지거래 50,000행 처리 한도에 도달했습니다. 전체 기간 수집 미완료로 계산을 보류합니다. 요청 기간은 줄이지 않았습니다.")
                    break
            except ApiError as e:
                complete=False;land_complete=False
                if e.code=="LAND_NOT_REQUESTED":skipped_months.append(month)
                else:failed_months.append({"month":month,"code":e.code,"message":e.message})
        land_complete=land_complete and len(completed_months)==len(period)
        missing_months=[m for m in period if m not in completed_months]
        if failed_months:
            first_error=failed_months[0]
            warnings.append(f"토지 전체 {len(period)}개월 중 {len(completed_months)}개월 수집 · {len(missing_months)}개월 미완료. {first_error['message']} 실패·미요청 월은 자료 출처에서 확인하세요. 요청 기간을 줄이지 않았습니다.")
        sources.append({"id":"land","name":"국토교통부 토지 매매 실거래가","url":"https://www.data.go.kr/data/15126466/openapi.do","queriedAt":now(),"requestedMonths":period,"collectedMonths":completed_months,"failedMonths":failed_months,"skippedMonths":skipped_months,"missingMonths":missing_months,"collectionStatus":"complete" if land_complete else "partial","dataStatus":"available" if land else "empty" if land_complete else "failed","rawCount":len(land),"requestedStart":land_start,"requestedEnd":land_end,"effectiveEndDate":land_cutoff,"dateBasis":"계약일",**date_summary(land)})
        if not complete:
            # Incomplete fetches are inspectable, but never masquerade as a complete
            # comparison universe in downstream financial calculations.
            affected=([] if revenue_complete else revenue)+([] if land_complete else land)
            for row in affected:
                row["eligible"]=False
                row["exclusionReason"]=" · ".join(filter(None,[row.get("exclusionReason"),"부분 수집: 전체 표본 판정 보류"]))
        if land_end==dt.date.today().strftime("%Y-%m"):warnings.append("최근월 토지거래는 신고 반영 중이며 추가·정정될 수 있습니다.")
        warnings.append("과거 기준일로 재조회한 자료는 제공기관의 현재 수정·추가 내역을 반영할 수 있습니다.")
        if outcomes:
            eligible_models=defaultdict(int)
            for row in revenue:
                if row.get("eligible") is True:eligible_models[(row["houseManageNo"],row["announcementNo"])]+=1
            for row in outcomes:
                row["eligibleModelCount"]=eligible_models[(row["houseManageNo"],row["announcementNo"])]
                row["eligible"]=row["eligibleModelCount"]>0
                if not revenue_complete:
                    row["exclusionReason"]=" · ".join(filter(None,[row.get("exclusionReason"),"부분 수집: 전체 표본 판정 보류"]))
            location_stats=geocoding_stats(outcomes);location_stats["targetSetStatus"]="ready"
            for source in sources:
                if source["id"]=="applyhome":
                    source.update(geocodingStats=location_stats,geocodingOutcomes=outcomes,
                                  eligibleComplexCount=len({r["houseManageNo"] for r in outcomes if r["eligible"]}),
                                  **date_summary(revenue))
        result={"revenueCases":revenue,"landCases":land,"sources":sources,"warnings":warnings,"collectionStatus":"complete" if complete else "partial","queriedAt":now(),"query":{"sgg":sgg,"dong":dong,"start":revenue_start,"end":revenue_end,"landStart":land_start,"landEnd":land_end,"revenueStart":revenue_start,"revenueEnd":revenue_end,"asOf":as_of,"landEndDate":land_cutoff,"revenueEndDate":revenue_cutoff,"scope":scope,"radiusKm":radius_km if scope=="radius" else None,"lon":lon if scope=="radius" else None,"lat":lat if scope=="radius" else None,"center":{"lon":lon,"lat":lat} if scope=="radius" else None,"landScope":"dong"},"geocodingStats":location_stats,"geocodingOutcomes":outcomes,"realtimeOnly":True,"persistencePolicy":"session_only","fromCache":False}
        result["query"].update(landScope=land_scope, landRawScope="sgg", landMatchPolicy="custom-twelve-groups", landRulesVersion=RULES_VERSION)
        if automatic:
            result["query"].update(periodMode=period_mode,landStartDate=land_first,revenueStartDate=revenue_first)
            result["coverage"]=coverage
        if rolling:result["query"].update(**window,**selection)
        for source in sources:
            source["effectiveStartDate"]=land_first if source["id"]=="land" else revenue_first
            if automatic:source["periodMode"]=period_mode
            if rolling:source["endExclusive"]=window["endExclusive"]
            if source['id']=='land':
                records=[dict(month=m,**self.land_reads[(sgg,m)]) for m in completed_months if (sgg,m) in self.land_reads]
                source['localStorage']={'enabled':self.land_store is not None,'fileName':self.land_store.path.name if self.land_store else None,
                    'reusedMonths':sum(r['origin']=='local' for r in records),'resumedPages':sum(r['resumedPages'] for r in records),
                    'historyRefreshDays':30,'recentRefreshHours':1,'months':records,'error':self.land_store_error}
                if self.land_store_error:warnings.append(self.land_store_error)
        result["landQuery"] = {k: result["query"][k] for k in ("sgg", "dong", "landStart", "landEnd", "asOf", "landEndDate", "landScope", "landRawScope", "landMatchPolicy", "landRulesVersion")}
        result["landQuery"].update(collectionStatus="complete" if land_complete else "partial", queriedAt=result["queriedAt"])
        if automatic:result["landQuery"].update(periodMode=period_mode,landStartDate=land_first)
        if rolling:result["landQuery"].update(**window,**selection)
        if complete:self.session_cache.set(ck,result)
        return result
