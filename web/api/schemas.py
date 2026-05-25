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


# Phase 1 only ships company_info. Other agent types listed for OpenAPI
# completeness — the router will reject them with a 400 until enabled
# in Phase 3.
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


class JobCreateRequest(BaseModel):
    """
    Submit a new job. Free-text instruction + agent type + a few knobs.
    Optional `extra` carries type-specific data (e.g. translation needs
    title / source / body_text; podcast needs explicit questions).
    """
    model_config = ConfigDict(extra="forbid")

    type:         AgentType
    instruction:  str = Field(min_length=1, max_length=20_000)
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
    type:         AgentType
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
