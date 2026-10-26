"""매일 공공데이터를 받아 직접 적재한 DB 테이블을 최신으로 유지한다.

    GET  /api/daily-load        마지막 실행 결과와 다음 실행 시각
    POST /api/daily-load/run    지금 바로 한 번 실행 (이미 돌고 있으면 409)

서버가 켜질 때(main.py) 백그라운드 스레드가 하나 뜨고, 매일 DAILY_LOAD_TIME(한국 시각, 기본 03:00)에 실행한다.

하는 일 (처음 적재에 쓴 land_trade.py / applyhome.py 의 load 규칙을 그대로 따른다)
  1. 토지 실거래: 지난 달부터 DAILY_LOAD_MONTHS 개월(기본 3) × land_trade_job 에 있는 시군구를 다시 받는다.
     늦게 들어온 신고·해제 신고를 반영하려고 지난 몇 달도 매번 다시 받는다.
     한 달 단위로 DELETE → INSERT 하고 land_trade_job 에 total_count·loaded_rows 를 기록한다.
     실패한 달은 land_trade_fail 에 남기고 다음 달로 넘어간다 (그 달의 기존 자료는 그대로 둔다).
  2. 청약홈: 공고(apt)·주택형(apt_mdl) 전체를 받아 REPLACE 한다. 실패한 쪽은 applyhome_fail 에 남긴다.
  - 인증키 오류·일일 한도 초과가 나면 그 자리에서 멈춘다 (다음 날 다시 시도).
  - 같은 DB에 서버가 여러 개 붙어도 한 번만 돌도록 MySQL 잠금(GET_LOCK)을 건다.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import threading
import time

from fastapi import APIRouter, Request
from sqlalchemy import text

from server.domain.public_api import KOREA_TIMEZONE, ApiError, Collector
from server.web import ok, redact

router = APIRouter(prefix="/api/daily-load")
log = logging.getLogger("uvicorn.error")

LAND_URL = "https://apis.data.go.kr/1613000/RTMSDataSvcLandTrade/getRTMSDataSvcLandTrade"
APPLYHOME_URL = "https://api.odcloud.kr/api/ApplyhomeInfoDetailSvc/v1/"
APPLYHOME_ENDPOINTS = {"apt": "getAPTLttotPblancDetail", "apt_mdl": "getAPTLttotPblancMdl"}
LAND_STOP_CODES = {"22", "022", "30", "31", "32", "33", "20", "21"}   # 한도 초과·키 오류·접근 거부
STOP_API_CODES = {"UPSTREAM_AUTH", "UPSTREAM_RATE_LIMIT", "KEY_MISSING"}
RETRY_API_CODES = {"UPSTREAM_NETWORK", "UPSTREAM_HTTP", "INVALID_XML", "INVALID_JSON"}
LOCK_NAME = "v6_daily_load"


# ---------------------------------------------------------------------------
# 라우터
# ---------------------------------------------------------------------------
@router.get("")
def daily_load_status(request: Request):
    return ok(request.app.state.daily_load.status())


@router.post("/run")
def daily_load_run(request: Request):
    request.app.state.daily_load.run_in_background()
    return ok(request.app.state.daily_load.status())


# ---------------------------------------------------------------------------
# 매일 적재
# ---------------------------------------------------------------------------
class _Stop(Exception):
    """인증키·한도 문제: 오늘은 더 부르지 않는다."""


class DailyLoader:
    def __init__(self, sessions, collector: Collector, *, enabled=True, run_at="03:00", months=3, delay=0.25, retry_wait=2.0):
        self.sessions = sessions
        self.collector = collector
        self.enabled = enabled
        self.run_at = dt.time.fromisoformat(run_at)
        self.months = months
        self.delay = delay              # 호출 사이 쉬는 시간(초). 제공기관에 부담을 주지 않으려고
        self.retry_wait = retry_wait    # 네트워크 오류 뒤 다시 시도하기 전 기다리는 시간(초)
        self.running = threading.Lock()
        self.last: dict | None = None
        self.progress: dict | None = None
        self._stop = threading.Event()

    # --- 스레드 --------------------------------------------------------------
    def start(self):
        if self.enabled:
            threading.Thread(target=self._loop, name="daily-load", daemon=True).start()

    def stop(self):
        self._stop.set()

    def _loop(self):
        while not self._stop.is_set():
            wait = (self.next_run() - dt.datetime.now(KOREA_TIMEZONE)).total_seconds()
            if self._stop.wait(max(1.0, wait)):
                return
            self.run_once()

    def next_run(self) -> dt.datetime:
        now = dt.datetime.now(KOREA_TIMEZONE)
        today = dt.datetime.combine(now.date(), self.run_at, tzinfo=KOREA_TIMEZONE)
        return today if today > now else today + dt.timedelta(days=1)

    def run_in_background(self):
        if self.running.locked():
            raise ApiError("ALREADY_RUNNING", "매일 적재가 이미 실행 중입니다. 끝난 뒤 다시 시도하세요.", 409)
        threading.Thread(target=self.run_once, name="daily-load-now", daemon=True).start()

    def status(self) -> dict:
        return {"enabled": self.enabled, "running": self.running.locked(),
                "nextRunAt": self.next_run().isoformat(timespec="minutes") if self.enabled else None,
                "months": self.months, "progress": self.progress, "last": self.last}

    # --- 한 번 실행 ------------------------------------------------------------
    def run_once(self) -> dict | None:
        if not self.running.acquire(blocking=False):
            return None
        summary = {"startedAt": _now(), "finishedAt": None, "land": {"ok": 0, "failed": 0, "months": []},
                   "applyhome": {}, "stopped": None, "error": None}
        self.progress = summary
        try:
            with self.sessions() as lock_session:
                if not _acquire_db_lock(lock_session):
                    summary["error"] = "다른 서버가 이미 적재 중입니다."
                    return summary
                try:
                    key = self.collector.require("dataGoKr")
                    self._load_land(key, summary["land"])
                    self._load_applyhome(key, summary["applyhome"])
                finally:
                    _release_db_lock(lock_session)
        except _Stop as exc:
            summary["stopped"] = redact(str(exc))
        except ApiError as exc:
            summary["error"] = redact(exc.message)
        except Exception as exc:  # noqa: BLE001 - 스레드가 죽지 않게. 내용은 종류만 남긴다
            summary["error"] = f"적재 중 오류가 발생했습니다 ({type(exc).__name__})."
        finally:
            summary["finishedAt"] = _now()
            self.last, self.progress = summary, None
            self.running.release()
            log.info("매일 적재 끝: 토지 성공 %d · 실패 %d, 청약홈 %s, 중단 %s, 오류 %s",
                     summary["land"]["ok"], summary["land"]["failed"], summary["applyhome"],
                     summary["stopped"], summary["error"])
            self._save_last(summary)
        return summary

    # --- 1. 토지 실거래 ----------------------------------------------------------
    def _load_land(self, key, result):
        with self.sessions() as session:
            sggs = [row[0] for row in session.execute(text("SELECT DISTINCT lawd_cd FROM land_trade_job ORDER BY lawd_cd"))]
        months = recent_months(self.months)
        result["months"] = months
        for ym in months:
            for sgg in sggs:
                try:
                    total, items = self._fetch_land(key, sgg, ym)
                except ApiError as exc:
                    self._land_failed(sgg, ym, exc)
                    result["failed"] += 1
                    continue
                self._write_land(sgg, ym, total, items)
                result["ok"] += 1

    def _fetch_land(self, key, sgg, ym):
        items, total, page = [], 0, 1
        while True:
            root = self._call(LAND_URL, {"serviceKey": key, "LAWD_CD": sgg, "DEAL_YMD": ym,
                                         "pageNo": page, "numOfRows": 1000}, "xml")
            code = root.findtext(".//resultCode") or root.findtext(".//returnReasonCode")
            if code in LAND_STOP_CODES:
                raise _Stop(f"토지 실거래 API 응답 코드 {code} (한도 초과 또는 인증키 문제)")
            if code not in ("000", "00", "0", None):
                raise ApiError("LAND_REJECTED", f"토지 실거래 API 응답 코드 {code}")
            total = int(root.findtext(".//totalCount") or 0)
            got = [{child.tag: (child.text or "").strip() for child in item} for item in root.findall(".//item")]
            items += got
            if len(items) >= total or not got:
                break
            page += 1
        if len(items) != total:
            raise ApiError("PARTIAL_COLLECTION", f"건수 불일치: 전체 {total}건인데 {len(items)}건 수신")
        return total, items

    def _write_land(self, sgg, ym, total, items):
        rows = [land_trade_values(sgg, ym, item) for item in items]
        with self.sessions.begin() as session:
            session.execute(text("DELETE FROM land_trade WHERE lawd_cd = :sgg AND deal_ym = :ym"), {"sgg": sgg, "ym": ym})
            for i in range(0, len(rows), 2000):
                session.execute(text(
                    "INSERT INTO land_trade (lawd_cd, deal_ym, deal_date, umd_nm, jibun, jimok, land_use, "
                    "deal_amount_manwon, deal_area_m2, dealing_gbn, share_dealing_type, cdeal_type, cdeal_day, "
                    "agent_sgg_nm, extra) VALUES (:lawd_cd, :deal_ym, :deal_date, :umd_nm, :jibun, :jimok, :land_use, "
                    ":deal_amount_manwon, :deal_area_m2, :dealing_gbn, :share_dealing_type, :cdeal_type, :cdeal_day, "
                    ":agent_sgg_nm, :extra)"), rows[i:i + 2000])
            session.execute(text("REPLACE INTO land_trade_job (lawd_cd, deal_ym, total_count, loaded_rows, loaded_at) "
                                 "VALUES (:sgg, :ym, :total, :loaded, :at)"),
                            {"sgg": sgg, "ym": ym, "total": total, "loaded": len(rows), "at": _db_now()})
            session.execute(text("DELETE FROM land_trade_fail WHERE lawd_cd = :sgg AND deal_ym = :ym"), {"sgg": sgg, "ym": ym})

    def _land_failed(self, sgg, ym, exc):
        with self.sessions.begin() as session:
            updated = session.execute(text(
                "UPDATE land_trade_fail SET error = :error, attempts = attempts + 1, last_failed_at = :at "
                "WHERE lawd_cd = :sgg AND deal_ym = :ym"), {"sgg": sgg, "ym": ym, "error": redact(exc.message)[:500], "at": _db_now()})
            if updated.rowcount == 0:
                session.execute(text("INSERT INTO land_trade_fail (lawd_cd, deal_ym, error, attempts, last_failed_at) "
                                     "VALUES (:sgg, :ym, :error, 1, :at)"),
                                {"sgg": sgg, "ym": ym, "error": redact(exc.message)[:500], "at": _db_now()})

    # --- 2. 청약홈 ---------------------------------------------------------------
    def _load_applyhome(self, key, result):
        for endpoint, path in APPLYHOME_ENDPOINTS.items():
            rows, failed_pages, page, total = [], [], 1, None
            while total is None or (page - 1) * 100 < total:
                try:
                    data = self._call(APPLYHOME_URL + path, {"serviceKey": key, "page": page, "perPage": 100}, "json")
                    if not isinstance(data.get("data"), list):
                        raise _Stop(f"청약홈 API 응답에 자료가 없습니다 (코드 {data.get('code')}). 인증키·승인 상태를 확인하세요.")
                    total = int(data.get("matchCount", data.get("totalCount")) or 0)
                    rows += data["data"]
                except ApiError as exc:
                    if total is None:
                        raise  # 첫 쪽부터 실패하면 전체 건수를 모르므로 이번 회차는 포기
                    failed_pages.append(page)
                    self._applyhome_failed(endpoint, page, exc)
                page += 1
            self._write_applyhome(endpoint, rows)
            result[endpoint] = {"total": total, "received": len(rows), "failedPages": failed_pages}

    def _write_applyhome(self, endpoint, rows):
        if endpoint == "apt":
            values = {(v["house_manage_no"], v["pblanc_no"]): v for v in map(applyhome_notice_values, rows)}
            sql = ("REPLACE INTO applyhome_apt_notice (house_manage_no, pblanc_no, house_nm, house_secd, house_dtl_secd, "
                   "rent_secd, hssply_adres, rcrit_pblanc_de, bsns_mby_nm, cnstrct_entrps_nm, pblanc_url, extra) VALUES "
                   "(:house_manage_no, :pblanc_no, :house_nm, :house_secd, :house_dtl_secd, :rent_secd, :hssply_adres, "
                   ":rcrit_pblanc_de, :bsns_mby_nm, :cnstrct_entrps_nm, :pblanc_url, :extra)")
        else:
            values = {(v["house_manage_no"], v["pblanc_no"], v["model_no"]): v for v in map(applyhome_model_values, rows)}
            sql = ("REPLACE INTO applyhome_apt_model (house_manage_no, pblanc_no, model_no, house_ty, suply_ar, "
                   "suply_hshldco, spsply_hshldco, lttot_top_amount, extra) VALUES (:house_manage_no, :pblanc_no, "
                   ":model_no, :house_ty, :suply_ar, :suply_hshldco, :spsply_hshldco, :lttot_top_amount, :extra)")
        batch = list(values.values())
        with self.sessions.begin() as session:
            for i in range(0, len(batch), 1000):
                session.execute(text(sql), batch[i:i + 1000])

    def _applyhome_failed(self, endpoint, page, exc):
        with self.sessions.begin() as session:
            updated = session.execute(text(
                "UPDATE applyhome_fail SET error = :error, attempts = attempts + 1, last_failed_at = :at "
                "WHERE endpoint = :ep AND page = :page"), {"ep": endpoint, "page": page, "error": redact(exc.message)[:500], "at": _db_now()})
            if updated.rowcount == 0:
                session.execute(text("INSERT INTO applyhome_fail (endpoint, page, error, attempts, last_failed_at) "
                                     "VALUES (:ep, :page, :error, 1, :at)"),
                                {"ep": endpoint, "page": page, "error": redact(exc.message)[:500], "at": _db_now()})

    # --- 공통 ----------------------------------------------------------------
    def _call(self, url, params, kind):
        """API 한 번 호출. 네트워크 오류는 두 번까지 다시 시도하고, 인증·한도 오류는 바로 멈춘다."""
        for attempt in range(3):
            if self._stop.is_set():
                raise _Stop("서버가 종료되어 적재를 멈췄습니다.")
            time.sleep(self.delay)
            try:
                return self.collector.request(url, params, kind)
            except ApiError as exc:
                if exc.code in STOP_API_CODES:
                    raise _Stop(exc.message) from None
                if exc.code not in RETRY_API_CODES or attempt == 2:
                    raise
                time.sleep(self.retry_wait * (attempt + 1))

    def _save_last(self, summary):
        """마지막 결과를 짧게 app_settings 에 남긴다 (서버를 다시 켜도 확인할 수 있게)."""
        brief = json.dumps({"at": summary["startedAt"], "landOk": summary["land"]["ok"],
                            "landFailed": summary["land"]["failed"],
                            "apt": (summary["applyhome"].get("apt") or {}).get("received"),
                            "aptMdl": (summary["applyhome"].get("apt_mdl") or {}).get("received"),
                            "stopped": bool(summary["stopped"]), "error": bool(summary["error"])},
                           ensure_ascii=False)[:255]
        try:
            with self.sessions.begin() as session:
                session.execute(text("DELETE FROM app_settings WHERE `key` = 'daily_load_last'"))
                session.execute(text("INSERT INTO app_settings (`key`, value) VALUES ('daily_load_last', :v)"), {"v": brief})
        except Exception:  # noqa: BLE001 - 기록 실패가 적재 결과를 바꾸지 않게
            pass


# ---------------------------------------------------------------------------
# 행 변환 (land_trade.py / applyhome.py 의 load 와 같은 규칙)
# ---------------------------------------------------------------------------
LAND_KNOWN = {"sggCd", "umdNm", "jibun", "jimok", "landUse", "dealAmount", "dealArea", "dealYear",
              "dealMonth", "dealDay", "dealingGbn", "shareDealingType", "cdealType", "cdealDay", "estateAgentSggNm"}
NOTICE_CORE = {"HOUSE_MANAGE_NO", "PBLANC_NO", "HOUSE_NM", "HOUSE_SECD", "HOUSE_DTL_SECD", "RENT_SECD",
               "HSSPLY_ADRES", "RCRIT_PBLANC_DE", "BSNS_MBY_NM", "CNSTRCT_ENTRPS_NM", "PBLANC_URL"}
MODEL_CORE = {"HOUSE_MANAGE_NO", "PBLANC_NO", "MODEL_NO", "HOUSE_TY", "SUPLY_AR", "SUPLY_HSHLDCO",
              "SPSPLY_HSHLDCO", "LTTOT_TOP_AMOUNT"}


def land_trade_values(sgg, ym, item) -> dict:
    try:
        date = dt.date(int(item["dealYear"]), int(item["dealMonth"]), int(item["dealDay"])).isoformat()
    except (KeyError, ValueError):
        date = None
    extra = {k: v for k, v in item.items() if k not in LAND_KNOWN}
    return {"lawd_cd": sgg, "deal_ym": ym, "deal_date": date, "umd_nm": item.get("umdNm"), "jibun": item.get("jibun"),
            "jimok": item.get("jimok"), "land_use": item.get("landUse"),
            "deal_amount_manwon": _number(item.get("dealAmount")), "deal_area_m2": _number(item.get("dealArea")),
            "dealing_gbn": item.get("dealingGbn"), "share_dealing_type": item.get("shareDealingType"),
            "cdeal_type": item.get("cdealType"), "cdeal_day": item.get("cdealDay"),
            "agent_sgg_nm": item.get("estateAgentSggNm"),
            "extra": json.dumps(extra, ensure_ascii=False) if extra else None}


def applyhome_notice_values(row) -> dict:
    extra = {k: v for k, v in row.items() if k not in NOTICE_CORE}
    return {"house_manage_no": str(row.get("HOUSE_MANAGE_NO") or ""), "pblanc_no": str(row.get("PBLANC_NO") or ""),
            "house_nm": _cut(row.get("HOUSE_NM"), 200), "house_secd": _cut(row.get("HOUSE_SECD"), 10),
            "house_dtl_secd": _cut(row.get("HOUSE_DTL_SECD"), 10), "rent_secd": _cut(row.get("RENT_SECD"), 10),
            "hssply_adres": _cut(row.get("HSSPLY_ADRES"), 300), "rcrit_pblanc_de": _date(row.get("RCRIT_PBLANC_DE")),
            "bsns_mby_nm": _cut(row.get("BSNS_MBY_NM"), 200), "cnstrct_entrps_nm": _cut(row.get("CNSTRCT_ENTRPS_NM"), 200),
            "pblanc_url": _cut(row.get("PBLANC_URL"), 500),
            "extra": json.dumps(extra, ensure_ascii=False) if extra else None}


def applyhome_model_values(row) -> dict:
    extra = {k: v for k, v in row.items() if k not in MODEL_CORE}
    return {"house_manage_no": str(row.get("HOUSE_MANAGE_NO") or ""), "pblanc_no": str(row.get("PBLANC_NO") or ""),
            "model_no": str(row.get("MODEL_NO") or ""), "house_ty": _cut(row.get("HOUSE_TY"), 30),
            "suply_ar": _float(row.get("SUPLY_AR")), "suply_hshldco": _int(row.get("SUPLY_HSHLDCO")),
            "spsply_hshldco": _int(row.get("SPSPLY_HSHLDCO")), "lttot_top_amount": _int(row.get("LTTOT_TOP_AMOUNT")),
            "extra": json.dumps(extra, ensure_ascii=False) if extra else None}


def recent_months(count, today=None) -> list[str]:
    """지난 달부터 거꾸로 count 개월 (YYYYMM). 이번 달은 아직 신고가 덜 들어와서 받지 않는다."""
    first = (today or dt.datetime.now(KOREA_TIMEZONE).date()).replace(day=1)
    months = []
    for _ in range(count):
        first = (first - dt.timedelta(days=1)).replace(day=1)
        months.append(first.strftime("%Y%m"))
    return months


def _number(value):
    value = (value or "").replace(",", "").strip()
    try:
        return float(value) if "." in value else int(value)
    except ValueError:
        return None


def _float(value):
    try:
        return float(str(value).replace(",", "").strip())
    except (ValueError, TypeError):
        return None


def _int(value):
    try:
        return int(float(str(value).replace(",", "").strip()))
    except (ValueError, TypeError):
        return None


def _date(value):
    try:
        return dt.date.fromisoformat(str(value).strip()[:10]).isoformat()
    except ValueError:
        return None


def _cut(value, size):
    return None if value in (None, "") else str(value)[:size]


def _now() -> str:
    return dt.datetime.now(KOREA_TIMEZONE).isoformat(timespec="seconds")


def _db_now() -> str:
    return dt.datetime.now(KOREA_TIMEZONE).strftime("%Y-%m-%d %H:%M:%S")


def _acquire_db_lock(session) -> bool:
    if session.bind.dialect.name != "mysql":
        return True  # 테스트용 SQLite 등
    return session.execute(text("SELECT GET_LOCK(:name, 0)"), {"name": LOCK_NAME}).scalar() == 1


def _release_db_lock(session):
    if session.bind.dialect.name == "mysql":
        session.execute(text("SELECT RELEASE_LOCK(:name)"), {"name": LOCK_NAME})
