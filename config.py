"""
config.py — Word/PPTX format settings and output paths.

All LLM call sites were removed when the project migrated from LangGraph
agents to Claude Code Skills (May 2026). Skills run inside a Claude Code
session and don't instantiate their own Anthropic clients, so model IDs
and API keys no longer live here. STT/DALL-E still use OPENAI_API_KEY
(loaded from .env in utils/stt.py and scripts/build_pptx_cli.py).
"""
import os

# ── Font ──────────────────────────────────────────────────────────────────────
FONT_NAME = "微軟正黑體"
FONT_NAME_FALLBACK = "Noto Sans CJK TC"  # used on non-Windows if 微軟正黑體 absent
FONT_SIZE_PT = 14          # body text
FONT_SIZE_TITLE_PT = 14    # title (same size, distinguished by bold)

# ── Paragraph ─────────────────────────────────────────────────────────────────
LINE_SPACING = 1.15        # WD_LINE_SPACING.MULTIPLE
SPACE_AFTER_PT = 5         # space after each paragraph

# ── Page (A4) ─────────────────────────────────────────────────────────────────
PAGE_WIDTH_CM = 21.0
PAGE_HEIGHT_CM = 29.7
MARGIN_TOP_CM = 2.5
MARGIN_BOTTOM_CM = 2.5
MARGIN_LEFT_CM = 3.2
MARGIN_RIGHT_CM = 3.2

# ── Paths ─────────────────────────────────────────────────────────────────────
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")
DOWNLOADS_DIR = os.path.expanduser("~/Downloads")

# Set FCC_DISABLE_DOWNLOADS_COPY=1 to skip the auto-copy of every output
# .docx/.pptx into ~/Downloads. Read once at import; no hot-reload needed.
DISABLE_DOWNLOADS_COPY = os.environ.get("FCC_DISABLE_DOWNLOADS_COPY", "").lower() in ("1", "true", "yes")

# ── Defaults ──────────────────────────────────────────────────────────────────
DEFAULT_INTERN_NAME = "Justin"
