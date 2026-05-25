"""
web/api/schemas.py — Pydantic v2 request / response models.

These define the HTTP boundary contract. The frontend's TypeScript types
are generated from this app's OpenAPI schema (via `openapi-typescript`),
so changes here are picked up by the client without manual sync.
"""

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from web.api.models import JobStatus


# Concrete agent types — one of these is what router.dispatch eventually
# fans out to.
AgentType = Literal[
    "company_info",
    "person_info",
    "translation",
    "letter",
    "meeting",
    "verbal_cleanup",
    "podcast",
    "speech_ppt",
]

# A Job's `type` is either a concrete agent (single-task path) OR the
# `stt_pipeline` sentinel (multi-step: STT → subject_review → planner
# → router.dispatch fan-out into N sub-tasks). The web job_runner
# picks the execution path based on this.
JobType = Literal[
    "company_info",
    "person_info",
    "translation",
    "letter",
    "meeting",
    "verbal_cleanup",
    "podcast",
    "speech_ppt",
    "stt_pipeline",
]


class JobCreateRequest(BaseModel):
    """
    Submit a new job. Free-text instruction + agent type + a few knobs.

    For single-agent jobs: pass instruction as the free-text task.
    For stt_pipeline jobs: pass extra={"upload_id": "<id>"} and use
    instruction="" (or a label) — the actual instructions come from
    parse_tasks after STT transcribes the audio.
    """
    model_config = ConfigDict(extra="forbid")

    type:         JobType
    instruction:  str = Field(default="", max_length=20_000)
    intern_name:  str = Field(default="Justin", max_length=128)
    mode:         Literal["short", "medium"] = "short"
    subdir:       Optional[Literal["daily", "weekly", "adhoc"]] = None
    extra:        dict[str, Any] = Field(default_factory=dict)


class JobResponse(BaseModel):
    """
    Snapshot of a job's row state. The events list is fetched
    separately via /jobs/{id}/events (SSE) — including it here would
    bloat polling responses.
    """
    model_config = ConfigDict(from_attributes=True)

    id:           str
    user_id:      str
    type:         JobType
    instruction:  str
    intern_name:  str
    mode:         str
    subdir:       str
    status:       JobStatus
    output_path:  Optional[str] = None
    log_path:     Optional[str] = None
    cost_usd:     float = 0.0
    error:        Optional[str] = None
    created_at:   datetime
    started_at:   Optional[datetime] = None
    completed_at: Optional[datetime] = None
    extra:        dict[str, Any] = Field(default_factory=dict)


class JobSubTaskResponse(BaseModel):
    """One child of an stt_pipeline parent. Frontend renders these as
    nested cards under the parent job's detail page."""
    model_config = ConfigDict(from_attributes=True)

    id:           str
    parent_id:    str
    idx:          int
    agent_type:   AgentType
    label:        str
    instruction:  str
    status:       JobStatus
    output_path:  Optional[str] = None
    log_path:     Optional[str] = None
    cost_usd:     float = 0.0
    error:        Optional[str] = None
    started_at:   Optional[datetime] = None
    completed_at: Optional[datetime] = None


class JobEventResponse(BaseModel):
    """
    Persisted event row. The SSE stream uses the same shape (id is the
    `last-event-id` cursor a reconnecting client passes back).
    """
    model_config = ConfigDict(from_attributes=True)

    id:      int
    job_id:  str
    kind:    str
    payload: dict[str, Any]
    ts:      datetime


class UploadResponse(BaseModel):
    """Returned by POST /uploads/audio. Frontend stashes upload_id and
    references it in the stt_pipeline job's extra payload."""
    model_config = ConfigDict(from_attributes=True)

    id:         str
    filename:   str
    size_bytes: int
    mime:       str
    created_at: datetime
