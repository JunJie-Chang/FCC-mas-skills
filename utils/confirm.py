"""
utils/confirm.py — Pluggable interactive-checkpoint strategy.

The CLI has three interactive checkpoints that pause the pipeline and wait
for a human decision:

    planner.confirm          — review parsed task list, allow edit / merge / delete
    subject_review           — review STT-extracted proper nouns, correct mishears
    speech_ppt.confirm_slides — preview slide plan before DALL-E image generation

Each of these calls input() directly in a loop. That works for the CLI but
makes the web layer impossible: a browser tab can't supply data through
sys.stdin.

This module defines a `ConfirmStrategy` protocol with one method per
checkpoint. The CLI registers a `StdinConfirmStrategy` (the existing
behavior). The web layer will register a different strategy that emits a
`confirm_request` SSE event and blocks on a bus message until the user
clicks the confirm button in the browser.

Active strategy is bound per-thread (same pattern as
`utils/cost_tracker.use_tracker`), so the web job runner can set its own
strategy on its worker without disturbing the CLI default.

    from utils.confirm import use_strategy, WebConfirmStrategy
    with use_strategy(WebConfirmStrategy(job_id=...)):
        agent.run(...)
"""

import threading
from contextlib import contextmanager
from typing import Any, Iterator, Protocol


class ConfirmStrategy(Protocol):
    """
    Three checkpoint methods. Each receives the data to present and
    returns the user's decision in the agent-expected shape.

    Implementations must be synchronous from the agent's perspective.
    Web-side implementations can internally do `loop.run_until_complete(...)`
    on a future that the SSE handler resolves — agents stay sync.
    """

    def confirm_tasks(self, tasks: list[Any]) -> list[Any] | None:
        """Confirm a list of planner.PlanTask objects.

        Returns the (possibly edited) list to proceed with, or None if
        the user cancelled the whole batch.
        """
        ...

    def review_subjects(self, transcript: str, mentions: list[dict]) -> str:
        """Show STT subject mentions, accept corrections, return the
        (possibly-rewritten) transcript ready for parse_tasks().
        """
        ...

    def confirm_slides(self, slides_plan: list[dict], topic: str,
                       generate_images: bool) -> bool:
        """Speech-PPT slide plan preview. Returns True to proceed with
        image generation + PPT build, False to abort.
        """
        ...


class StdinConfirmStrategy:
    """
    Default CLI strategy. Delegates to the existing input()-driven
    implementations that live next to each checkpoint's data (so the
    presentation logic stays with the data it presents).

    The implementations are imported lazily to avoid circular imports —
    planner / subject_review / speech_ppt all eventually import this
    module via the get_active_strategy() lookup.
    """

    def confirm_tasks(self, tasks):
        from utils.planner import _confirm_tasks_stdin
        return _confirm_tasks_stdin(tasks)

    def review_subjects(self, transcript, mentions):
        from utils.subject_review import _review_subjects_stdin
        return _review_subjects_stdin(transcript, mentions)

    def confirm_slides(self, slides_plan, topic, generate_images):
        from agents.speech_ppt_agent import _confirm_slides_stdin
        return _confirm_slides_stdin(slides_plan, topic, generate_images)


# ── Active strategy plumbing ─────────────────────────────────────────────────

_default_strategy: ConfirmStrategy = StdinConfirmStrategy()
_local = threading.local()


def get_active_strategy() -> ConfirmStrategy:
    """Return the confirm strategy bound to the current thread, or the
    process-wide default (StdinConfirmStrategy)."""
    s = getattr(_local, "strategy", None)
    return s if s is not None else _default_strategy


@contextmanager
def use_strategy(s: ConfirmStrategy) -> Iterator[ConfirmStrategy]:
    """
    Bind `s` as the active strategy for the current thread / context.

    Used by the web job runner to wire confirm checkpoints to the SSE
    bus instead of stdin:

        with use_strategy(WebConfirmStrategy(job_id)):
            agent.run(...)
    """
    previous = getattr(_local, "strategy", None)
    _local.strategy = s
    try:
        yield s
    finally:
        _local.strategy = previous
