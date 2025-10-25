"""Database engine and session utilities."""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from src.services.settings import load_settings

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

Base = declarative_base()
"""Declarative base class for ORM models."""


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
