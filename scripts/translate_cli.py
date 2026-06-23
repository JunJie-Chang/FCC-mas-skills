"""
scripts/translate_cli.py — token-cheap translation path for fcc-translation.

The fcc-translation skill calls this FIRST. When ANTHROPIC_API_KEY is set, the
whole article is translated in a single Haiku call and rendered to a .docx via
the existing build_docx_cli pipeline — far cheaper than translating
paragraph-by-paragraph inside the (Opus) Claude Code session.

Fallback contract (read by SKILL.md):
    exit 0  → translation done; the saved .docx path is printed on stdout.
    exit 3  → ANTHROPIC_API_KEY not set/empty; the skill should translate
              in-session instead (the token-heavy path).
    exit 1  → the script failed (bad JSON from the model, etc.); the skill
              should also fall back, noting the script error.

Input gathering (OCR of images/PDF, URL fetch) stays in the skill/session —
this script only takes already-extracted body text. So it deliberately does
NOT depend on utils/ocr.py, logger, progress, or langgraph.

Usage:
    python3 scripts/translate_cli.py \
        --title "..." --source WSJ \
        --body-file /tmp/body.txt \
        --pub-date 2026-05-15 --date 2026-05-27 --intern Justin
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

# Re-exec under the repo venv ($FCC_MAS_HOME/.venv) when launched with a bare
# python3. Must run before any third-party import. See utils/venv_bootstrap.
from utils.venv_bootstrap import activate as _activate_venv  # noqa: E402

_activate_venv(_REPO)

import config  # noqa: E402
from scripts.build_docx_cli import build  # noqa: E402

# Exit code the skill watches for to trigger the in-session fallback.
EXIT_NO_KEY = 3


def _get_api_key() -> str:
    """Return a non-empty ANTHROPIC_API_KEY, or '' if unset/blank.

    load_dotenv uses override=True because a blank ANTHROPIC_API_KEY already
    exported in the shell would otherwise shadow the value in .env (the same
    trap documented in CLAUDE.md).
    """
    try:
        from dotenv import load_dotenv
        load_dotenv(_REPO / ".env", override=True)
    except Exception:
        pass
    return os.getenv("ANTHROPIC_API_KEY", "").strip()


def _parse_json(text: str):
    original = text
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text).strip()
    match = re.search(r"(\{[\s\S]*\}|\[[\s\S]*\])", text)
    if match:
        text = match.group(1)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        print(f"ERROR: model did not return valid JSON. Raw:\n{original[:1500]}",
              file=sys.stderr)
        raise


def _build_prompt(title: str, source: str, body_text: str) -> str:
    return f"""你是一位專業的繁體中文翻譯，服務於香港金融顧問公司。
請將以下文章逐段翻譯成繁體中文：
   - 保留原文段落結構（原文一段對應一個 JSON 元素，不合併也不拆開）
   - 公司／機構／產品名保留原文（Tesla、Apple、iPhone），不加括號中譯
   - 人名第一次出現用「譯名（原文）」，如「川普（Trump）」「黃仁勳（Jensen Huang）」；之後只用譯名
   - 數字單位用繁中金融慣例：$9.4 billion → 「94 億美元」（不是 9.4 億；billion 對應「億」差 10 倍）
   - 語氣自然流暢，符合繁體中文書面語；不要逐字直譯
   - 不要加任何「譯註」「以下為翻譯」之類的 meta 文字
   - 不省略段落、不總結、不重排

翻完後自我檢查一次：譯文段落數是否等於原文段落數？金額單位是否正確（billion↔億）？
人名第一次出現是否附原文？發現問題就修正後再回傳。

標題：{title}
來源：{source}

原文：
{body_text}

回傳純 JSON，不要 markdown 包裝，格式如下：
{{
  "body": [
    "第一段翻譯",
    "第二段翻譯"
  ]
}}"""


def translate(title: str, source: str, body_text: str) -> list[str]:
    from anthropic import Anthropic

    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    message = client.messages.create(
        model=config.LLM_FAST,
        max_tokens=8192,
        messages=[{"role": "user", "content": _build_prompt(title, source, body_text)}],
    )

    try:
        from utils.cost_tracker import tracker
        tracker.record_claude(config.LLM_FAST,
                              message.usage.input_tokens,
                              message.usage.output_tokens)
    except Exception:
        tracker = None

    raw = next((b.text for b in message.content if hasattr(b, "text")), "")
    parsed = _parse_json(raw)
    body = parsed.get("body", []) if isinstance(parsed, dict) else parsed
    if not body:
        raise ValueError("translation returned an empty body")
    return body


def main() -> int:
    ap = argparse.ArgumentParser(description="Translate an article to Traditional Chinese (Haiku path).")
    ap.add_argument("--title", required=True)
    ap.add_argument("--source", required=True)
    ap.add_argument("--body", default=None, help="Article body inline.")
    ap.add_argument("--body-file", dest="body_file", default=None,
                    help="Path to a UTF-8 text file with the article body.")
    ap.add_argument("--pub-date", dest="pub_date", default="", help="Publication date YYYY-MM-DD.")
    ap.add_argument("--date", dest="task_date", default=None, help="Work date YYYY-MM-DD (default today).")
    ap.add_argument("--intern", default=config.DEFAULT_INTERN_NAME)
    ap.add_argument("--subdir", default="daily", choices=["daily", "weekly", "adhoc"])
    args = ap.parse_args()

    if not _get_api_key():
        print("ANTHROPIC_API_KEY not set — fall back to in-session translation.",
              file=sys.stderr)
        return EXIT_NO_KEY

    if args.body_file:
        body_text = Path(args.body_file).read_text(encoding="utf-8").strip()
    elif args.body:
        body_text = args.body.strip()
    else:
        ap.error("provide --body <text> or --body-file <path>")
    if not body_text:
        print("ERROR: empty body text.", file=sys.stderr)
        return 1

    intern = ([n.strip() for n in args.intern.split(",")]
              if "," in args.intern else args.intern)
    task_date = args.task_date or date.today().strftime("%Y-%m-%d")
    intern_str = ", ".join(intern) if isinstance(intern, list) else intern

    try:
        paragraphs = translate(args.title, args.source, body_text)
    except Exception as e:
        print(f"ERROR: translation failed — {e}", file=sys.stderr)
        return 1

    # Two-line meta header: pub_date_source / task_date_intern (matches SKILL.md Step 4).
    meta_line1 = f"{args.pub_date}_{args.source}" if args.pub_date else args.source
    meta_text = f"{meta_line1}\n{task_date}_{intern_str}"

    spec = {
        "title": args.title,
        "meta_text": meta_text,
        "intern_name": intern,
        "task_date": task_date,
        "task_name": f"{args.title}_{args.source}",
        "subdir": args.subdir,
        "sections": [{"type": "blank"}]
                    + [{"type": "paragraph", "text": p} for p in paragraphs],
    }

    try:
        out_path = build(spec)
    except Exception as e:
        print(f"ERROR: docx build failed — {e}", file=sys.stderr)
        return 1

    print(str(out_path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
