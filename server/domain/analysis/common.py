"""공통 도구: 숫자·날짜 입력 검사, 통계(중앙값 등), 입력에서 비밀값 제거.

원 단위·㎡·날짜만 다룬다. 비어 있으면(None) "모름", 직접 입력한 0은 유효한 가정이다.
"""
from __future__ import annotations

import datetime as dt
import math
import re
from urllib.parse import parse_qsl, urlsplit


VERSION = "pf-study-5"
WON_PER_MANWON = 10000
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


def _input_error(errors, section, path, message):
    if errors is None:
        raise ValueError(message)
    error = {"section": section, "path": path, "message": str(message)}
    if error not in errors:
        errors.append(error)
