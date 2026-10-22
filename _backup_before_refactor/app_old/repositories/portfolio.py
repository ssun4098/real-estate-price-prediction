from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.db.models import PortfolioSampleRow, SettingRow
from app.repositories.snapshots import storage_error

DEFAULT_KEY = "portfolio_default_id"


class PortfolioRepository:
    def __init__(self, session_factory):
        self.session_factory = session_factory

    def exists(self, ident: str) -> bool:
        try:
            with self.session_factory() as session:
                return session.get(PortfolioSampleRow, ident) is not None
        except SQLAlchemyError:
            raise storage_error() from None

    def add(self, item: dict) -> None:
        try:
            with self.session_factory.begin() as session:
                session.add(PortfolioSampleRow(
                    id=item["id"], captured_at=item["capturedAt"],
                    body=json.dumps(item, ensure_ascii=False, allow_nan=False)))
        except SQLAlchemyError:
            raise storage_error() from None

    def get(self, ident: str) -> dict | None:
        try:
            with self.session_factory() as session:
                row = session.get(PortfolioSampleRow, ident)
                return json.loads(row.body) if row else None
        except SQLAlchemyError:
            raise storage_error() from None

    def list_all(self) -> list[dict]:
        try:
            with self.session_factory() as session:
                return [json.loads(body) for body in session.scalars(select(PortfolioSampleRow.body))]
        except SQLAlchemyError:
            raise storage_error() from None

    def get_default_id(self) -> str | None:
        try:
            with self.session_factory() as session:
                row = session.get(SettingRow, DEFAULT_KEY)
                return row.value if row else None
        except SQLAlchemyError:
            raise storage_error() from None

    def set_default_id(self, ident: str) -> None:
        try:
            with self.session_factory.begin() as session:
                session.merge(SettingRow(key=DEFAULT_KEY, value=ident))
        except SQLAlchemyError:
            raise storage_error() from None
