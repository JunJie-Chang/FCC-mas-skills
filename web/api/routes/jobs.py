"""
web/api/routes/jobs.py — Job lifecycle endpoints.

    POST   /jobs                  — create + schedule a new agent run
    GET    /jobs/{id}             — current row snapshot
    GET    /jobs/{id}/events      — SSE stream (replay + live)
    GET    /jobs/{id}/download    — output .docx as binary
    GET    /jobs/{id}/log         — log .log sidecar as text

The download / log endpoints stream from disk paths resolved through
the Job row, never from a caller-supplied path. That keeps the file
namespace closed.
"""

import asyncio
import json
import logging
import mimetypes
from pathlib import Path
from typing import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from web.api.db import get_session
from web.api.models import Job, JobEvent, JobStatus
from web.api.schemas import JobCreateRequest, JobResponse
from web.api.services.job_runner import execute_job
from web.api.services.progress_bus import bus

log = logging.getLogger("routes.jobs")
router = APIRouter(prefix="/jobs", tags=["jobs"])


# ── Defaults ─────────────────────────────────────────────────────────

_AGENT_DEFAULT_SUBDIR = {
    "translation": "daily",
    "podcast":     "weekly",
    "speech_ppt":  "weekly",
}


# ── Routes ───────────────────────────────────────────────────────────

@router.post("", response_model=JobResponse, status_code=201)
async def create_job(
    body: JobCreateRequest,
    db: Session = Depends(get_session),
) -> Job:
    """
    Create a new job and schedule it. Returns the freshly inserted row
    with status=queued. The browser then opens /jobs/{id}/events to
    watch it run.
    """
    subdir = body.subdir or _AGENT_DEFAULT_SUBDIR.get(body.type, "adhoc")

    job = Job(
        type=body.type,
        instruction=body.instruction,
        intern_name=body.intern_name,
        mode=body.mode,
        subdir=subdir,
        extra=body.extra,
        status=JobStatus.QUEUED,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    # Schedule the worker. asyncio.create_task is fire-and-forget — the
    # task lifetime is the agent run's lifetime, separate from this
    # HTTP request.
    asyncio.create_task(execute_job(job.id))
    return job


@router.get("/{job_id}", response_model=JobResponse)
def get_job(job_id: str, db: Session = Depends(get_session)) -> Job:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return job


@router.get("/{job_id}/events")
async def stream_events(
    request: Request,
    job_id: str,
    db: Session = Depends(get_session),
) -> EventSourceResponse:
    """
    Server-Sent Events stream. Sends:
      1. Persisted events with id > Last-Event-ID (replay).
      2. Live events arriving on the in-process bus until job is
         terminal AND the queue drains.
      3. A heartbeat every 15s so corporate proxies don't time out.

    Client must use the browser's native EventSource — it handles
    reconnection automatically (sending Last-Event-ID back).
    """
    if db.get(Job, job_id) is None:
        raise HTTPException(status_code=404, detail="job not found")

    last_event_id_header = request.headers.get("Last-Event-ID")
    try:
        cursor = int(last_event_id_header) if last_event_id_header else 0
    except ValueError:
        cursor = 0

    # Subscribe BEFORE replay so we don't miss anything published in the
    # gap between the replay query and the live stream start.
    queue = await bus.subscribe(job_id)

    async def event_generator() -> AsyncIterator[dict]:
        try:
            # ── Replay persisted events ─────────────────────────────
            with next(get_session()) as replay_db:  # fresh session
                rows = (
                    replay_db.query(JobEvent)
                    .filter(JobEvent.job_id == job_id, JobEvent.id > cursor)
                    .order_by(JobEvent.id.asc())
                    .all()
                )
                for row in rows:
                    yield {
                        "id":    str(row.id),
                        "event": row.kind,
                        "data":  json.dumps(
                            {"kind": row.kind, "ts": row.ts.isoformat(), **(row.payload or {})},
                            ensure_ascii=False,
                            default=str,
                        ),
                    }
                # Track the highest replayed id so we don't double-emit
                # an event that's now also queued by the live publisher.
                replayed_ids = {row.id for row in rows}

            # ── Live stream ─────────────────────────────────────────
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    # Heartbeat to keep the connection warm.
                    yield {"event": "ping", "data": ""}
                    continue

                event_id = event.pop("_event_id", None)
                if event_id is not None and event_id in replayed_ids:
                    # Already sent during replay — skip duplicate.
                    continue

                yield {
                    "id":    str(event_id) if event_id is not None else "",
                    "event": event.get("kind", "message"),
                    "data":  json.dumps(event, ensure_ascii=False, default=str),
                }

                # Close the stream once we see a terminal event.
                if event.get("kind") in ("job_completed", "job_failed"):
                    break
        finally:
            await bus.unsubscribe(job_id, queue)

    return EventSourceResponse(event_generator())


@router.get("/{job_id}/download")
def download_output(job_id: str, db: Session = Depends(get_session)) -> FileResponse:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    if job.status != JobStatus.DONE or not job.output_path:
        raise HTTPException(status_code=409, detail=f"job not downloadable (status={job.status.value})")

    path = Path(job.output_path)
    if not path.exists():
        raise HTTPException(status_code=410, detail="output file no longer on disk")

    media_type, _ = mimetypes.guess_type(str(path))
    if media_type is None:
        media_type = "application/octet-stream"

    return FileResponse(
        path=str(path),
        media_type=media_type,
        filename=path.name,
    )


@router.get("/{job_id}/log", response_class=PlainTextResponse)
def get_log(job_id: str, db: Session = Depends(get_session)) -> str:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    if not job.log_path:
        raise HTTPException(status_code=404, detail="no log for this job")
    path = Path(job.log_path)
    if not path.exists():
        raise HTTPException(status_code=410, detail="log file no longer on disk")
    return path.read_text(encoding="utf-8")
