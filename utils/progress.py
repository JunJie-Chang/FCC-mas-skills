"""
utils/progress.py — Optional progress-event callback used by all agents.

Each agent's run() accepts an optional `progress_cb: ProgressCb` and stores
it in state["progress_cb"]. Agent nodes call:

    emit(state.get("progress_cb"), "node_start", node="parse_task")

When the callback is None (CLI path), emit() is a no-op — agents continue
to use print() for human-readable terminal output exactly as before. When
the callback is provided (web layer), it receives structured event dicts
that can be persisted to the JobEvent table and streamed to the browser
via Server-Sent Events.

Event dict shape:
    {
        "kind":    str,            # event category — see kinds below
        "ts":      str,            # ISO 8601 UTC timestamp (added here)
        ... arbitrary kind-specific payload (node, query, round, …)
    }

Canonical event kinds (extend as needed; consumers must tolerate unknowns):
    node_start              — entering an agent node
    node_end                — leaving an agent node (with optional summary)
    search_batch            — multi-query batch (initial queries from parse_task)
    search_query            — single Tavily query executed
    evaluate                — react_loop evaluate() finished, with todo counts
    confirm_request         — agent needs user input (planner / subject_review / slides)
    info                    — generic message
    warning                 — non-fatal issue worth surfacing
    error                   — fatal issue; agent run is aborting
"""

from datetime import datetime, timezone
from typing import Any, Callable, Optional

ProgressCb = Optional[Callable[[dict], None]]


def emit(cb: ProgressCb, kind: str, **payload: Any) -> None:
    """
    Send an event to the callback if present; no-op otherwise.

    The callback is wrapped in a try/except — a buggy web-side consumer
    must never be able to crash an agent run. Bad callbacks are silently
    dropped (intentional; web layer is responsible for its own error
    surface).
    """
    if cb is None:
        return
    event = {
        "kind": kind,
        "ts":   datetime.now(timezone.utc).isoformat(),
        **payload,
    }
    try:
        cb(event)
    except Exception:
        pass
