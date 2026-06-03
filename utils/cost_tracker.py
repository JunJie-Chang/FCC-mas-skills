"""
utils/cost_tracker.py — lightweight, non-fatal usage / cost logging.

Records STT (and optionally DALL-E) usage to a JSONL log under
``$FCC_MAS_HOME/output/.cost_log.jsonl`` so spend can be reviewed later.

Design rule: cost logging must NEVER break the user-facing task. Every
public method swallows its own errors — a failed log line is reported on
stderr and otherwise ignored, so a transcription or slide build always
completes even if logging fails.

Rates are approximate and overridable via env vars
(``FCC_STT_RATE_PER_MIN``, ``FCC_DALLE_RATE_PER_IMAGE``); verify against
https://openai.com/api/pricing/ before relying on the totals.
"""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


def _home() -> Path:
    return Path(os.environ.get("FCC_MAS_HOME", os.path.expanduser("~/.fcc-mas")))


def _rate(env_name: str, default: float) -> float:
    try:
        return float(os.environ.get(env_name, default))
    except (TypeError, ValueError):
        return default


class CostTracker:
    """Append-only usage logger. Never raises to the caller."""

    def __init__(self, log_path: Path | None = None):
        self._log_path = log_path or (_home() / "output" / ".cost_log.jsonl")

    def _write(self, record: dict) -> None:
        try:
            record["ts"] = datetime.now(timezone.utc).isoformat()
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as exc:  # logging must never break the task
            print(f"[cost_tracker] ⚠ 無法寫入用量紀錄：{exc}", file=sys.stderr)

    def record_stt(self, duration_seconds: float,
                   model: str = "gpt-4o-transcribe") -> float:
        """Log an STT call. Returns the estimated USD cost (0.0 on failure)."""
        try:
            minutes = max(0.0, float(duration_seconds)) / 60.0
            cost = round(minutes * _rate("FCC_STT_RATE_PER_MIN", 0.006), 6)
            self._write({
                "kind": "stt", "model": model,
                "duration_s": round(float(duration_seconds), 2),
                "est_usd": cost,
            })
            return cost
        except Exception as exc:
            print(f"[cost_tracker] ⚠ record_stt 失敗：{exc}", file=sys.stderr)
            return 0.0

    def record_dalle(self, n: int = 1, size: str = "1024x1024",
                     model: str = "dall-e-3") -> float:
        """Log DALL-E image generation. Returns the estimated USD cost."""
        try:
            cost = round(max(0, int(n)) * _rate("FCC_DALLE_RATE_PER_IMAGE", 0.04), 6)
            self._write({
                "kind": "dalle", "model": model,
                "n": int(n), "size": size, "est_usd": cost,
            })
            return cost
        except Exception as exc:
            print(f"[cost_tracker] ⚠ record_dalle 失敗：{exc}", file=sys.stderr)
            return 0.0


# Module-level singleton expected by callers:
#   from utils.cost_tracker import tracker
tracker = CostTracker()
