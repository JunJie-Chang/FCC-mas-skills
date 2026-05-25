"""
web/api/services/job_runner.py — Bridge from HTTP job rows to agent runs.

What this does on a queued Job:
  1. Mark status=RUNNING, started_at=now.
  2. Construct a per-job CostTracker bound for the agent's worker thread
     so the CLI's global tracker stays untouched.
  3. Construct a progress_cb that pushes events through the in-process
     bus (which persists them and fans out to SSE subscribers).
  4. Invoke the agent in a thread pool via asyncio.to_thread (agents
     are sync and use blocking SDKs — keeping them off the event loop
     is required, not optional).
  5. On return / exception, write final status, cost_usd, output_path,
     log_path, error message.

Phase 1 supports `company_info` only. Other agent_types raise a
clear NotImplementedError; the routes layer surfaces that as HTTP 501.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from utils.confirm import use_strategy
from utils.cost_tracker import CostTracker, use_tracker
from web.api.db import SessionLocal
from web.api.models import Job, JobStatus
from web.api.services.confirm_strategy import WebConfirmStrategy
from web.api.services.progress_bus import bus

log = logging.getLogger("job_runner")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ── Agent dispatch ───────────────────────────────────────────────────

def _dispatch_blocking(
    agent_type: str,
    instruction: str,
    intern_name: str,
    task_date: str,
    subdir: str,
    mode: str,
    extra: dict[str, Any],
    progress_cb,
) -> dict[str, Any]:
    """
    Run the agent. Synchronous on purpose — called via asyncio.to_thread.

    The agent's own per-job state (cost tracker, confirm strategy) is
    bound for the duration of this call via contextvars / threading.local
    set up by the caller.

    Currently enabled types:
        company_info  (Phase 1)
        speech_ppt    (Phase 4 — exercises the confirm_slides checkpoint)
    Other types reach Phase 3 / 5.
    """
    if agent_type == "company_info":
        from agents.company_info_agent import run as agent_run
        return agent_run(
            task_instruction=instruction,
            intern_name=intern_name,
            task_date=task_date,
            subdir=subdir,
            mode=mode,
            progress_cb=progress_cb,
        )

    if agent_type == "speech_ppt":
        from agents.speech_ppt_agent import run as agent_run
        return agent_run(
            task_instruction=instruction,
            intern_name=intern_name,
            task_date=task_date,
            subdir=subdir,
            generate_images=bool(extra.get("generate_images", True)),
            mode=mode,
            progress_cb=progress_cb,
        )

    # Other types reach Phase 3 / 5. Raising lets the runner surface a
    # clean error status to the user instead of silently hanging.
    raise NotImplementedError(
        f"agent_type {agent_type!r} not enabled yet"
    )


# ── Job execution ────────────────────────────────────────────────────

async def execute_job(job_id: str) -> None:
    """
    Entry point scheduled via asyncio.create_task from the POST /jobs
    handler. Owns the full lifecycle for one job.
    """
    # Step 1: claim — mark RUNNING.
    with SessionLocal() as db:  # type: Session
        job = db.get(Job, job_id)
        if job is None:
            log.error("execute_job: no Job row for %s", job_id)
            return
        if job.status != JobStatus.QUEUED:
            log.warning("execute_job: %s already in status %s, skipping", job_id, job.status)
            return
        job.status = JobStatus.RUNNING
        job.started_at = _utcnow()
        db.commit()

    bus.publish_from_thread(job_id, {"kind": "job_started", "ts": _utcnow().isoformat()})

    # Step 2: run. Per-job tracker isolates cost; progress_cb publishes
    # via the bus. asyncio.to_thread releases the event loop while the
    # blocking agent (HTTP requests, sleeps, JSON parsing) runs.
    tracker = CostTracker()

    def progress_cb(event: dict[str, Any]) -> None:
        # Called from the worker thread — bus handles the loop hop.
        bus.publish_from_thread(job_id, event)

    # Capture the fields we need now (on the event loop, with an open
    # session) so the worker thread doesn't have to re-query the DB and
    # so an ORM detach is unnecessary.
    with SessionLocal() as db:  # type: Session
        job = db.get(Job, job_id)
        if job is None:
            return
        agent_kwargs = dict(
            agent_type=job.type,
            instruction=job.instruction,
            intern_name=job.intern_name,
            task_date=job.created_at.strftime("%Y-%m-%d"),
            subdir=job.subdir or "adhoc",
            mode=job.mode,
            extra=dict(job.extra or {}),
        )

    confirm_strategy = WebConfirmStrategy(job_id=job_id)

    def _run_with_tracker() -> dict[str, Any]:
        # Thread-local bind for cost_tracker AND confirm strategy survive
        # within this thread for the lifetime of the with-block, so
        # agent code's tracker.record_* + planner.confirm() / etc. go
        # to the per-job instances.
        with use_tracker(tracker), use_strategy(confirm_strategy):
            return _dispatch_blocking(progress_cb=progress_cb, **agent_kwargs)

    error_msg: str | None = None
    result: dict[str, Any] = {}
    try:
        result = await asyncio.to_thread(_run_with_tracker)
    except NotImplementedError as exc:
        error_msg = str(exc)
        log.warning("job %s rejected: %s", job_id, error_msg)
    except Exception as exc:
        error_msg = f"{type(exc).__name__}: {exc}"
        log.exception("job %s failed", job_id)

    # Step 3: persist final state. Three cases:
    #   - error_msg set → FAILED
    #   - no output_path → CANCELLED (agent returned cleanly without a
    #     deliverable, which means it took the early-exit edge after a
    #     user-cancelled checkpoint; e.g. speech_ppt confirm_slides=False)
    #   - otherwise → DONE
    # Respect a /cancel route's pre-set CANCELLED status either way.
    cost_usd = tracker.total_usd()
    if error_msg:
        final_status = JobStatus.FAILED
    elif not result.get("output_path"):
        final_status = JobStatus.CANCELLED
    else:
        final_status = JobStatus.DONE

    with SessionLocal() as db:
        job = db.get(Job, job_id)
        if job is None:
            return
        if job.status == JobStatus.CANCELLED:
            # User cancelled — keep terminal state, just record cost
            # and (if the agent did produce output before cancel) the
            # paths. Don't overwrite the cancel.
            job.cost_usd = cost_usd
            if result.get("output_path"):
                job.output_path = result["output_path"]
                job.log_path = result.get("log_path")
            job.completed_at = _utcnow()
            db.commit()
            bus.publish_from_thread(job_id, {
                "kind": "job_cancelled",
                "ts":   _utcnow().isoformat(),
                "cost_usd": cost_usd,
            })
            return
        job.status = final_status
        job.completed_at = _utcnow()
        job.cost_usd = cost_usd
        job.error = error_msg
        job.output_path = result.get("output_path")
        job.log_path = result.get("log_path")
        db.commit()

    bus.publish_from_thread(job_id, {
        "kind": (
            "job_failed" if final_status == JobStatus.FAILED else
            "job_cancelled" if final_status == JobStatus.CANCELLED else
            "job_completed"
        ),
        "ts":   _utcnow().isoformat(),
        "status": final_status.value,
        "cost_usd": cost_usd,
        "error": error_msg,
    })
