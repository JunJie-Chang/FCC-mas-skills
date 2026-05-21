"""
utils/cost_tracker.py — Session cost estimator.

Usage in any agent:
    from utils.cost_tracker import tracker
    tracker.record_claude(model, input_tokens, output_tokens)
    tracker.record_stt(duration_seconds)
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
    "claude-opus-4-7":          {"in": 15.00, "out": 75.00},
    "claude-sonnet-4-6":        {"in":  3.00, "out": 15.00},
    "claude-haiku-4-5-20251001": {"in":  0.80, "out":  4.00},
    # fallback for unknown models
    "_default":                  {"in":  3.00, "out": 15.00},
}

_TASK_COST_WARN_USD = 0.30   # print ⚠ if a single task exceeds this

_STT_PER_SECOND   = 0.006 / 60   # $0.006/min — same rate for gpt-4o-transcribe and whisper-1
_DALLE3_PER_IMAGE = 0.04          # standard 1024×1024
# Tavily: free tier tracked as call count only (no $ estimate)


# ── Tracker ───────────────────────────────────────────────────────────────────

class CostTracker:
    def __init__(self):
        self.reset()

    def reset(self):
        self._claude: list[dict] = []   # {model, in_tok, out_tok, cost}
        self._stt_sec: float = 0.0
        self._dalle_images: int = 0
        self._tavily_calls: int = 0
        self._ckpt_claude: int = 0
        self._ckpt_stt: float = 0.0
        self._ckpt_tavily: int = 0
        self._ckpt_dalle: int = 0
        self._warned_models: set = set()

    # ── Record ────────────────────────────────────────────────────────────────

    def record_claude(self, model: str, input_tokens: int, output_tokens: int) -> None:
        if model not in _CLAUDE_PRICES and model not in self._warned_models:
            print(f"[cost] ⚠ unknown model {model!r}，用 _default 價格估算")
            self._warned_models.add(model)
        prices = _CLAUDE_PRICES.get(model, _CLAUDE_PRICES["_default"])
        cost = (input_tokens * prices["in"] + output_tokens * prices["out"]) / 1_000_000
        self._claude.append({
            "model":   model,
            "in_tok":  input_tokens,
            "out_tok": output_tokens,
            "cost":    cost,
        })

    def record_stt(self, duration_seconds: float) -> None:
        self._stt_sec += duration_seconds

    def record_dalle(self, n_images: int = 1) -> None:
        self._dalle_images += n_images

    def record_tavily(self, n_calls: int = 1) -> None:
        self._tavily_calls += n_calls

    # ── Per-task summary ──────────────────────────────────────────────────────

    def print_task_summary(self) -> None:
        """Print cost for this task only (since last checkpoint), then advance."""
        task_claude = self._claude[self._ckpt_claude:]
        task_stt    = self._stt_sec - self._ckpt_stt
        task_tavily = self._tavily_calls - self._ckpt_tavily
        task_dalle  = self._dalle_images - self._ckpt_dalle

        self._ckpt_claude = len(self._claude)
        self._ckpt_stt    = self._stt_sec
        self._ckpt_tavily = self._tavily_calls
        self._ckpt_dalle  = self._dalle_images

        in_tok     = sum(r["in_tok"]  for r in task_claude)
        out_tok    = sum(r["out_tok"] for r in task_claude)
        claude_usd = sum(r["cost"]    for r in task_claude)
        stt_usd    = task_stt * _STT_PER_SECOND
        dalle_usd  = task_dalle * _DALLE3_PER_IMAGE
        total_usd  = claude_usd + stt_usd + dalle_usd

        parts = []
        if task_claude:
            parts.append(f"Claude {in_tok:,}in+{out_tok:,}out tok  ${claude_usd:.4f}")
        if task_stt:
            parts.append(f"STT {task_stt/60:.1f}min  ${stt_usd:.4f}")
        if task_dalle:
            parts.append(f"DALL-E {task_dalle} img  ${dalle_usd:.4f}")
        if task_tavily:
            parts.append(f"Tavily {task_tavily} calls")
        if parts:
            line = "   💰 " + " | ".join(parts) + f"  →  total ${total_usd:.4f}"
            if total_usd >= _TASK_COST_WARN_USD:
                line += f"  ⚠ 超過 ${_TASK_COST_WARN_USD:.2f}"
            print(line)

    # ── Report ────────────────────────────────────────────────────────────────

    def total_usd(self) -> float:
        claude_total = sum(r["cost"] for r in self._claude)
        stt_total    = self._stt_sec * _STT_PER_SECOND
        dalle_total  = self._dalle_images * _DALLE3_PER_IMAGE
        return claude_total + stt_total + dalle_total

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

        if self._stt_sec:
            cost = self._stt_sec * _STT_PER_SECOND
            mins = self._stt_sec / 60
            print(f"  STT               {mins:>7.1f} min                  ${cost:.4f}")

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
