"""
web/api/models.py — Job + JobEvent ORM models.

A Job is one agent run. A JobEvent is one row in its progress stream
(the same payload that gets pushed over SSE). Persisting events lets a
user reopen a job page mid-run and replay everything they missed.
"""

import enum
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    Enum as SAEnum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from web.api.db import Base


# ── Status enum ──────────────────────────────────────────────────────
# Phase 1 only covers the non-interactive states. Interactive states
# (needs_confirm, needs_subject_review, needs_slide_confirm) come in
# Phase 4 when the corresponding UI surfaces exist.

class JobStatus(str, enum.Enum):
    QUEUED                = "queued"
    RUNNING               = "running"
    # Interactive checkpoint states (Phase 4). The agent has paused
    # mid-run and is waiting for the user to submit a decision via
    # POST /jobs/{id}/confirm. Status returns to RUNNING once resolved.
    NEEDS_CONFIRM         = "needs_confirm"           # planner.confirm
    NEEDS_SUBJECT_REVIEW  = "needs_subject_review"    # subject_review
    NEEDS_SLIDE_CONFIRM   = "needs_slide_confirm"     # speech_ppt.confirm_slides
    DONE                  = "done"
    FAILED                = "failed"
    CANCELLED             = "cancelled"


# ── Helpers ──────────────────────────────────────────────────────────

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return uuid.uuid4().hex


# ── Models ───────────────────────────────────────────────────────────

class Job(Base):
    """
    One agent run. The lifecycle:
        queued → running → (done | failed | cancelled)

    Output / log paths are filesystem locations under the same `output/`
    tree the CLI uses; the download endpoint resolves them through this
    row so the browser can only see paths it owns.
    """
    __tablename__ = "jobs"

    id:           Mapped[str] = mapped_column(String(32), primary_key=True, default=_new_id)
    # Multi-user is Phase 7; for now treat user_id as a soft label that
    # eventually maps to OAuth identity.
    user_id:      Mapped[str] = mapped_column(String(128), default="local")

    # Agent type — same vocab as router.dispatch:
    # company_info | person_info | translation | letter | meeting
    # | verbal_cleanup | podcast | speech_ppt
    type:         Mapped[str] = mapped_column(String(32))

    instruction:  Mapped[str] = mapped_column(Text)
    intern_name:  Mapped[str] = mapped_column(String(128))
    mode:         Mapped[str] = mapped_column(String(16), default="short")  # short | medium
    subdir:       Mapped[str] = mapped_column(String(16), default="adhoc")

    status:       Mapped[JobStatus] = mapped_column(
        SAEnum(JobStatus, native_enum=False, length=24),
        default=JobStatus.QUEUED,
    )

    output_path:  Mapped[str | None] = mapped_column(String(512), nullable=True)
    log_path:     Mapped[str | None] = mapped_column(String(512), nullable=True)
    cost_usd:     Mapped[float] = mapped_column(Float, default=0.0)
    error:        Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at:   Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    started_at:   Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Free-form per-type extras (audio path for STT runs, ticker overrides,
    # podcast questions, etc.). Pydantic schemas validate the shape per type.
    extra:        Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    events: Mapped[list["JobEvent"]] = relationship(
        back_populates="job",
        cascade="all, delete-orphan",
        order_by="JobEvent.id",
    )


class JobEvent(Base):
    """
    One progress event for a job. Mirrors the dict shape from
    `utils.progress.emit()`:

        {"kind": "node_start", "ts": "...", "node": "parse_task", ...}

    Persisted so SSE replay works for late connections / refreshes.
    """
    __tablename__ = "job_events"

    id:      Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id:  Mapped[str] = mapped_column(String(32), ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    kind:    Mapped[str] = mapped_column(String(32))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    ts:      Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    job: Mapped[Job] = relationship(back_populates="events")
