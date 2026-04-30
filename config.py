"""
config.py — Format settings and paths only.
API keys are in .env (loaded via python-dotenv in each module that needs them).
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

# ── LLM models ────────────────────────────────────────────────────────────────
LLM_MAIN      = "claude-opus-4-6"               # medium mode / complex synthesis
LLM_SYNTHESIS = "claude-sonnet-4-6"             # short mode synthesis (lower cost)
LLM_FAST      = "claude-haiku-4-5-20251001"     # classification / query gen / eval

# ── Paths ─────────────────────────────────────────────────────────────────────
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")
DOWNLOADS_DIR = os.path.expanduser("~/Downloads")

# ── Defaults ──────────────────────────────────────────────────────────────────
DEFAULT_INTERN_NAME = "Justin"
