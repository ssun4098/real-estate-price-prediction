"""토지 실거래를 직접 적재한 DB 테이블(land_trade)에서 읽는다. URL 없음.

    land_trade       거래 한 건이 한 줄 (lawd_cd=시군구 5자리, deal_ym=거래년월 YYYYMM)
    land_trade_job   시군구·월마다 적재 기록 (total_count=API가 알려 준 전체 건수, loaded_rows=넣은 건수)
    land_trade_fail  적재 실패 기록

이 파일은 위 테이블을 읽기만 한다 (만들거나 고치지 않음). 매일 갱신은 features/daily_load.py 가 맡는다.

규칙
  - land_trade_job 에 기록이 있고 loaded_rows ≥ total_count 인 달만 "다 받은 달"로 쓴다.
    기록이 없는 달은 0건으로 치지 않고 None(= 아직 적재 안 됨)을 돌려준다.
  - 거래 한 건의 판정(취소·지분·금액 0 제외)은 API로 받을 때와 같은 함수 land_trade_row 를 쓴다.
  - 행 id 는 API로 받을 때와 같은 모양(land-시군구-월-페이지-순번, 100건 한 페이지)으로 만든다.

Collector 는 이 객체를 land_store 자리에 두고 land_source="table" 로 쓴다 (main.py).
"""
from __future__ import annotations

import datetime as dt
import pathlib
import re

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from server.domain.land_store import LandStoreError
from server.domain.public_api import land_trade_row

_UNAVAILABLE = "토지 실거래 DB(land_trade)를 읽지 못했습니다. 데이터베이스 상태를 확인하세요."
PAGE_SIZE = 100  # API 페이지 크기와 같게 해서 행 id 모양을 맞춘다

_MONTH_ROWS = text("""
    SELECT id, lawd_cd, deal_date, umd_nm, jibun, jimok, land_use, deal_amount_manwon, deal_area_m2,
           share_dealing_type, cdeal_type, cdeal_day
    FROM land_trade
    WHERE lawd_cd = :sgg AND deal_ym = :month
    ORDER BY id
""")
_JOB = text("SELECT total_count, loaded_rows, loaded_at FROM land_trade_job WHERE lawd_cd = :sgg AND deal_ym = :month")


class LandTradeTable:
    # Collector 가 화면 표시용으로 .path.name 을 읽는다.
    path = pathlib.PurePosixPath("mysql/land_trade")

    def __init__(self, sessions):
        self.sessions = sessions

    def complete(self, sgg, month, force=False):
        """다 적재된 달의 비교사례 행. 아직 적재되지 않았거나 덜 적재된 달이면 None."""
        _check_key(sgg, month)
        try:
            with self.sessions() as session:
                job = session.execute(_JOB, {"sgg": sgg, "month": month}).first()
                if job is None or job.total_count is None or (job.loaded_rows or 0) < job.total_count:
                    return None
                rows = session.execute(_MONTH_ROWS, {"sgg": sgg, "month": month}).all()
        except SQLAlchemyError:
            raise LandStoreError(_UNAVAILABLE) from None
        records = [land_trade_row(sgg, month, i // PAGE_SIZE + 1, i % PAGE_SIZE, _as_api_fields(row))
                   for i, row in enumerate(rows)]
        loaded_at = job.loaded_at.isoformat() if hasattr(job.loaded_at, "isoformat") else str(job.loaded_at or "")
        return {"rows": records, "fetchedAt": loaded_at, "total": len(records)}

    def summary(self, sgg=None):
        """/api/land-cache 화면용 요약. 시군구를 지정하면 월별 목록까지, 아니면 전체 건수만."""
        if sgg is not None and not re.fullmatch(r"\d{5}", sgg):
            raise LandStoreError("시군구 코드는 5자리여야 합니다.")
        where = "WHERE lawd_cd = :sgg" if sgg else ""
        try:
            with self.sessions() as session:
                totals = session.execute(text(
                    f"SELECT COUNT(*) AS months, COALESCE(SUM(loaded_rows), 0) AS stored FROM land_trade_job {where} "
                    f"{'AND' if sgg else 'WHERE'} loaded_rows >= total_count"), {"sgg": sgg}).first()
                months = [] if not sgg else [
                    {"sgg": r.lawd_cd, "month": r.deal_ym, "total": r.loaded_rows,
                     "fetched_at": r.loaded_at.isoformat() if hasattr(r.loaded_at, "isoformat") else r.loaded_at}
                    for r in session.execute(text(
                        "SELECT lawd_cd, deal_ym, loaded_rows, loaded_at FROM land_trade_job "
                        "WHERE lawd_cd = :sgg AND loaded_rows >= total_count ORDER BY deal_ym"), {"sgg": sgg})]
                failures = [
                    {"sgg": r.lawd_cd, "month": r.deal_ym, "code": "LOAD_FAILED",
                     "failed_at": r.last_failed_at.isoformat() if hasattr(r.last_failed_at, "isoformat") else r.last_failed_at}
                    for r in session.execute(text(
                        f"SELECT lawd_cd, deal_ym, last_failed_at FROM land_trade_fail {where} "
                        "ORDER BY lawd_cd, deal_ym LIMIT 200"), {"sgg": sgg})]
        except SQLAlchemyError:
            raise LandStoreError(_UNAVAILABLE) from None
        return {"enabled": True, "fileName": self.path.name, "completedMonths": int(totals.months),
                "storedRows": int(totals.stored), "months": months, "pending": [], "failures": failures,
                "policy": "database_table",
                "note": "직접 적재한 land_trade 테이블에서 읽음 · 공공데이터 API는 부르지 않음"}

    # --- Collector 가 API 모드에서 부르는 메서드: 이 모드에서는 쓰지 않는다 ---------------------
    def pending(self, sgg, month, force=False):
        return []

    def failure(self, sgg, month, code):
        pass  # 적재 실패 기록은 적재 작업(land_trade_fail)이 남긴다


def _check_key(sgg, month):
    if not re.fullmatch(r"\d{5}", str(sgg)) or not re.fullmatch(r"\d{6}", str(month)):
        raise LandStoreError("토지 실거래 조회 키(시군구 5자리·연월 6자리)가 올바르지 않습니다.")


def _as_api_fields(row) -> dict:
    """DB 한 줄 → API 응답과 같은 필드 이름의 dict (land_trade_row 가 그대로 판정할 수 있게)."""
    date = row.deal_date
    if isinstance(date, str):  # 드라이버에 따라 문자열로 올 수 있음
        try:
            date = dt.date.fromisoformat(date[:10])
        except ValueError:
            date = None
    return {
        "dealAmount": "" if row.deal_amount_manwon is None else str(row.deal_amount_manwon),
        "dealArea": "" if row.deal_area_m2 is None else str(row.deal_area_m2),
        "dealYear": str(date.year) if date else "0",
        "dealMonth": str(date.month) if date else "0",
        "dealDay": str(date.day) if date else "0",
        "umdNm": row.umd_nm or "",
        "jibun": row.jibun or "",
        "jimok": row.jimok or "",
        "landUse": row.land_use or "",
        "sggCd": row.lawd_cd,
        "shareDealingType": row.share_dealing_type or "",
        "cdealType": row.cdeal_type or "",
        "cdealDay": row.cdeal_day or "",
    }
