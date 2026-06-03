"""
scripts/build_docx_cli.py — thin CLI wrapper around WordBuilder.

Skills feed this a JSON spec; it produces a .docx at output/<subdir>/
and (by default) copies to ~/Downloads, matching the existing
WordBuilder pipeline.

Usage:
    python3.13 scripts/build_docx_cli.py --spec /tmp/spec.json
    python3.13 scripts/build_docx_cli.py --spec -   # stdin

Spec shape:
{
  "title":       "Tesla 自動駕駛調查",          # required — appears as Para[0]
  "task_date":   "2026-05-27",                  # optional, default today
  "intern_name": "Justin" or ["Justin","Neil"], # optional
  "meta_text":   "...",                         # optional — overrides date/intern line
  "task_name":   "Tesla 自動駕駛調查",          # used to build filename via file_naming.general()
  "subdir":      "adhoc" | "daily" | "weekly",  # default 'adhoc'
  "filename":    "...docx",                     # optional — overrides file_naming.general()
  "sections": [                                 # ordered list of content blocks
      {"type": "heading",          "text": "..."},
      {"type": "paragraph",        "text": "...", "references": [...]?},
      {"type": "bullet",           "text": "...", "references": [...]?},
      {"type": "blank"},
      {"type": "table",            "headers": ["..."], "rows": [["..."]]},
      {"type": "red_heading",      "text": "..."},
      {"type": "red_heading_comment", "text": "...", "comment": "..."},
      {"type": "podcast_title",    "title": "...", "subtitle": "..."},
      {"type": "bracket_heading",  "text": "..."},
      {"type": "topic_heading",    "text": "..."},
      {"type": "keyed_paragraph",  "key": "...", "text": "..."},
      {"type": "keyed_info",       "key": "...", "text": "..."},
      {"type": "references",       "references": [{"num":1,"title":"...","url":"..."}]}
  ]
}

References format (used by paragraph/bullet citation hyperlinking and
the references section): list of {"num": int, "title": str, "url": str}.

Prints absolute path of saved .docx on success; exits 0.
On error: prints message to stderr; exits 1.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

# Make repo root importable when invoked as a script.
_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

from formatters.word_formatter import WordBuilder  # noqa: E402
from utils.file_naming import general as _fname    # noqa: E402
from utils.spec_io import load_spec, safe_subdir, safe_filename  # noqa: E402


_DISPATCH = {
    "heading":             lambda wb, b: wb.add_heading(b["text"]),
    "paragraph":           lambda wb, b: wb.add_paragraph(b["text"], b.get("references")),
    "bullet":              lambda wb, b: wb.add_bullet(b["text"], b.get("references")),
    "blank":               lambda wb, b: wb.add_blank_line(),
    "table":               lambda wb, b: wb.add_table(b["headers"], b["rows"]),
    "red_heading":         lambda wb, b: wb.add_red_heading(b["text"]),
    "red_heading_comment": lambda wb, b: wb.add_red_heading_with_comment(b["text"], b["comment"]),
    "podcast_title":       lambda wb, b: wb.add_red_underline_title_with_subtitle(
                                             b["title"], b.get("subtitle", "")),
    "bracket_heading":     lambda wb, b: wb.add_bracket_heading(b["text"]),
    "topic_heading":       lambda wb, b: wb.add_topic_heading(b["text"]),
    "keyed_paragraph":     lambda wb, b: wb.add_keyed_paragraph(b["key"], b["text"]),
    "keyed_info":          lambda wb, b: wb.add_keyed_info(b["key"], b["text"]),
    "references":          lambda wb, b: wb.add_references(b["references"]),
}


def _resolve_filename(spec: dict) -> str:
    if spec.get("filename"):
        return safe_filename(spec["filename"])
    task_name = spec.get("task_name") or spec["title"]
    return _fname(
        task_name=task_name,
        intern_name=spec.get("intern_name") or "Justin",
        task_date=spec.get("task_date") or date.today(),
    )


def build(spec: dict) -> Path:
    wb = WordBuilder(
        title=spec["title"],
        task_date=spec.get("task_date"),
        intern_name=spec.get("intern_name"),
        meta_text=spec.get("meta_text"),
    )

    for i, block in enumerate(spec.get("sections", [])):
        btype = block.get("type")
        handler = _DISPATCH.get(btype)
        if handler is None:
            raise ValueError(f"sections[{i}]: unknown type {btype!r}")
        handler(wb, block)

    return wb.save(
        filename=_resolve_filename(spec),
        subdir=safe_subdir(spec.get("subdir"), "adhoc"),
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="Build a FCC-format .docx from JSON spec.")
    ap.add_argument("--spec", required=True, help="Path to JSON spec, or '-' for stdin.")
    args = ap.parse_args()

    try:
        spec = load_spec(args.spec)
    except json.JSONDecodeError as e:
        print(f"ERROR: invalid JSON spec — {e}", file=sys.stderr)
        return 1

    try:
        path = build(spec)
    except (KeyError, ValueError, IndexError, TypeError) as e:
        print(f"ERROR: bad spec — {e}", file=sys.stderr)
        return 1

    print(str(path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
