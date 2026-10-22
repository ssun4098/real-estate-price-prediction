"""MySQL table definitions. Documents are stored as text to keep key order and exact numbers."""
from __future__ import annotations

from sqlalchemy import Integer, String, Text
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


# 4GB on MySQL (analysis documents can reach 64MB); plain TEXT elsewhere, e.g. SQLite in tests.
LongText = Text().with_variant(LONGTEXT(), "mysql")


class Base(DeclarativeBase):
    pass


class SnapshotRow(Base):
    """Working analyses saved from the dashboard (/api/save, /api/export-json)."""
    __tablename__ = "analysis_snapshots"

    id: Mapped[str] = mapped_column(String(110), primary_key=True)
    name: Mapped[str | None] = mapped_column(String(255))
    scenario: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[str | None] = mapped_column(String(40), index=True)
    body: Mapped[str] = mapped_column(LongText)


class PortfolioSampleRow(Base):
    """Explicitly captured, read-only sample shelf entries."""
    __tablename__ = "portfolio_samples"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    captured_at: Mapped[str] = mapped_column(String(40), index=True)
    body: Mapped[str] = mapped_column(LongText)


class SettingRow(Base):
    """Tiny key/value table (e.g. which portfolio sample is the default)."""
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(255))


class LandCompleteRow(Base):
    __tablename__ = "land_complete"

    sgg: Mapped[str] = mapped_column(String(5), primary_key=True)
    month: Mapped[str] = mapped_column(String(6), primary_key=True)
    format: Mapped[str] = mapped_column(String(32))
    fetched_at: Mapped[str] = mapped_column(String(40))
    total: Mapped[int] = mapped_column(Integer)
    rows_json: Mapped[str] = mapped_column(LongText)


class LandPageRow(Base):
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
    __tablename__ = "land_errors"

    sgg: Mapped[str] = mapped_column(String(5), primary_key=True)
    month: Mapped[str] = mapped_column(String(6), primary_key=True)
    code: Mapped[str] = mapped_column(String(64))
    failed_at: Mapped[str] = mapped_column(String(40))
