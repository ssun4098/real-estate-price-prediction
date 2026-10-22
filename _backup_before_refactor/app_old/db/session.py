"""Engine and session factory. The only place a database connection is opened."""
from __future__ import annotations

import time

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import Base


def create_db_engine(url: str) -> Engine:
    return create_engine(url, pool_pre_ping=True, pool_recycle=1800, pool_size=10, max_overflow=10)


def ping_database(engine: Engine) -> None:
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))


def wait_for_database(engine: Engine, retries: int, delay: float = 2.0) -> None:
    """MySQL can still be initialising when the API container starts."""
    for attempt in range(1, max(1, retries) + 1):
        try:
            ping_database(engine)
            return
        except SQLAlchemyError:
            if attempt == retries:
                # The driver message can echo the connection string; report neither.
                raise RuntimeError("MySQL에 연결할 수 없습니다. 호스트·계정·비밀번호 설정을 확인하세요.") from None
            time.sleep(delay)


def init_schema(engine: Engine) -> None:
    Base.metadata.create_all(engine)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)
