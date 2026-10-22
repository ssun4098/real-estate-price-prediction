"""MySQL: 테이블 정의 · 연결 · 기존 테이블 보호.

이 앱은 PC에 이미 떠 있는 MySQL 컨테이너를 그대로 씁니다. 그래서 시작할 때
  - 없는 테이블만 새로 만들고 (CREATE TABLE IF NOT EXISTS 와 같음)
  - 이미 있는 테이블은 절대 지우거나 바꾸지 않으며
  - 이름은 같은데 구조가 다른 테이블이 있으면 그 자료를 보호하려고 시작을 멈춥니다.

문서(분석 결과 등)는 JSON 문자열로 LONGTEXT 열에 통째로 저장합니다 (키 순서·숫자 그대로 보존).
"""
from __future__ import annotations

import logging
import time
from contextlib import contextmanager

from sqlalchemy import Integer, String, Text, create_engine, inspect, text
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from server.domain.public_api import ApiError

log = logging.getLogger("uvicorn.error")

# MySQL에서는 LONGTEXT(최대 4GB, 분석 문서는 64MB까지), 테스트용 SQLite에서는 TEXT.
LongText = Text().with_variant(LONGTEXT(), "mysql")


# ---------------------------------------------------------------------------
# 테이블 (이름·열을 바꾸면 기존에 저장된 자료와 맞지 않게 되니 주의)
# ---------------------------------------------------------------------------
class Base(DeclarativeBase):
    pass


class SnapshotRow(Base):
    """대시보드에서 '저장'한 분석 (/api/save, /api/export-json)."""
    __tablename__ = "analysis_snapshots"
    id: Mapped[str] = mapped_column(String(110), primary_key=True)
    name: Mapped[str | None] = mapped_column(String(255))
    scenario: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[str | None] = mapped_column(String(40), index=True)
    body: Mapped[str] = mapped_column(LongText)


class PortfolioSampleRow(Base):
    """샘플 선반: 한 번 저장하면 바뀌지 않는 분석."""
    __tablename__ = "portfolio_samples"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    captured_at: Mapped[str] = mapped_column(String(40), index=True)
    body: Mapped[str] = mapped_column(LongText)


class SettingRow(Base):
    """작은 키/값 설정 (예: 화면을 열 때 보여줄 기본 샘플)."""
    __tablename__ = "app_settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(255))


class LandCompleteRow(Base):
    """토지 실거래 캐시: 시군구·월 단위로 다 받은 자료."""
    __tablename__ = "land_complete"
    sgg: Mapped[str] = mapped_column(String(5), primary_key=True)
    month: Mapped[str] = mapped_column(String(6), primary_key=True)
    format: Mapped[str] = mapped_column(String(32))
    fetched_at: Mapped[str] = mapped_column(String(40))
    total: Mapped[int] = mapped_column(Integer)
    rows_json: Mapped[str] = mapped_column(LongText)


class LandPageRow(Base):
    """토지 실거래 캐시: 받는 중인 페이지 (다 받으면 land_complete 로 합쳐지고 지워짐)."""
    __tablename__ = "land_pages"
    sgg: Mapped[str] = mapped_column(String(5), primary_key=True)
    month: Mapped[str] = mapped_column(String(6), primary_key=True)
    page: Mapped[int] = mapped_column(Integer, primary_key=True)
    format: Mapped[str] = mapped_column(String(32))
    started_at: Mapped[str] = mapped_column(String(40))
    total: Mapped[int] = mapped_column(Integer)
    page_size: Mapped[int] = mapped_column(Integer)
    rows_json: Mapped[str] = mapped_column(LongText)


class LandErrorRow(Base):
    """토지 실거래 캐시: 마지막 조회 실패 기록."""
    __tablename__ = "land_errors"
    sgg: Mapped[str] = mapped_column(String(5), primary_key=True)
    month: Mapped[str] = mapped_column(String(6), primary_key=True)
    code: Mapped[str] = mapped_column(String(64))
    failed_at: Mapped[str] = mapped_column(String(40))


