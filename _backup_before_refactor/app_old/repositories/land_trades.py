"""MySQL implementation of the land-trade store used by ``pf_api.Collector``.

It keeps the exact interface and cache policy of ``pf_land_store.LandStore``
(SQLite), so the collector does not change; only where the rows live does.
Key/age/encode/decode rules are inherited rather than copied.
"""
from __future__ import annotations

import pathlib
import re

from sqlalchemy import delete, func, select
from sqlalchemy.exc import SQLAlchemyError

from app.db.models import LandCompleteRow, LandErrorRow, LandPageRow
from pf_land_store import FORMAT, LandStore, LandStoreError

_UNAVAILABLE = "토지 저장소(MySQL)를 읽거나 기록하지 못했습니다. 데이터베이스 상태를 확인하세요."


def _guarded(method):
    def wrapper(self, *args, **kwargs):
        try:
            return method(self, *args, **kwargs)
        except SQLAlchemyError:
            raise LandStoreError(_UNAVAILABLE) from None
    wrapper.__name__ = method.__name__
    return wrapper


class MySqlLandStore(LandStore):
    # ``Collector`` only reads ``.path.name`` for display.
    path = pathlib.PurePosixPath("mysql/land_trades")

    def __init__(self, session_factory, secrets=(), clock=None):
        # Deliberately not calling LandStore.__init__ (it opens a SQLite file).
        import datetime as dt
        self.session_factory = session_factory
        self.secrets = tuple(s for s in secrets if s)
        self.clock = clock or (lambda: dt.datetime.now(dt.timezone.utc))

    @_guarded
    def complete(self, sgg, month, force=False):
        self.key(sgg, month)
        with self.session_factory() as session:
            row = session.get(LandCompleteRow, (sgg, month))
            error = session.get(LandErrorRow, (sgg, month))
        if row is None or row.format != FORMAT:
            return None
        if error and error.failed_at >= row.fetched_at:
            return None
        import datetime as dt
        recent = month >= (self.clock().date().replace(day=1) - dt.timedelta(days=1)).strftime("%Y%m")
        ttl = 3600 if recent else 30 * 86400
        if force or not 0 <= self.age(row.fetched_at) < ttl:
            return None
        values = self.decode(row.rows_json)
        if len(values) != row.total:
            raise LandStoreError("저장된 토지 행 수가 수집 완료 기록과 다릅니다.")
        return {"rows": values, "fetchedAt": row.fetched_at, "total": row.total}

    @_guarded
    def pending(self, sgg, month, force=False):
        self.key(sgg, month)
        with self.session_factory() as session:
            pages = list(session.scalars(
                select(LandPageRow).where(LandPageRow.sgg == sgg, LandPageRow.month == month).order_by(LandPageRow.page)))
        if force or not pages or any(p.format != FORMAT or not 0 <= self.age(p.started_at) < 86400 for p in pages):
            return []
        if [p.page for p in pages] != list(range(1, len(pages) + 1)):
            return []
        if len({(p.total, p.page_size, p.started_at) for p in pages}) != 1:
            return []
        return [{"sgg": p.sgg, "month": p.month, "page": p.page, "format": p.format, "started_at": p.started_at,
                 "total": p.total, "page_size": p.page_size, "rows_json": p.rows_json,
                 "rows": self.decode(p.rows_json)} for p in pages]

    @_guarded
    def save_page(self, sgg, month, page, rows, total, page_size):
        self.key(sgg, month)
        body = self.encode(rows)
        with self.session_factory.begin() as session:
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

    @_guarded
    def finish(self, sgg, month, rows, total):
        if len(rows) != total:
            raise LandStoreError("미완료 자료를 토지 수집 완료로 저장할 수 없습니다.")
        body = self.encode(rows)
        stamp = self.clock().isoformat()
        with self.session_factory.begin() as session:
            session.merge(LandCompleteRow(sgg=sgg, month=month, format=FORMAT, fetched_at=stamp, total=total, rows_json=body))
            session.execute(delete(LandPageRow).where(LandPageRow.sgg == sgg, LandPageRow.month == month))
            session.execute(delete(LandErrorRow).where(LandErrorRow.sgg == sgg, LandErrorRow.month == month))
        return stamp

    @_guarded
    def failure(self, sgg, month, code):
        self.key(sgg, month)
        # Error messages/URLs can contain credentials; persist only our own code.
        if not re.fullmatch(r"[A-Z_]{1,64}", code):
            code = "UPSTREAM_ERROR"
        with self.session_factory.begin() as session:
            session.merge(LandErrorRow(sgg=sgg, month=month, code=code, failed_at=self.clock().isoformat()))

    @_guarded
    def summary(self, sgg=None):
        if sgg is not None and not re.fullmatch(r"\d{5}", sgg):
            raise LandStoreError("시군구 코드는 5자리여야 합니다.")
        with self.session_factory() as session:
            def scoped(statement, model):
                return statement.where(model.sgg == sgg) if sgg else statement

            complete = session.execute(scoped(
                select(LandCompleteRow.sgg, LandCompleteRow.month, LandCompleteRow.total, LandCompleteRow.fetched_at),
                LandCompleteRow).order_by(LandCompleteRow.sgg, LandCompleteRow.month)).all()
            pending = session.execute(scoped(
                select(LandPageRow.sgg, LandPageRow.month, func.max(LandPageRow.page).label("saved_pages"),
                       func.max(LandPageRow.total).label("total")),
                LandPageRow).group_by(LandPageRow.sgg, LandPageRow.month)).all()
            failures = session.execute(scoped(select(LandErrorRow), LandErrorRow).order_by(LandErrorRow.sgg, LandErrorRow.month)).scalars().all()
        months = [dict(r._mapping) for r in complete]
        return {"enabled": True, "fileName": self.path.name, "completedMonths": len(months),
                "storedRows": sum(r["total"] for r in months), "months": months,
                "pending": [dict(r._mapping) for r in pending],
                "failures": [{"sgg": f.sgg, "month": f.month, "code": f.code, "failed_at": f.failed_at} for f in failures],
                "policy": "recent_1h_history_30d",
                "note": "토지 원자료만 DB 보관 · 인증키·Geocoder 위치자료 제외"}
