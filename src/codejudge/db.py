"""Persistence: tasks and submissions (the job queue) via SQLAlchemy.

PostgreSQL in production, SQLite for development and tests. The queue claim
is a conditional UPDATE (``status='queued' -> 'running'``) whose rowcount
tells a worker whether it won the race, which is safe on both backends and
with any number of workers.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Any

from sqlalchemy import JSON, DateTime, String, Text, create_engine, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from codejudge.config import get_settings


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class TaskRow(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    spec: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class SubmissionRow(Base):
    __tablename__ = "submissions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    task_id: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(16), index=True, default="queued")
    source: Mapped[str] = mapped_column(String(16), default="api")
    # Task spec snapshot: later edits to a task never change past results.
    task_spec: Mapped[dict[str, Any]] = mapped_column(JSON)
    request: Mapped[dict[str, Any]] = mapped_column(JSON)
    report: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    github: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    worker_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


@lru_cache(maxsize=4)
def get_engine(url: str | None = None) -> Engine:
    url = url or get_settings().database_url
    kwargs: dict[str, Any] = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    engine = create_engine(url, **kwargs)
    Base.metadata.create_all(engine)
    return engine


@contextmanager
def session_scope(url: str | None = None) -> Iterator[Session]:
    factory = sessionmaker(bind=get_engine(url), expire_on_commit=False)
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def requeue_stale(session: Session, older_than: timedelta = timedelta(minutes=30)) -> int:
    """Return submissions orphaned by a crashed worker to the queue."""
    res = session.execute(
        update(SubmissionRow)
        .where(SubmissionRow.status == "running", SubmissionRow.started_at < utcnow() - older_than)
        .values(status="queued", worker_id=None, started_at=None)
    )
    session.commit()
    return int(getattr(res, "rowcount", 0) or 0)


def claim_next(session: Session, worker_id: str) -> SubmissionRow | None:
    """Atomically move the oldest queued submission to 'running'."""
    for _ in range(5):
        candidate_id = session.scalar(
            select(SubmissionRow.id)
            .where(SubmissionRow.status == "queued")
            .order_by(SubmissionRow.created_at)
            .limit(1)
        )
        if candidate_id is None:
            return None
        res = session.execute(
            update(SubmissionRow)
            .where(SubmissionRow.id == candidate_id, SubmissionRow.status == "queued")
            .values(status="running", worker_id=worker_id, started_at=utcnow())
        )
        session.commit()
        if getattr(res, "rowcount", 0) == 1:
            return session.get(SubmissionRow, candidate_id)
    return None
