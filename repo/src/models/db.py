"""Database session management utilities."""
from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, scoped_session, sessionmaker

from src.models.tables import Base

_ENGINE: Engine | None = None
_SESSION_FACTORY: scoped_session[Session] | None = None


def init_engine(database_url: str | None = None) -> Engine:
    """Initialise the SQLAlchemy engine and session factory."""

    url = database_url or os.getenv("DATABASE_URL", "sqlite:///data_modeller.db")
    engine = create_engine(url, future=True)
    session_factory = scoped_session(
        sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    )

    global _ENGINE  # noqa: PLW0603 - module level cache is intentional
    global _SESSION_FACTORY  # noqa: PLW0603
    _ENGINE = engine
    _SESSION_FACTORY = session_factory
    return engine


def get_engine() -> Engine:
    """Return the active SQLAlchemy engine."""

    if _ENGINE is None:
        return init_engine()
    return _ENGINE


def create_all() -> None:
    """Create database tables based on the metadata."""

    engine = get_engine()
    Base.metadata.create_all(bind=engine)


@contextmanager
def session_scope() -> Iterator[Session]:
    """Provide a transactional scope for database work."""

    if _SESSION_FACTORY is None:
        init_engine()
    assert _SESSION_FACTORY is not None  # For type-checkers
    session = _SESSION_FACTORY()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
