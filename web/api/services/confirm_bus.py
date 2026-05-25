"""
web/api/services/confirm_bus.py — Per-job pending-checkpoint futures.

When an agent hits an interactive checkpoint (planner.confirm,
subject_review, speech_ppt.confirm_slides) the WebConfirmStrategy:

    1. Calls `confirm_bus.open(job_id)` → gets a concurrent.futures.Future
    2. Updates Job.status to the matching `needs_*` enum value
    3. Publishes a `*_request` event with the payload
    4. Blocks on the future via `f.result(timeout=...)` — agent's worker
       thread sits here until the browser submits the decision.

When `POST /jobs/{id}/confirm` arrives, the route handler calls
`confirm_bus.resolve(job_id, response)` which unblocks the agent.

Cross-thread coordination: the strategy and the future live on the
agent's worker thread; the route handler resolves from the FastAPI
event-loop thread. `concurrent.futures.Future` is thread-safe for
this exact pattern.
"""

import threading
from concurrent.futures import Future
from typing import Any


class ConfirmBus:
    """One bus per FastAPI app. Routes futures by job_id."""

    def __init__(self) -> None:
        self._pending: dict[str, Future[dict[str, Any]]] = {}
        self._lock = threading.Lock()

    def open(self, job_id: str) -> Future[dict[str, Any]]:
        """
        Register a pending checkpoint for `job_id` and return its Future.

        If a previous future for the same job exists (e.g. agent hit
        another checkpoint without the prior one resolving — should
        not happen but defensive), cancel it first.
        """
        with self._lock:
            existing = self._pending.get(job_id)
            if existing is not None and not existing.done():
                existing.cancel()
            f: Future[dict[str, Any]] = Future()
            self._pending[job_id] = f
            return f

    def resolve(self, job_id: str, response: dict[str, Any]) -> bool:
        """
        Resolve the pending future for `job_id`.

        Returns True on success, False if there was no pending future
        (caller should surface that as a 409 to the user).
        """
        with self._lock:
            f = self._pending.pop(job_id, None)
        if f is None or f.done():
            return False
        f.set_result(response)
        return True

    def cancel(self, job_id: str) -> bool:
        """
        Force-cancel a pending checkpoint — used by POST /jobs/{id}/cancel.
        Strategy interprets the cancellation result and aborts the agent.
        """
        with self._lock:
            f = self._pending.pop(job_id, None)
        if f is None or f.done():
            return False
        f.cancel()
        return True


# Module-level singleton, one per process.
confirm_bus = ConfirmBus()
