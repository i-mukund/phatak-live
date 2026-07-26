"""Declarative base and shared column types."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, MetaData, TypeDecorator
from sqlalchemy.orm import DeclarativeBase

from app.core.clock import UTC, ensure_aware

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class UtcDateTime(TypeDecorator):
    """Always store UTC, always return tz-aware.

    SQLite silently drops tzinfo; this decorator makes SQLite and PostgreSQL
    behave identically, which removes a whole class of "works on my laptop" bugs.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: object) -> datetime | None:
        return None if value is None else ensure_aware(value).astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: object) -> datetime | None:
        return None if value is None else ensure_aware(value).astimezone(UTC)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
