"""Database engine and session helpers.

This module centralises creation of the SQLAlchemy engine and exposes a
handful of helper functions used across the application.  The previous
revision of the repository contained a partially duplicated implementation
that left several symbols undefined which in turn caused import-time
failures.  The helpers below present a cohesive, well documented API that is
shared by the blueprints and services.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

# The declarative base is defined here so that the metadata is available before
# the model modules import it.  Individual model classes subclass ``Base``.
Base = declarative_base()

# Module level caches populated by ``init_engine``.  They are initialised on
# demand which keeps import time side effects to a minimum while still allowing
# imperative configuration during application start-up.
_ENGINE: Engine | None = None
_SESSION_FACTORY: sessionmaker[Session] | None = None


def init_engine(database_url: str | None = None) -> Engine:
    """Initialise the SQLAlchemy engine and session factory.

    Parameters
    ----------
    database_url:
        Optional SQLAlchemy connection string.  When omitted the value is read
        from the ``DATABASE_URL`` environment variable falling back to a local
        SQLite database.  The created engine is cached for subsequent calls.
    """

    url = database_url or os.getenv("DATABASE_URL", "sqlite:///data_modeller.db")
    engine = create_engine(url, future=True)

    global _ENGINE, _SESSION_FACTORY  # noqa: PLW0603 - module level cache
    _ENGINE = engine
    _SESSION_FACTORY = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )
    return engine


def get_engine() -> Engine:
    """Return the configured SQLAlchemy engine, initialising it if required."""

    global _ENGINE  # noqa: PLW0603 - accessed for lazy initialisation
    if _ENGINE is None:
        return init_engine()
    return _ENGINE


def _get_session_factory() -> sessionmaker[Session]:
    """Return the lazily initialised session factory."""

    global _SESSION_FACTORY  # noqa: PLW0603 - accessed for lazy initialisation
    if _SESSION_FACTORY is None:
        init_engine()
    assert _SESSION_FACTORY is not None  # for type-checkers
    return _SESSION_FACTORY


@contextmanager
def get_db() -> Iterator[Session]:
    """Yield a database session with commit/rollback semantics.

    The helper mirrors Flask-SQLAlchemy's behaviour where a session is bound to
    the context manager and automatically committed or rolled back depending on
    whether an exception was raised.
    """

    session = _get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Alias for :func:`get_db` for backwards compatibility."""

    with get_db() as session:
        yield session


def create_all() -> None:
    """Create database tables for all declared models."""

    # Importing inside the function avoids circular imports and ensures that
    # every model has been registered with the declarative base before calling
    # ``metadata.create_all``.
    from src.models import tables  # noqa: F401  # imported for side effects

    Base.metadata.create_all(bind=get_engine())


__all__ = [
    "Base",
    "create_all",
    "get_db",
    "get_engine",
    "init_engine",
    "session_scope",
]

