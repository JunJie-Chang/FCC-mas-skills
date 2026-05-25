"""
web/api/services/confirm_strategy.py — Web-side ConfirmStrategy.

Drop-in replacement for utils.confirm.StdinConfirmStrategy that lets a
running agent pause for browser-side user input. The flow per
checkpoint:

    agent code → ConfirmStrategy method
                    │
                    ├── update Job.status → needs_*
                    ├── publish `*_request` SSE event with payload
                    ├── confirm_bus.open(job_id) → Future
                    └── block on Future.result(timeout=30min)
                                        │
                                        ▼
    browser POST /jobs/{id}/confirm
        └── confirm_bus.resolve(job_id, decision)
            └── Future unblocks → strategy returns decision to agent

`agents/...` see plain Python returns — they don't know whether a
human typed at stdin or clicked in a browser. That decoupling is the
whole point of Phase 0's strategy pattern.
"""

import logging
import time
from concurrent.futures import CancelledError, TimeoutError as FutureTimeoutError
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from utils.confirm import ConfirmStrategy
from utils.planner import PlanTask
from web.api.db import SessionLocal
from web.api.models import Job, JobStatus
from web.api.services.confirm_bus import confirm_bus
from web.api.services.progress_bus import bus

log = logging.getLogger("confirm_strategy")

# 30 min default. CY's audio dictations can sit while interns step
# away — generous timeout, but bounded so abandoned jobs don't sit
# forever in needs_* states.
_DEFAULT_TIMEOUT_SEC = 30 * 60


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CheckpointTimeout(Exception):
    """Raised when no user response arrives within the timeout."""


class CheckpointCancelled(Exception):
    """Raised when the user (or a /cancel route) aborts the checkpoint."""


class WebConfirmStrategy:
    """One instance per job. Bound for the agent's worker thread via
    `with use_strategy(strategy):` in the job runner."""

    def __init__(self, job_id: str, timeout_sec: int = _DEFAULT_TIMEOUT_SEC) -> None:
        self.job_id = job_id
        self.timeout_sec = timeout_sec

    # ── ConfirmStrategy protocol ─────────────────────────────────────

    def confirm_tasks(self, tasks: list[PlanTask]) -> list[PlanTask] | None:
        """planner.confirm — present parsed tasks, accept edits / merge / cancel."""
        payload = {
            "tasks": [
                {
                    "agent_type":  t.agent_type,
                    "label":       t.label,
                    "instruction": t.instruction,
                }
                for t in tasks
            ],
        }
        try:
            response = self._await_user(
                status=JobStatus.NEEDS_CONFIRM,
                kind="confirm_tasks_request",
                payload=payload,
            )
        except CheckpointCancelled:
            return None

        if response.get("action") == "cancel":
            return None

        new_tasks = response.get("tasks", []) or []
        return [
            PlanTask(
                agent_type  = t["agent_type"],
                label       = t["label"],
                instruction = t["instruction"],
            )
            for t in new_tasks
        ]

    def review_subjects(self, transcript: str, mentions: list[dict]) -> str:
        """subject_review — show STT-extracted proper nouns, accept replacements."""
        payload = {
            "transcript": transcript,
            "mentions":   mentions,
        }
        try:
            response = self._await_user(
                status=JobStatus.NEEDS_SUBJECT_REVIEW,
                kind="subject_review_request",
                payload=payload,
            )
        except CheckpointCancelled:
            # Subject review cancellation is non-fatal: caller (the
            # planner pipeline) treats it as "skip review", keeps the
            # original transcript. Different semantics from confirm_tasks
            # cancel (which aborts the whole batch).
            return transcript

        new_transcript = response.get("transcript")
        return new_transcript if isinstance(new_transcript, str) else transcript

    def confirm_slides(self, slides_plan: list[dict], topic: str,
                       generate_images: bool) -> bool:
        """speech_ppt.confirm_slides — preview slides before burning DALL-E credits."""
        payload = {
            "slides_plan":     slides_plan,
            "topic":           topic,
            "generate_images": generate_images,
        }
        try:
            response = self._await_user(
                status=JobStatus.NEEDS_SLIDE_CONFIRM,
                kind="slide_confirm_request",
                payload=payload,
            )
        except CheckpointCancelled:
            return False
        return bool(response.get("proceed", False))

    # ── Internals ─────────────────────────────────────────────────────

    def _await_user(self, *, status: JobStatus, kind: str,
                    payload: dict[str, Any]) -> dict[str, Any]:
        """
        Common path for all three checkpoints.

        Steps:
          1. Open a future on the confirm bus (caller side).
          2. Flip Job.status to the target needs_* value.
          3. Publish a `*_request` SSE event so the browser knows to
             open its modal.
          4. Block thread on Future.result(timeout=…). The
             POST /jobs/{id}/confirm route resolves the future.
          5. Flip Job.status back to RUNNING. Publish a
             `*_resolved` event so the browser closes its modal /
             tears down its modal state.

        Raises CheckpointCancelled when the user (or /cancel route)
        abandons the checkpoint; CheckpointTimeout when no response
        arrives within the timeout (caller side surfaces both as
        sensible agent-side returns — None for confirm_tasks, original
        transcript for subjects, False for slides).
        """
        future = confirm_bus.open(self.job_id)

        # --- side effects 1: update Job row + publish request event ---
        self._set_status(status)
        bus.publish_from_thread(self.job_id, {
            "kind":     kind,
            "ts":       _utcnow().isoformat(),
            "payload":  payload,
            "timeout":  self.timeout_sec,
        })

        # --- side effect 2: block worker thread until user replies ---
        started = time.monotonic()
        try:
            response = future.result(timeout=self.timeout_sec)
        except FutureTimeoutError:
            self._restore_status(status, kind, reason="timeout",
                                 elapsed=time.monotonic() - started)
            raise CheckpointTimeout(
                f"checkpoint {kind} timed out after {self.timeout_sec}s",
            )
        except CancelledError:
            self._restore_status(status, kind, reason="cancelled",
                                 elapsed=time.monotonic() - started)
            raise CheckpointCancelled(f"checkpoint {kind} cancelled by user")

        # --- side effect 3: flip status back + publish resolved ---
        self._restore_status(status, kind, reason="resolved",
                             elapsed=time.monotonic() - started)
        return response

    def _set_status(self, status: JobStatus) -> None:
        with SessionLocal() as db:  # type: Session
            job = db.get(Job, self.job_id)
            if job is None:
                log.warning("WebConfirmStrategy: job %s vanished", self.job_id)
                return
            job.status = status
            db.commit()

    def _restore_status(self, was: JobStatus, kind: str,
                        reason: str, elapsed: float) -> None:
        """
        Move status back to RUNNING and publish a paired `*_resolved`
        event so the frontend can close its modal and update the log.

        Skipped if the user / cancel route already moved the job to
        CANCELLED — that's a terminal state owned by the route layer.
        """
        with SessionLocal() as db:
            job = db.get(Job, self.job_id)
            if job is None:
                return
            if job.status == JobStatus.CANCELLED:
                # Cancel route already terminated; don't resurrect.
                return
            job.status = JobStatus.RUNNING
            db.commit()

        # Pair every *_request with a *_resolved so the frontend can
        # match them up unambiguously even if it dropped the SSE
        # connection mid-checkpoint.
        resolved_kind = kind.replace("_request", "_resolved")
        bus.publish_from_thread(self.job_id, {
            "kind":     resolved_kind,
            "ts":       _utcnow().isoformat(),
            "reason":   reason,
            "elapsed":  round(elapsed, 2),
        })
