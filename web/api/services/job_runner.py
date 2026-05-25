"""
web/api/services/job_runner.py — Bridge from HTTP job rows to agent runs.

Two execution paths:

  Single-agent (Phase 1)        Job.type ∈ concrete AgentType
     execute_job
       └─ _run_single_agent
             └─ _dispatch_blocking(agent_type, ...)

  STT pipeline (Phase 5)        Job.type == "stt_pipeline"
     execute_job
       └─ _run_stt_pipeline
             ├─ utils.stt.transcribe(audio_path)
             ├─ utils.subject_review.review_subjects   ← needs_subject_review checkpoint
             ├─ utils.planner.parse_tasks
             ├─ utils.planner.confirm                  ← needs_confirm checkpoint
             └─ for each task: router.dispatch with sub-task progress_cb

Common machinery (per-job CostTracker via `use_tracker`, per-job
WebConfirmStrategy via `use_strategy`, progress_cb publishing via the
bus, asyncio.to_thread for the blocking agent code) is shared in
execute_job's setup/teardown.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from utils.confirm import use_strategy
from utils.cost_tracker import CostTracker, use_tracker
from web.api.db import SessionLocal
from web.api.models import Job, JobStatus, JobSubTask, Upload
from web.api.services.confirm_strategy import WebConfirmStrategy
from web.api.services.progress_bus import bus

log = logging.getLogger("job_runner")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_subtask_id() -> str:
    import uuid
    return uuid.uuid4().hex


def _friendly_stt_error(exc: Exception, audio_path: str) -> RuntimeError:
    """
    Translate raw OpenAI / ffmpeg exceptions from utils.stt into an
    actionable Chinese message. The original exception's __cause__ is
    preserved so the .log sidecar / server logs still have the full
    traceback for debugging.
    """
    raw = str(exc)
    ext = audio_path.rsplit(".", 1)[-1].lower() if "." in audio_path else ""
    lower = raw.lower()

    if "unsupported file format" in lower or "invalid_request_error" in lower:
        return RuntimeError(
            f"OpenAI STT 不支援的音檔格式（.{ext}）。請改用 m4a / mp3 / mp4 / wav / webm。"
            f"原始錯誤：{raw[:200]}"
        )
    if "rate limit" in lower or "429" in lower:
        return RuntimeError(
            "OpenAI / Anthropic 速率限制 — 稍候再試。原始錯誤：" + raw[:200]
        )
    if "ffmpeg" in lower or "ffprobe" in lower:
        return RuntimeError(
            "音檔處理失敗（ffmpeg / ffprobe 出錯）。"
            "確認檔案沒有損壞，或試著重新轉檔。原始錯誤：" + raw[:200]
        )
    if "no such file" in lower or "filenotfound" in lower:
        return RuntimeError(
            "找不到上傳的音檔（可能被清掉）。請重新上傳。"
        )
    # Generic fallback — still better than a bare BadRequestError.
    return RuntimeError(f"STT 轉錄失敗：{raw[:300]}")


# ── Single-agent dispatch ───────────────────────────────────────────

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
    Run a single agent. Synchronous on purpose — called via
    asyncio.to_thread (or from the STT pipeline's own worker thread).

    Delegates to `router.dispatch()` so all 7 agent types Just Work
    (Phase 0 already threaded progress_cb through the router). The
    router's special-casing handles translation's JSON-shaped
    instruction and speech_ppt's separate signature.

    extra.generate_images is honoured for speech_ppt via the router's
    own kwargs handling.

    Raises ValueError for unknown agent_type (surfaced as job=FAILED).
    """
    from router import dispatch as router_dispatch
    from utils.planner import PlanTask

    # router.dispatch's speech_ppt branch reads from task.instruction
    # directly and doesn't take generate_images — for the web layer we
    # want generate_images controllable from job extra. Special-case
    # that one type here; everything else goes through the router.
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

    plan_task = PlanTask(
        agent_type  = agent_type,
        label       = instruction[:40] or agent_type,
        instruction = instruction,
    )
    return router_dispatch(
        task        = plan_task,
        intern_name = intern_name,
        task_date   = task_date,
        subdir      = subdir,
        mode        = mode,
        progress_cb = progress_cb,
    )


# ── STT pipeline ────────────────────────────────────────────────────

def _resolve_upload_path(upload_id: str) -> str:
    """Look up an Upload row by id; return its on-disk path. Raises
    ValueError if missing — caller wraps in agent error semantics."""
    with SessionLocal() as db:
        row = db.get(Upload, upload_id)
        if row is None:
            raise ValueError(f"upload_id {upload_id!r} not found")
        return row.path


