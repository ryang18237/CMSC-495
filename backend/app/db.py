"""Data layer wiring: engine, session factory and the declarative base.

A portable GUID column type is used so the same models run against PostgreSQL
(the production data layer) and against SQLite for fast local unit runs.
"""

import uuid
from collections.abc import Iterator
from typing import Any

from sqlalchemy import CHAR, create_engine
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.types import TypeDecorator

from app.config import get_settings


class GUID(TypeDecorator):
    """UUID column that works on PostgreSQL and on SQLite.

    PostgreSQL has a native UUID type and SQLite does not, so this stores a
    real UUID on PostgreSQL and a 36 character string elsewhere. Callers only
    ever see `uuid.UUID` either way, which is what lets the same models run
    against the production database and against a local file.
    """

    impl = CHAR
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect) -> Any:
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PG_UUID(as_uuid=True))
        return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value: Any, dialect: Dialect) -> Any:
        if value is None:
            return None
        if not isinstance(value, uuid.UUID):
            value = uuid.UUID(str(value))
        if dialect.name == "postgresql":
            return value
        return str(value)

    def process_result_value(self, value: Any, dialect: Dialect) -> Any:
        if value is None:
            return None
        if isinstance(value, uuid.UUID):
            return value
        return uuid.UUID(str(value))


class Base(DeclarativeBase):
    pass


_settings = get_settings()
_connect_args: dict[str, Any] = {}
if _settings.database_url.startswith("sqlite"):
    _connect_args = {"check_same_thread": False}

engine = create_engine(_settings.database_url, pool_pre_ping=True, connect_args=_connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """Yield a session for one request and close it afterwards.

    Committing is left to the route, because a route often coordinates several
    services and either all of that work lands or none of it should.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
