"""Database engine and session management.

The engine is created once per application process and stored on
``app.state``.  Nothing connects at import time, which keeps the existing
recommendation-only deployment working when no database is configured.
"""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.db import models  # noqa: F401  (register models on Base.metadata)
from app.db.base import Base

logger = logging.getLogger(__name__)

SessionFactory = sessionmaker[Session]


def _engine_kwargs(database_url: str, settings: Settings) -> dict:
    if database_url.startswith("sqlite"):
        kwargs: dict = {"connect_args": {"check_same_thread": False}}
        if ":memory:" in database_url:
            kwargs["poolclass"] = StaticPool
        return kwargs
    return {
        "pool_pre_ping": True,
        "pool_size": settings.db_pool_size,
        "max_overflow": settings.db_max_overflow,
        "pool_timeout": settings.db_pool_timeout_seconds,
        "pool_recycle": settings.db_pool_recycle_seconds,
        "connect_args": {"connect_timeout": settings.db_connect_timeout_seconds},
    }


def create_db_engine(database_url: str, settings: Settings) -> Engine:
    """Create a sync SQLAlchemy engine with sensible production defaults."""

    engine = create_engine(database_url, **_engine_kwargs(database_url, settings))

    if database_url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _enable_sqlite_foreign_keys(dbapi_connection, connection_record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


def build_session_factory(engine: Engine) -> SessionFactory:
    return sessionmaker(
        bind=engine,
        class_=Session,
        autoflush=False,
        expire_on_commit=False,
    )


def init_database(settings: Settings) -> tuple[Optional[Engine], Optional[SessionFactory]]:
    """Create the engine/session factory when ``DATABASE_URL`` is configured."""

    if not settings.database_url:
        return None, None

    engine = create_db_engine(settings.database_url, settings)

    # Production schema changes go through Alembic.  Auto-create is a local
    # and test convenience only and is rejected in production by Settings.
    if settings.db_auto_create:
        Base.metadata.create_all(engine)
        logger.info("database_schema_created")

    return engine, build_session_factory(engine)


def database_is_ready(engine: Engine) -> bool:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except Exception:
        logger.warning("database_readiness_check_failed", exc_info=True)
        return False


def dispose_database(engine: Optional[Engine]) -> None:
    if engine is not None:
        engine.dispose()
