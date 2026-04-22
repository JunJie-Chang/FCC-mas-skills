"""
utils/cost_tracker.py — Session cost estimator.

Usage in any agent:
    from utils.cost_tracker import tracker
    tracker.record_claude(model, input_tokens, output_tokens)
    tracker.record_whisper(duration_seconds)
    tracker.record_dalle(n_images)
    tracker.record_tavily(n_calls)

Print report:
    tracker.print_summary()

Prices are hardcoded constants (Anthropic / OpenAI pricing, may drift over time).
Actual charges: check each platform's dashboard.
"""

# ── Pricing constants ─────────────────────────────────────────────────────────
# Claude: per 1M tokens
_CLAUDE_PRICES = {
    "claude-opus-4-6":          {"in": 15.00, "out": 75.00},
    "claude-haiku-4-5-20251001": {"in":  0.80, "out":  4.00},
    # fallback for unknown models
    "_default":                  {"in":  3.00, "out": 15.00},
}

_WHISPER_PER_SECOND = 0.006 / 60   # $0.006/min
_DALLE3_PER_IMAGE   = 0.04          # standard 1024×1024
# Tavily: free tier tracked as call count only (no $ estimate)


# ── Tracker ───────────────────────────────────────────────────────────────────

class CostTracker:
    def __init__(self):
        self.reset()

    def reset(self):
        self._claude: list[dict] = []   # {model, in_tok, out_tok, cost}
        self._whisper_sec: float = 0.0
        self._dalle_images: int = 0
        self._tavily_calls: int = 0
        self._ckpt_claude: int = 0
        self._ckpt_whisper: float = 0.0
        self._ckpt_tavily: int = 0

    # ── Record ────────────────────────────────────────────────────────────────

    def record_claude(self, model: str, input_tokens: int, output_tokens: int) -> None:
        prices = _CLAUDE_PRICES.get(model, _CLAUDE_PRICES["_default"])
        cost = (input_tokens * prices["in"] + output_tokens * prices["out"]) / 1_000_000
        self._claude.append({
            "model":   model,
            "in_tok":  input_tokens,
            "out_tok": output_tokens,
            "cost":    cost,
        })

    def record_whisper(self, duration_seconds: float) -> None:
        self._whisper_sec += duration_seconds

    def record_dalle(self, n_images: int = 1) -> None:
        self._dalle_images += n_images

    def record_tavily(self, n_calls: int = 1) -> None:
        self._tavily_calls += n_calls

    # ── Per-task summary ──────────────────────────────────────────────────────

    def print_task_summary(self) -> None:
        """Print cost for this task only (since last checkpoint), then advance."""
        task_claude  = self._claude[self._ckpt_claude:]
        task_whisper = self._whisper_sec - self._ckpt_whisper
        task_tavily  = self._tavily_calls - self._ckpt_tavily

        self._ckpt_claude  = len(self._claude)
        self._ckpt_whisper = self._whisper_sec
        self._ckpt_tavily  = self._tavily_calls

        in_tok     = sum(r["in_tok"]  for r in task_claude)
        out_tok    = sum(r["out_tok"] for r in task_claude)
        claude_usd = sum(r["cost"]    for r in task_claude)
        whisper_usd = task_whisper * _WHISPER_PER_SECOND
        total_usd  = claude_usd + whisper_usd

        parts = []
        if task_claude:
            parts.append(f"Claude {in_tok:,}in+{out_tok:,}out tok  ${claude_usd:.4f}")
        if task_whisper:
            parts.append(f"Whisper {task_whisper/60:.1f}min  ${whisper_usd:.4f}")
        if task_tavily:
            parts.append(f"Tavily {task_tavily} calls")
        if parts:
            print("   💰 " + " | ".join(parts) + f"  →  total ${total_usd:.4f}")

    # ── Report ────────────────────────────────────────────────────────────────

    def total_usd(self) -> float:
        claude_total  = sum(r["cost"] for r in self._claude)
        whisper_total = self._whisper_sec * _WHISPER_PER_SECOND
        dalle_total   = self._dalle_images * _DALLE3_PER_IMAGE
        return claude_total + whisper_total + dalle_total

    def print_summary(self) -> None:
        print("\n" + "=" * 44)
        print("  Session Cost Report (estimated)")
        print("=" * 44)

        if self._claude:
            # Group by model
            by_model: dict[str, dict] = {}
            for r in self._claude:
                m = r["model"]
                if m not in by_model:
                    by_model[m] = {"in": 0, "out": 0, "cost": 0.0}
                by_model[m]["in"]   += r["in_tok"]
                by_model[m]["out"]  += r["out_tok"]
                by_model[m]["cost"] += r["cost"]
            for model, d in by_model.items():
                short = model.split("-")[1] if "-" in model else model
                print(f"  Claude ({short:<8})  "
                      f"{d['in']:>7,} in + {d['out']:>6,} out tok   "
                      f"${d['cost']:.4f}")

        if self._whisper_sec:
            cost = self._whisper_sec * _WHISPER_PER_SECOND
            mins = self._whisper_sec / 60
            print(f"  Whisper STT       {mins:>7.1f} min                  ${cost:.4f}")

        if self._dalle_images:
            cost = self._dalle_images * _DALLE3_PER_IMAGE
            print(f"  DALL-E 3          {self._dalle_images:>7} image(s)              ${cost:.4f}")

        if self._tavily_calls:
            print(f"  Tavily            {self._tavily_calls:>7} call(s)               (free tier)")

        print("-" * 44)
        print(f"  Total estimated:                        ${self.total_usd():.4f}")
        print("=" * 44)


# ── Module-level singleton ────────────────────────────────────────────────────

tracker = CostTracker()
