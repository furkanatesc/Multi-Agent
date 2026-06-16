"""Database connectivity: SQLAlchemy engine/session + LangGraph checkpointers.

Two distinct connection consumers exist and they expect *different* URL forms:

* **SQLAlchemy 2.0** (ORM models, Alembic) wants an explicit driver:
  ``postgresql+psycopg://...`` (psycopg v3).
* **PostgresSaver / psycopg_pool** want a plain DBAPI URI: ``postgresql://...``.

:func:`to_sqlalchemy_url` and :func:`to_psycopg_url` normalize ``settings.DATABASE_URL``
into each form. Nothing connects at import time; engines/pools are built lazily so
unit tests that never touch Postgres stay fast and offline.
"""

from __future__ import annotations

from contextlib import contextmanager
from functools import lru_cache
from typing import Any, Iterator, Optional

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from src.core.config import settings
from src.core.logging import logger

# --------------------------------------------------------------------------- #
# URL normalization
# --------------------------------------------------------------------------- #


def to_sqlalchemy_url(url: str) -> str:
    """Return ``url`` with an explicit psycopg v3 driver for SQLAlchemy.

    ``postgresql://...`` -> ``postgresql+psycopg://...``. URLs that already carry
    a ``postgresql+<driver>`` prefix (or a non-postgres scheme) are returned as-is.
    """
    if url.startswith("postgresql+"):
        return url
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://") :]
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://") :]
    return url


def to_psycopg_url(url: str) -> str:
    """Return a plain DBAPI URI suitable for psycopg / PostgresSaver.

    Strips any ``+psycopg`` driver hint that SQLAlchemy needs but psycopg rejects.
    """
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


# --------------------------------------------------------------------------- #
# SQLAlchemy engine / session (ORM)
# --------------------------------------------------------------------------- #


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """Build (once) and return the SQLAlchemy engine for the ORM models."""
    url = to_sqlalchemy_url(settings.DATABASE_URL)
    logger.info("Creating SQLAlchemy engine", url=url.split("@")[-1])
    return create_engine(url, pool_pre_ping=True, future=True)


@lru_cache(maxsize=1)
def get_sessionmaker() -> "sessionmaker[Session]":
    """Build (once) and return a configured session factory."""
    return sessionmaker(bind=get_engine(), expire_on_commit=False, class_=Session)


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional session scope: commit on success, rollback on error.

    Usage::

        with session_scope() as db:
            db.add(Project(prompt="..."))
    """
    session = get_sessionmaker()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# --------------------------------------------------------------------------- #
# LangGraph checkpointers
# --------------------------------------------------------------------------- #


def get_memory_checkpointer() -> Any:
    """Return an in-memory checkpointer (development / tests only)."""
    from langgraph.checkpoint.memory import InMemorySaver

    return InMemorySaver()


# Module-level pool so a single connection pool is shared process-wide.
_pg_pool: Optional[Any] = None


def get_postgres_checkpointer(setup: bool = True) -> Any:
    """Return a production :class:`PostgresSaver` backed by a shared pool.

    The connection pool is opened once and reused. ``autocommit=True`` and
    ``prepare_threshold=0`` are required by ``PostgresSaver``.

    Args:
        setup: When True, run ``checkpointer.setup()`` to create/upgrade the
            ``langgraph.*`` checkpoint tables (idempotent).
    """
    from langgraph.checkpoint.postgres import PostgresSaver
    from psycopg_pool import ConnectionPool

    global _pg_pool
    if _pg_pool is None:
        conninfo = to_psycopg_url(settings.DATABASE_URL)
        logger.info("Opening PostgreSQL connection pool", url=conninfo.split("@")[-1])
        _pg_pool = ConnectionPool(
            conninfo=conninfo,
            max_size=20,
            open=False,
            kwargs={"autocommit": True, "prepare_threshold": 0},
        )
        _pg_pool.open()

    checkpointer = PostgresSaver(_pg_pool)
    if setup:
        checkpointer.setup()
    return checkpointer
