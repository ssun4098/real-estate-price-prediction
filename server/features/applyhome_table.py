"""청약홈 분양정보를 직접 적재한 DB 테이블에서 읽는다. URL 없음.

    applyhome_apt_notice   분양 공고 (house_manage_no + pblanc_no 가 공고 하나)
    applyhome_apt_model    공고별 주택형 (공급면적·분양가)
    applyhome_fail         적재 실패 기록

이 앱은 위 테이블을 읽기만 한다 (만들거나 고치지 않음). 적재는 별도 작업(나중에 스케줄러)이 맡는다.

Collector 는 청약홈 API(odcloud)를 부르는 대신 이 객체의 query()/count() 를 부른다 (main.py).
돌려주는 행은 API 응답과 같은 필드 이름(대문자)이라서 분양사례 계산 코드는 바뀌지 않는다.
  - 열에 있는 값을 먼저 쓰고, extra(JSON)에 있는 나머지 원본 필드(특별공급 세대수 등)를 덧붙인다.
  - 조건은 앱이 실제로 쓰는 것만 받는다. 모르는 조건이 오면 조용히 무시하지 않고 오류를 낸다.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from server.domain.public_api import ApiError

_UNAVAILABLE = "청약홈 분양정보 DB(applyhome_apt_*)를 읽지 못했습니다. 데이터베이스 상태를 확인하세요."

# API 필드 이름 → DB 열 이름
NOTICE_COLUMNS = {
    "HOUSE_MANAGE_NO": "house_manage_no", "PBLANC_NO": "pblanc_no", "HOUSE_NM": "house_nm",
    "HOUSE_SECD": "house_secd", "HOUSE_DTL_SECD": "house_dtl_secd", "RENT_SECD": "rent_secd",
    "HSSPLY_ADRES": "hssply_adres", "RCRIT_PBLANC_DE": "rcrit_pblanc_de",
    "BSNS_MBY_NM": "bsns_mby_nm", "CNSTRCT_ENTRPS_NM": "cnstrct_entrps_nm", "PBLANC_URL": "pblanc_url",
}
MODEL_COLUMNS = {
    "HOUSE_MANAGE_NO": "house_manage_no", "PBLANC_NO": "pblanc_no", "MODEL_NO": "model_no",
    "HOUSE_TY": "house_ty", "SUPLY_AR": "suply_ar", "SUPLY_HSHLDCO": "suply_hshldco",
    "SPSPLY_HSHLDCO": "spsply_hshldco", "LTTOT_TOP_AMOUNT": "lttot_top_amount",
}
# API 경로 → (테이블, 열 대응표, 정렬)
SOURCES = {
    "getAPTLttotPblancDetail": ("applyhome_apt_notice", NOTICE_COLUMNS, "rcrit_pblanc_de, house_manage_no, pblanc_no"),
    "getAPTLttotPblancMdl": ("applyhome_apt_model", MODEL_COLUMNS, "house_manage_no, pblanc_no, model_no"),
}
OPERATORS = {"EQ": "=", "GTE": ">=", "LTE": "<=", "LT": "<", "LIKE": "LIKE"}


class ApplyhomeTable:
    def __init__(self, sessions):
        self.sessions = sessions

    def query(self, path, conditions) -> list[dict]:
        """odcloud(path, conditions) 와 같은 결과: 조건에 맞는 행 전체 (API 필드 이름)."""
        table, columns, order = _source(path)
        where, params = _where(columns, conditions)
        select = ", ".join(sorted(set(columns.values()) | {"extra"}))
        sql = text(f"SELECT {select} FROM {table}{where} ORDER BY {order}")
        try:
            with self.sessions() as session:
                rows = session.execute(sql, params).mappings().all()
        except SQLAlchemyError:
            raise ApiError("APPLYHOME_STORAGE", _UNAVAILABLE, 503) from None
        return [_as_api_row(row, columns) for row in rows]

    def count(self, conditions) -> int:
        """_coverage_count 와 같은 결과: 조건에 맞는 공고 수."""
        table, columns, _ = _source("getAPTLttotPblancDetail")
        where, params = _where(columns, conditions)
        try:
            with self.sessions() as session:
                return int(session.execute(text(f"SELECT COUNT(*) FROM {table}{where}"), params).scalar() or 0)
        except SQLAlchemyError:
            raise ApiError("APPLYHOME_STORAGE", _UNAVAILABLE, 503) from None


def _source(path):
    if path not in SOURCES:
        raise ApiError("APPLYHOME_UNSUPPORTED", f"DB에서 지원하지 않는 청약홈 조회입니다: {path}", 500)
    return SOURCES[path]


def _where(columns, conditions) -> tuple[str, dict]:
    """{"cond[RCRIT_PBLANC_DE::GTE]": "2021-10-01", ...} → (" WHERE ...", 매개변수). 값은 항상 매개변수로 넘긴다."""
    clauses, params = [], {}
    for i, (key, value) in enumerate(conditions.items()):
        match = re.fullmatch(r"cond\[([A-Z_]+)::([A-Z]+)\]", key)
        if not match or match.group(1) not in columns or match.group(2) not in OPERATORS:
            raise ApiError("APPLYHOME_UNSUPPORTED", f"DB에서 지원하지 않는 청약홈 조건입니다: {key}", 500)
        field, op = match.groups()
        clauses.append(f"{columns[field]} {OPERATORS[op]} :p{i}")
        params[f"p{i}"] = f"%{value}%" if op == "LIKE" else value
    return (" WHERE " + " AND ".join(clauses) if clauses else ""), params


def _as_api_row(row, columns) -> dict:
    """DB 한 줄 → API 응답과 같은 모양의 dict."""
    result = {field: _plain(row[column]) for field, column in columns.items()}
    extra = row.get("extra")
    if isinstance(extra, (str, bytes)):
        try:
            extra = json.loads(extra)
        except ValueError:
            extra = None
    if isinstance(extra, dict):
        for key, value in extra.items():
            result.setdefault(str(key).upper(), value)  # 열에 있는 값이 우선
    return result


def _plain(value):
    """JSON으로 보낼 수 있고 API와 같은 모양의 값으로 (날짜 → 'YYYY-MM-DD', Decimal → 문자열)."""
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()[:10]
    if isinstance(value, Decimal):
        return str(value)
    return value
