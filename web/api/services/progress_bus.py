"""
web/api/services/progress_bus.py — In-process pub/sub for job progress.

The flow:

    agent (worker thread) ──progress_cb──> bus.publish(job_id, event)
                                                  │
                                                  ├── persist as JobEvent row
                                                  └── push to asyncio.Queue per job
                                                            │
                                                            └── SSE handler yields

The agent code is synchronous, so the callback runs on the agent's
worker thread. We hop back to the FastAPI event loop with
`asyncio.run_coroutine_threadsafe` to enqueue on the per-job queue.

Why an in-process bus rather than Redis pub/sub:
  - Phase 1 is single-process. No need for cross-instance fanout yet.
  - Lower latency, no extra moving part to operate.
  - Trade-off documented in FRONTEND_PLAN.md §4.2: when we need
    horizontal scale or job durability across restarts, swap this for
    Redis Streams / Postgres LISTEN/NOTIFY.
"""

import asyncio
import logging
from typing import Any

from sqlalchemy.orm import Session

from web.api.db import SessionLocal
from web.api.models import JobEvent

log = logging.getLogger("progress_bus")


class ProgressBus:
    """
    One bus instance per FastAPI app. Each job has its own queue while
    at least one subscriber is connected; queues are torn down once
    the job finishes AND all subscribers disconnect.
    """

    def __init__(self) -> None:
        # job_id -> set of asyncio.Queue (one per active SSE subscriber)
        self._subscribers: dict[str, set[asyncio.Queue]] = {}
        # The event loop this bus belongs to — captured on first use so
        # the agent's worker thread can hop back to it. Set lazily
        # because the bus is constructed before the loop exists.
        self._loop: asyncio.AbstractEventLoop | None = None
        self._lock = asyncio.Lock()

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Called once from FastAPI lifespan startup."""
        self._loop = loop

    # ── Publish path ─────────────────────────────────────────────────

    def publish_from_thread(self, job_id: str, event: dict[str, Any]) -> None:
        """
        Thread-safe entry point used by the agent's progress_cb.

        Persists the event synchronously (the worker thread holds its
        own DB session) so a subscriber that joins later can replay it.
        Then schedules a fanout on the FastAPI event loop.
        """
        # Step 1: persist. Done on the calling thread because we already
        # have a SessionLocal and waiting for the loop adds latency.
        try:
            event_id = self._persist(job_id, event)
        except Exception:
            log.exception("failed to persist event for %s", job_id)
            event_id = None

        # Step 2: fanout to live subscribers via the FastAPI loop.
        if self._loop is None:
            return  # No subscribers possible without a bound loop
        # Tag with the persisted id so SSE last-event-id works.
        event_with_id = {**event, "_event_id": event_id} if event_id is not None else dict(event)
        asyncio.run_coroutine_threadsafe(
            self._fanout(job_id, event_with_id),
            self._loop,
        )

    def _persist(self, job_id: str, event: dict[str, Any]) -> int:
        """Save the event to the JobEvent table; return its row id."""
        # Worker-thread-owned session — short-lived, opens and closes
        # per event. Concurrency is fine on SQLite WAL mode (low write
        # volume per job) and would obviously generalize to Postgres.
        kind = event.get("kind", "info")
        payload = {k: v for k, v in event.items() if k != "kind"}
        with SessionLocal() as db:  # type: Session
            row = JobEvent(job_id=job_id, kind=kind, payload=payload)
            db.add(row)
            db.commit()
            db.refresh(row)
            return row.id

    async def _fanout(self, job_id: str, event: dict[str, Any]) -> None:
        """Enqueue on every active subscriber's queue for this job."""
        queues = self._subscribers.get(job_id)
        if not queues:
            return
        # Snapshot the set so a subscriber unsubscribing mid-iteration
        # doesn't trip RuntimeError. set.copy is O(n).
        for q in queues.copy():
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                # Drop the slow consumer's connection — the next SSE
                # client connecting will replay from persisted events.
                queues.discard(q)

    # ── Subscribe path ───────────────────────────────────────────────

    async def subscribe(self, job_id: str) -> asyncio.Queue:
        """
        Register an SSE subscriber. Returns a queue to read from. The
        caller is responsible for calling unsubscribe() on disconnect.
        """
        async with self._lock:
            queue: asyncio.Queue = asyncio.Queue(maxsize=1024)
            self._subscribers.setdefault(job_id, set()).add(queue)
            return queue

    async def unsubscribe(self, job_id: str, queue: asyncio.Queue) -> None:
        async with self._lock:
            queues = self._subscribers.get(job_id)
            if not queues:
                return
            queues.discard(queue)
            if not queues:
                del self._subscribers[job_id]


# Module-level singleton — one bus per process. Bound to the FastAPI
# event loop in the lifespan callback.
bus = ProgressBus()
