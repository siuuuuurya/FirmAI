"""SQLAlchemy engine and session management (Pure Python SQLite compatibility)."""
from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import DATA_DIR, settings


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


sync_db_url = settings.database_url.replace("+aiosqlite", "")
if not sync_db_url.startswith("sqlite"):
    sync_db_url = f"sqlite:///{DATA_DIR / 'firmware_ai.db'}"

engine = create_engine(
    sync_db_url,
    echo=False,
    connect_args={"check_same_thread": False} if "sqlite" in sync_db_url else {},
)

SessionLocal = sessionmaker(
    bind=engine,
    class_=Session,
    expire_on_commit=False,
    autoflush=False,
)


def init_db() -> None:
    """Create tables on startup."""
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)


# Auto-initialize database schema
init_db()


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a scoped database session."""
    with SessionLocal() as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    """Context manager for tasks that need their own session."""
    with SessionLocal() as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
