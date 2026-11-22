"""Database URL helpers shared by the application and Alembic."""

from __future__ import annotations

from typing import Optional


def normalize_database_url(value: Optional[str]) -> Optional[str]:
    """Return a SQLAlchemy 2 compatible URL.

    Managed Postgres providers still hand out ``postgres://`` or
    ``postgresql://`` URLs.  SQLAlchemy 2 needs an explicit driver, otherwise
    it tries to import ``psycopg2``.  The project uses psycopg 3.
    """

    if value is None:
        return None
    url = value.strip()
    if not url:
        return None
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://") :]
    return url
