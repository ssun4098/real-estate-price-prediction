from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.core.errors import ApiError
from app.db.models import SnapshotRow


def storage_error() -> ApiError:
    return ApiError("STORAGE_ERROR", "저장소(MySQL)를 읽거나 기록하지 못했습니다. 잠시 후 다시 시도하세요.", 503)


class SnapshotRepository:
    def __init__(self, session_factory):
        self.session_factory = session_factory

    def exists(self, ident: str) -> bool:
        try:
            with self.session_factory() as session:
                return session.get(SnapshotRow, ident) is not None
        except SQLAlchemyError:
            raise storage_error() from None

    def add(self, ident: str, snapshot: dict) -> None:
        """Insert only; an existing id is never overwritten."""
        try:
            with self.session_factory.begin() as session:
                session.add(SnapshotRow(
                    id=ident, name=snapshot.get("name"), scenario=snapshot.get("scenario"),
                    created_at=snapshot.get("createdAt"),
                    body=json.dumps(snapshot, ensure_ascii=False, allow_nan=False)))
        except SQLAlchemyError:
            raise storage_error() from None

    def get(self, ident: str) -> dict | None:
        try:
            with self.session_factory() as session:
                row = session.get(SnapshotRow, ident)
                return json.loads(row.body) if row else None
        except SQLAlchemyError:
            raise storage_error() from None

    def list_meta(self) -> list[dict]:
        """Newest first. Reads only the small columns, never the documents."""
        try:
            with self.session_factory() as session:
                rows = session.execute(
                    select(SnapshotRow.id, SnapshotRow.name, SnapshotRow.scenario, SnapshotRow.created_at)
                    .order_by(SnapshotRow.created_at.desc())).all()
                return [{"id": r.id, "name": r.name, "scenario": r.scenario, "createdAt": r.created_at} for r in rows]
        except SQLAlchemyError:
            raise storage_error() from None
