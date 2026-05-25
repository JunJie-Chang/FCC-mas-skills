"""
web/api/db.py — SQLAlchemy 2.0 engine + session factory.

SQLite for Phase 1 — one file, durable, sufficient for the team's
working volume. Swap-in Postgres later by changing settings.db_url
and dropping the `check_same_thread` connect arg.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from web.api.config import settings


class Base(DeclarativeBase):
    """ORM base — all models inherit from here so create_all() finds them."""
    pass


# `check_same_thread=False` is required for SQLite because the job runner
# touches the DB from a worker thread that is different from the request
# thread. Safety here comes from session-per-request scoping below, not
# from SQLite's per-connection thread guard.
_connect_args = {"check_same_thread": False} if settings.db_url.startswith("sqlite") else {}

engine = create_engine(
    settings.db_url,
    connect_args=_connect_args,
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def init_db() -> None:
    """
    Create tables if missing. Called from FastAPI lifespan startup.

    For Phase 1 this is the migration story — we have one schema and we
    own when it changes. Alembic comes in when we add columns to a live
    deployment.
    """
    # Import models so they register on Base.metadata before create_all.
    from web.api import models  # noqa: F401
    Base.metadata.create_all(bind=engine)


def get_session():
    """
    FastAPI dependency — one Session per request, closed on exit.

    Used as `db: Session = Depends(get_session)` in route handlers.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
