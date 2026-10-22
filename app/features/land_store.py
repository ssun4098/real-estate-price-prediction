"""토지 실거래 캐시를 MySQL에 보관한다.

backend/pf_land_store.py 의 LandStore(SQLite 파일용)와 메서드 이름·캐시 규칙이 같아서
pf_api.Collector 는 아무것도 바꾸지 않고 저장 위치만 MySQL로 바뀐다.
  - 최근 달 자료는 1시간, 지난 달 자료는 30일 동안 다시 받지 않고 재사용
  - 받는 중인 페이지는 하루 동안 이어 받기 가능
"""
from __future__ import annotations

import datetime as dt
import functools
import pathlib
import re

from sqlalchemy import delete, func, select
from sqlalchemy.exc import SQLAlchemyError

from app.db import LandCompleteRow, LandErrorRow, LandPageRow
from pf_land_store import FORMAT, LandStore, LandStoreError

_UNAVAILABLE = "토지 저장소(MySQL)를 읽거나 기록하지 못했습니다. 데이터베이스 상태를 확인하세요."


def _db_errors(method):
    """DB 오류를 Collector가 이해하는 LandStoreError 로 바꾼다."""
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        try:
            return method(self, *args, **kwargs)
        except SQLAlchemyError:
            raise LandStoreError(_UNAVAILABLE) from None
    return wrapper


class MySqlLandStore(LandStore):
    # Collector는 화면 표시용으로 .path.name 만 읽는다.
    path = pathlib.PurePosixPath("mysql/land_trades")

    def __init__(self, sessions, secrets=(), clock=None):
        # LandStore.__init__ 은 SQLite 파일을 여므로 일부러 호출하지 않는다.
        # key / age / encode / decode 검사 규칙은 부모 클래스 것을 그대로 쓴다.
        self.sessions = sessions
        self.secrets = tuple(s for s in secrets if s)
        self.clock = clock or (lambda: dt.datetime.now(dt.timezone.utc))

    @_db_errors
    def complete(self, sgg, month, force=False):
        """다 받아 둔 달 자료. 유효기간이 지났거나 없으면 None."""
        self.key(sgg, month)
        with self.sessions() as session:
            row = session.get(LandCompleteRow, (sgg, month))
            error = session.get(LandErrorRow, (sgg, month))
        if row is None or row.format != FORMAT:
            return None
        if error and error.failed_at >= row.fetched_at:
            return None
        last_month = (self.clock().date().replace(day=1) - dt.timedelta(days=1)).strftime("%Y%m")
        ttl = 3600 if month >= last_month else 30 * 86400
        if force or not 0 <= self.age(row.fetched_at) < ttl:
            return None
        values = self.decode(row.rows_json)
        if len(values) != row.total:
            raise LandStoreError("저장된 토지 행 수가 수집 완료 기록과 다릅니다.")
        return {"rows": values, "fetchedAt": row.fetched_at, "total": row.total}

    @_db_errors
    def pending(self, sgg, month, force=False):
        """받는 중인 페이지들. 이어 받을 수 없는 상태면 빈 목록."""
        self.key(sgg, month)
        with self.sessions() as session:
            pages = list(session.scalars(
                select(LandPageRow).where(LandPageRow.sgg == sgg, LandPageRow.month == month)
                .order_by(LandPageRow.page)))
        if force or not pages:
            return []
        if any(p.format != FORMAT or not 0 <= self.age(p.started_at) < 86400 for p in pages):
            return []
        if [p.page for p in pages] != list(range(1, len(pages) + 1)):
            return []
        if len({(p.total, p.page_size, p.started_at) for p in pages}) != 1:
            return []
        return [{"sgg": p.sgg, "month": p.month, "page": p.page, "format": p.format,
                 "started_at": p.started_at, "total": p.total, "page_size": p.page_size,
                 "rows_json": p.rows_json, "rows": self.decode(p.rows_json)} for p in pages]

    @_db_errors
    def save_page(self, sgg, month, page, rows, total, page_size):
        self.key(sgg, month)
        body = self.encode(rows)
        with self.sessions.begin() as session:
            if page == 1:
                session.execute(delete(LandPageRow).where(LandPageRow.sgg == sgg, LandPageRow.month == month))
                started = self.clock().isoformat()
            else:
                first = session.get(LandPageRow, (sgg, month, 1))
                if first is None or (first.total, first.page_size) != (total, page_size):
                    raise LandStoreError("토지 페이지의 전체 건수가 변경돼 다시 조회해야 합니다.")
                started = first.started_at
            session.merge(LandPageRow(sgg=sgg, month=month, page=page, format=FORMAT, started_at=started,
                                      total=total, page_size=page_size, rows_json=body))

    @_db_errors
    def finish(self, sgg, month, rows, total):
        """마지막 페이지까지 받았으면 한 달 자료로 합치고, 페이지·실패 기록은 지운다."""
        if len(rows) != total:
            raise LandStoreError("미완료 자료를 토지 수집 완료로 저장할 수 없습니다.")
        body = self.encode(rows)
        stamp = self.clock().isoformat()
        with self.sessions.begin() as session:
            session.merge(LandCompleteRow(sgg=sgg, month=month, format=FORMAT, fetched_at=stamp,
                                          total=total, rows_json=body))
            session.execute(delete(LandPageRow).where(LandPageRow.sgg == sgg, LandPageRow.month == month))
            session.execute(delete(LandErrorRow).where(LandErrorRow.sgg == sgg, LandErrorRow.month == month))
        return stamp

    @_db_errors
    def failure(self, sgg, month, code):
        self.key(sgg, month)
        # 오류 메시지·URL에는 인증키가 섞일 수 있어서 우리 쪽 오류 코드만 남긴다.
        if not re.fullmatch(r"[A-Z_]{1,64}", code):
            code = "UPSTREAM_ERROR"
        with self.sessions.begin() as session:
            session.merge(LandErrorRow(sgg=sgg, month=month, code=code, failed_at=self.clock().isoformat()))

    @_db_errors
    def summary(self, sgg=None):
        """/api/land-cache 화면용 요약."""
        if sgg is not None and not re.fullmatch(r"\d{5}", sgg):
            raise LandStoreError("시군구 코드는 5자리여야 합니다.")

        def only_sgg(statement, model):
            return statement.where(model.sgg == sgg) if sgg else statement

        with self.sessions() as session:
            complete = session.execute(only_sgg(
                select(LandCompleteRow.sgg, LandCompleteRow.month, LandCompleteRow.total, LandCompleteRow.fetched_at),
                LandCompleteRow).order_by(LandCompleteRow.sgg, LandCompleteRow.month)).all()
            pending = session.execute(only_sgg(
                select(LandPageRow.sgg, LandPageRow.month, func.max(LandPageRow.page).label("saved_pages"),
                       func.max(LandPageRow.total).label("total")),
                LandPageRow).group_by(LandPageRow.sgg, LandPageRow.month)).all()
            failures = session.execute(only_sgg(select(LandErrorRow), LandErrorRow)
                                       .order_by(LandErrorRow.sgg, LandErrorRow.month)).scalars().all()
        months = [dict(r._mapping) for r in complete]
        return {"enabled": True, "fileName": self.path.name, "completedMonths": len(months),
                "storedRows": sum(r["total"] for r in months), "months": months,
                "pending": [dict(r._mapping) for r in pending],
                "failures": [{"sgg": f.sgg, "month": f.month, "code": f.code, "failed_at": f.failed_at}
                             for f in failures],
                "policy": "recent_1h_history_30d",
                "note": "토지 원자료만 DB 보관 · 인증키·Geocoder 위치자료 제외"}