def _wrap_subtask_progress_cb(
    parent_progress_cb,
    subtask_id: str,
    subtask_idx: int,
):
    """
    Decorate the parent's progress_cb so every sub-task event carries
    `subtask_idx` + `subtask_id` in its payload. Frontend uses these to
    group the unified event stream into per-card sub-task logs.
    """
    def cb(event: dict[str, Any]) -> None:
        if parent_progress_cb is None:
            return
        # Don't mutate the caller's dict — agents may keep a reference
        # to it for their own bookkeeping.
        parent_progress_cb({
            **event,
            "subtask_idx": subtask_idx,
            "subtask_id":  subtask_id,
        })
    return cb


def _run_stt_pipeline(
    job_id: str,
    intern_name: str,
    task_date: str,
    mode: str,
    extra: dict[str, Any],
    progress_cb,
) -> dict[str, Any]:
    """
    The full STT path: transcribe audio, optionally review subjects,
    parse tasks, confirm, then dispatch each task as a sub-task. The
    parent job's `output_path` is left empty (each sub-task has its
    own); the parent's cost is the rolling sum of sub-task costs.

    Strategy hooks at subject_review and planner.confirm are wired via
    the use_strategy() context already established by execute_job.
    """
    upload_id = extra.get("upload_id")
    if not upload_id:
        raise ValueError("stt_pipeline 需要 extra.upload_id（請從 /new-audio 頁面上傳音檔）")

    audio_path = _resolve_upload_path(upload_id)

    # Lazy imports so the web layer's startup time isn't blown up by
    # the agent dep tree (openai, anthropic, langgraph, etc.).
    from utils.stt import transcribe
    from utils.subject_review import extract_subject_mentions, review_subjects
    from utils.planner import parse_tasks, confirm
    from router import dispatch as router_dispatch

    # 1. STT — wrap with user-friendly error mapping so a doomed
    # transcription doesn't dump a raw OpenAI exception into Job.error.
    progress_cb({"kind": "stt_started", "ts": _utcnow().isoformat()})
    try:
        transcript = transcribe(audio_path)
    except Exception as exc:
        raise _friendly_stt_error(exc, audio_path) from exc
    progress_cb({
        "kind": "stt_completed",
        "ts": _utcnow().isoformat(),
        "n_chars": len(transcript),
    })

    # 2. Subject review (Haiku extract → strategy presents → user corrects)
    mentions = extract_subject_mentions(transcript)
    if mentions:
        transcript = review_subjects(transcript, mentions)

    # 3. Parse → confirm
    tasks = parse_tasks(transcript)
    if not tasks:
        return {}   # nothing to do; job_runner marks CANCELLED
    confirmed = confirm(tasks)
    if confirmed is None:
        return {}   # user cancelled at planner.confirm
    tasks = confirmed

    # 4. Dispatch each task. Sub-task rows track per-task output / cost.
    progress_cb({
        "kind": "subtasks_planned",
        "ts": _utcnow().isoformat(),
        "n": len(tasks),
    })

    outputs: list[str] = []
    for idx, plan_task in enumerate(tasks):
        subtask_id = _new_subtask_id()
        # Persist sub-task row up front so the frontend can render it
        # at "queued" state immediately when the event arrives.
        with SessionLocal() as db:
            db.add(JobSubTask(
                id          = subtask_id,
                parent_id   = job_id,
                idx         = idx,
                agent_type  = plan_task.agent_type,
                label       = plan_task.label,
                instruction = plan_task.instruction,
                status      = JobStatus.RUNNING,
                started_at  = _utcnow(),
            ))
            db.commit()

        progress_cb({
            "kind":        "subtask_started",
            "ts":          _utcnow().isoformat(),
            "subtask_id":  subtask_id,
            "subtask_idx": idx,
            "agent_type":  plan_task.agent_type,
            "label":       plan_task.label,
        })

        sub_cb = _wrap_subtask_progress_cb(progress_cb, subtask_id, idx)
        sub_tracker = CostTracker()

        sub_error: str | None = None
        sub_result: dict[str, Any] = {}
        try:
            with use_tracker(sub_tracker):
                sub_result = router_dispatch(
                    task        = plan_task,
                    intern_name = intern_name,
                    task_date   = task_date,
                    mode        = mode,
                    progress_cb = sub_cb,
                )
        except Exception as exc:
            sub_error = f"{type(exc).__name__}: {exc}"
            log.exception("subtask %d (%s) failed", idx, plan_task.agent_type)

        sub_cost = sub_tracker.total_usd()
        sub_status = (
            JobStatus.FAILED if sub_error else
            JobStatus.CANCELLED if not sub_result.get("output_path") else
            JobStatus.DONE
        )

        with SessionLocal() as db:
            row = db.get(JobSubTask, subtask_id)
            if row is not None:
                row.status       = sub_status
                row.output_path  = sub_result.get("output_path")
                row.log_path     = sub_result.get("log_path")
                row.cost_usd     = sub_cost
                row.error        = sub_error
                row.completed_at = _utcnow()
                db.commit()

        progress_cb({
            "kind":        "subtask_completed",
            "ts":          _utcnow().isoformat(),
            "subtask_id":  subtask_id,
            "subtask_idx": idx,
            "status":      sub_status.value,
            "cost_usd":    sub_cost,
            "error":       sub_error,
        })

        if sub_result.get("output_path"):
            outputs.append(sub_result["output_path"])

    # Parent job aggregates: we return an empty output_path (no single
    # "the" docx) but populate `extra.output_paths` so the frontend can
    # offer a bulk download / list. cost_usd is the sum of sub-tracker
    # totals — execute_job re-reads that from the tracker we're not
    # holding, so we instead persist via DB sub-task aggregation.
    return {
        "output_path": "",  # explicit empty: parent has no single file
        "log_path":    "",
        "extra_outputs": outputs,
    }


