"""
router.py — Dispatch confirmed PlanTasks to the correct agent.

Add new agents here as they are implemented.
Unfinished agents raise NotImplementedError with a clear message.
"""
from typing import Union
from utils.planner import PlanTask
from utils.progress import ProgressCb


_AGENT_DEFAULT_SUBDIR = {
    "translation": "daily",
    "podcast":     "weekly",
    "speech_ppt":  "weekly",
}


def dispatch(
    task: PlanTask,
    intern_name: Union[str, list[str]],
    task_date: str = None,
    subdir: str = None,
    mode: str = "short",
    progress_cb: ProgressCb = None,
) -> dict:
    """
    Route a confirmed PlanTask to its agent and return the result.

    Args:
        task:        Confirmed PlanTask with agent_type + instruction.
        intern_name: Intern name(s) for file naming.
        task_date:   Date string YYYY-MM-DD; defaults to today.
        subdir:      Output subfolder — 'daily', 'weekly', or 'adhoc'.
                     When None, each agent_type uses its own default
                     (translation→daily, podcast/speech_ppt→weekly, others→adhoc).
        progress_cb: Optional callback for structured progress events.
                     CLI path leaves this as None — existing print()
                     output is unchanged. Web layer passes a callback
                     that publishes to its SSE bus.

    Returns:
        dict with at least 'output_path' and 'log_path'.
    """
    resolved_subdir = subdir or _AGENT_DEFAULT_SUBDIR.get(task.agent_type, "adhoc")

    kwargs = dict(
        task_instruction = task.instruction,
        intern_name      = intern_name,
        task_date        = task_date,
        subdir           = resolved_subdir,
        mode             = mode,
        progress_cb      = progress_cb,
    )

    agent_type = task.agent_type

    if agent_type == "company_info":
        from agents.company_info_agent import run
        return run(**kwargs)

    elif agent_type == "person_info":
        from agents.person_info_agent import run
        return run(**kwargs)

    elif agent_type == "translation":
        from agents.translation_agent import run
        # translation_agent requires title/source/body_text explicitly;
        # router callers should pass these via task.instruction as JSON.
        import json as _json
        instr = task.instruction
        try:
            parsed = _json.loads(instr)
            return run(
                title=parsed["title"],
                source=parsed.get("source", ""),
                body_text=parsed["body_text"],
                intern_name=intern_name,
                pub_date=parsed.get("pub_date"),
                task_date=task_date,
                subdir=resolved_subdir,
                progress_cb=progress_cb,
            )
        except Exception:
            raise ValueError(
                "translation_agent：task.instruction 需為 JSON，含 title / source / body_text 欄位"
            )

    elif agent_type in ("letter", "meeting"):
        from agents.dictation_agent import run
        return run(**kwargs)

    elif agent_type == "verbal_cleanup":
        from agents.verbal_cleanup_agent import run
        return run(**kwargs)

    elif agent_type == "speech_ppt":
        from agents.speech_ppt_agent import run
        return run(
            task_instruction=task.instruction,
            intern_name=intern_name,
            task_date=task_date,
            subdir=resolved_subdir,
            progress_cb=progress_cb,
        )

    elif agent_type == "podcast":
        from agents.podcast_agent import run
        return run(
            task_instruction=task.instruction,
            intern_name=intern_name,
            task_date=task_date,
            subdir=resolved_subdir,
            progress_cb=progress_cb,
        )

    else:
        raise ValueError(f"未知的 agent_type：{agent_type!r}")