# ---------------------------------------------------------------------------
# 연결
# ---------------------------------------------------------------------------
# MySQL 오류 번호 중 기다려도 해결되지 않는 것: 바로 원인을 알려 준다.
_FATAL = {
    1045: "MySQL 계정 또는 비밀번호가 틀렸습니다. .env의 MYSQL_USER / MYSQL_PASSWORD를 확인하세요.",
    1049: "MySQL에 MYSQL_DATABASE로 지정한 데이터베이스가 없습니다. 먼저 만들어 주세요 (README 8장).",
}


def connect(url: str, retries: int) -> sessionmaker[Session]:
    """MySQL에 연결하고, 앱 테이블을 준비한 뒤, 세션 공장을 돌려준다."""
    # 접속이 안 될 때 한 번에 오래 매달리지 않도록 5초 제한 (MySQL일 때만)
    connect_args = {"connect_timeout": 5} if url.startswith("mysql") else {}
    engine = create_engine(url, pool_pre_ping=True, pool_recycle=1800, pool_size=10, max_overflow=10,
                           connect_args=connect_args)
    _wait_until_ready(engine, retries)
    _prepare_tables(engine)
    return sessionmaker(engine, expire_on_commit=False)


def close(sessions: sessionmaker[Session]) -> None:
    sessions.kw["bind"].dispose()


def ping(sessions: sessionmaker[Session]) -> None:
    with sessions() as session:
        session.execute(text("SELECT 1"))


def _wait_until_ready(engine: Engine, retries: int, delay: float = 2.0) -> None:
    """MySQL 컨테이너가 막 켜지는 중일 수 있어서 몇 번 다시 시도한다."""
    for attempt in range(1, max(1, retries) + 1):
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            return
        except SQLAlchemyError as exc:
            args = getattr(getattr(exc, "orig", None), "args", ())
            number = args[0] if args else None
            if number in _FATAL:
                raise RuntimeError(_FATAL[number]) from None
            log.warning("MySQL 연결 대기 중 (%d/%d) — 주소 %s:%s, 오류 번호 %s",
                        attempt, retries, engine.url.host, engine.url.port, number)
            if attempt >= retries:
                # 드라이버 메시지에 접속 문자열이 섞일 수 있어 그대로 내보내지 않는다.
                raise RuntimeError("MySQL에 연결할 수 없습니다. MySQL 컨테이너가 켜져 있는지, "
                                   ".env의 MYSQL_HOST / MYSQL_PORT가 맞는지 확인하세요.") from None
            time.sleep(delay)


def _prepare_tables(engine: Engine) -> None:
    inspector = inspect(engine)
    existing = set(inspector.get_table_names())

    # 이름이 같은 기존 테이블이 이 앱이 기대하는 열을 다 갖고 있는지 먼저 확인한다.
    for table in Base.metadata.sorted_tables:
        if table.name not in existing:
            continue
        have = {column["name"] for column in inspector.get_columns(table.name)}
        missing = [column.name for column in table.columns if column.name not in have]
        if missing:
            raise RuntimeError(
                f"기존 테이블 `{table.name}`의 구조가 이 앱과 다릅니다 (없는 열: {', '.join(missing)}). "
                "기존 자료를 보호하려고 시작을 멈췄습니다. .env의 MYSQL_DATABASE를 다른 데이터베이스로 지정하세요.")

    # 없는 테이블만 만든다. 있는 테이블과 그 안의 자료는 건드리지 않는다.
    Base.metadata.create_all(engine, checkfirst=True)

    created = [t.name for t in Base.metadata.sorted_tables if t.name not in existing]
    kept = [t.name for t in Base.metadata.sorted_tables if t.name in existing]
    log.info("MySQL 테이블 준비 완료 — 새로 만듦: %s / 기존 유지: %s",
             ", ".join(created) or "없음", ", ".join(kept) or "없음")


@contextmanager
def db_errors(message: str = "저장소(MySQL)를 읽거나 기록하지 못했습니다. 잠시 후 다시 시도하세요."):
    """DB 오류를 503 표준 오류로 바꾼다. 드라이버 메시지(접속 정보가 섞일 수 있음)는 버린다."""
    try:
        yield
    except SQLAlchemyError:
        raise ApiError("STORAGE_ERROR", message, 503) from None
