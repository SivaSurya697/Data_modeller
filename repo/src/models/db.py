"""Database engine and session utilities."""
from __future__ import annotations

import os
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from src.models.tables import Base

_settings = load_settings()

engine = create_engine(_settings.database_url, future=True)
"""SQLAlchemy engine bound to the configured database."""

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
)
"""Factory for creating database sessions."""

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
def get_db() -> Iterator[Session]:
    """Yield a database session ensuring transactional safety."""

    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def create_all() -> None:
    """Create database tables defined on the declarative base."""

    # Import within the function to ensure all models are registered without
    # creating circular import issues during module initialisation.
    from src.models import tables  # noqa: WPS433 - imported for side effects only

    Base.metadata.create_all(bind=engine)