# ── Top-level job execution ─────────────────────────────────────────

async def execute_job(job_id: str) -> None:
    """
    Entry point scheduled via asyncio.create_task from POST /jobs.
    Owns the full lifecycle for one job (single-agent OR stt_pipeline).
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

    tracker = CostTracker()

    def progress_cb(event: dict[str, Any]) -> None:
        bus.publish_from_thread(job_id, event)

    # Snapshot fields outside the worker thread.
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        if job is None:
            return
        job_type     = job.type
        instruction  = job.instruction
        intern_name  = job.intern_name
        task_date    = job.created_at.strftime("%Y-%m-%d")
        subdir       = job.subdir or "adhoc"
        mode         = job.mode
        extra        = dict(job.extra or {})

    confirm_strategy = WebConfirmStrategy(job_id=job_id)

    def _run() -> dict[str, Any]:
        # Per-job cost tracker + confirm strategy bound for this thread.
        with use_tracker(tracker), use_strategy(confirm_strategy):
            if job_type == "stt_pipeline":
                return _run_stt_pipeline(
                    job_id      = job_id,
                    intern_name = intern_name,
                    task_date   = task_date,
                    mode        = mode,
                    extra       = extra,
                    progress_cb = progress_cb,
                )
            return _dispatch_blocking(
                agent_type  = job_type,
                instruction = instruction,
                intern_name = intern_name,
                task_date   = task_date,
                subdir      = subdir,
                mode        = mode,
                extra       = extra,
                progress_cb = progress_cb,
            )

    error_msg: str | None = None
    result: dict[str, Any] = {}
    try:
        result = await asyncio.to_thread(_run)
    except NotImplementedError as exc:
        error_msg = str(exc)
        log.warning("job %s rejected: %s", job_id, error_msg)
    except Exception as exc:
        error_msg = f"{type(exc).__name__}: {exc}"
        log.exception("job %s failed", job_id)

    # Step 3: persist final state.
    parent_cost_usd = tracker.total_usd()
    is_stt = (job_type == "stt_pipeline")

    # For STT parents, sum sub-task costs (they ran under their own
    # CostTracker instances inside the pipeline and aren't included in
    # the parent's `tracker`). The parent's tracker still has the STT
    # call cost (utils/stt.py records into the active tracker).
    if is_stt:
        with SessionLocal() as db:
            subtasks = (
                db.query(JobSubTask)
                .filter(JobSubTask.parent_id == job_id)
                .all()
            )
        sub_cost_total = sum(s.cost_usd for s in subtasks)
        any_output = any(s.output_path for s in subtasks)
        parent_cost_usd += sub_cost_total

        if error_msg:
            final_status = JobStatus.FAILED
        elif not any_output:
            # All sub-tasks failed / cancelled — surface as parent
            # CANCELLED so the UI doesn't claim success.
            final_status = JobStatus.CANCELLED
        else:
            final_status = JobStatus.DONE
    else:
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
            # User cancelled mid-run — preserve.
            job.cost_usd = parent_cost_usd
            if result.get("output_path"):
                job.output_path = result["output_path"]
                job.log_path = result.get("log_path")
            job.completed_at = _utcnow()
            db.commit()
            bus.publish_from_thread(job_id, {
                "kind": "job_cancelled",
                "ts":   _utcnow().isoformat(),
                "cost_usd": parent_cost_usd,
            })
            return
        job.status = final_status
        job.completed_at = _utcnow()
        job.cost_usd = parent_cost_usd
        job.error = error_msg
        job.output_path = result.get("output_path")
        job.log_path = result.get("log_path")
        # STT parents stash aggregated sub-output paths in extra for the
        # frontend's bulk-download UI.
        if is_stt and result.get("extra_outputs"):
            job.extra = {**(job.extra or {}), "output_paths": result["extra_outputs"]}
        db.commit()

    bus.publish_from_thread(job_id, {
        "kind": (
            "job_failed" if final_status == JobStatus.FAILED else
            "job_cancelled" if final_status == JobStatus.CANCELLED else
            "job_completed"
        ),
        "ts":   _utcnow().isoformat(),
        "status":   final_status.value,
        "cost_usd": parent_cost_usd,
        "error":    error_msg,
    })
