"""
agents/verbal_cleanup_agent.py — Verbal dictation cleanup agent using LangGraph.

Flow:
    maybe_transcribe → cleanup_text → format_output

Input:
  - text:  raw dictation transcript
  - audio: path to .m4a / .mp3 / .wav (triggers STT first)

Purpose:
  Remove opening pleasantries, filler words, and verbal noise from dictated
  content. The output is clean, publication-ready prose that preserves the
  original intent without the spoken-word artefacts.

Output: Word doc with cleaned prose paragraphs.
Filename: YYYY.MM.DD_[title]_InternName.docx
"""
import json
import os
import sys
from datetime import date
from pathlib import Path
from typing import TypedDict, Union

from anthropic import Anthropic
from dotenv import load_dotenv
from langgraph.graph import END, StateGraph

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config
from formatters.word_formatter import WordBuilder
from utils.file_naming import general
from utils.logger import AgentLogger

load_dotenv(override=True)


# ── State ─────────────────────────────────────────────────────────────────────

class VerbalCleanupState(TypedDict):
    raw_text: str
    audio_path: str
    intern_name: Union[str, list[str]]
    task_date: str
    subdir: str
    mode: str
    cleaned: dict       # {title, sections: [{heading?, paragraphs: [str]}]}
    output_path: str
    log_path: str


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_client() -> Anthropic:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise EnvironmentError("ANTHROPIC_API_KEY not set in .env")
    return Anthropic(api_key=api_key)


def _parse_json(text: str):
    import re
    original = text
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    text = text.strip()
    match = re.search(r"(\{[\s\S]*\}|\[[\s\S]*\])", text)
    if match:
        text = match.group(1)
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        print(f"\n[DEBUG] JSON parse failed: {e}")
        print(f"[DEBUG] Raw LLM response:\n{original[:2000]}")
        raise


def _intern_str(intern_name) -> str:
    if isinstance(intern_name, list):
        return ", ".join(intern_name)
    return intern_name or config.DEFAULT_INTERN_NAME


# ── Node 1: maybe_transcribe ──────────────────────────────────────────────────

def maybe_transcribe(state: VerbalCleanupState) -> dict:
    """If audio_path is set, run STT then let the user review and correct before cleanup."""
    if not state.get("audio_path"):
        return {}
    from utils.stt import transcribe
    print(f"  STT: transcribing {state['audio_path']} ...")
    text = transcribe(state["audio_path"])
    print(f"  STT: done ({len(text)} chars)\n")

    print("─" * 70)
    print(text)
    print("─" * 70)
    print("直接按 Enter 繼續清稿，或貼上修正後的文字再按 Enter：")
    user_input = input("> ").strip()
    if user_input:
        text = user_input

    return {"raw_text": text}


# ── Node 2: cleanup_text ──────────────────────────────────────────────────────

def cleanup_text(state: VerbalCleanupState) -> dict:
    client = _get_client()

    prompt = f"""你是 FCC Partners 的助理，負責將口述錄音的文字稿清稿成乾淨的繁體中文書面稿。

以下是口述內容（可能是 Whisper 語音轉文字，語氣口語，含廢話）：
{state['raw_text']}

請執行以下清稿工作：
1. 刪除開頭語（如「嗯好那個」「哈囉大家好」「好，今天我想說的是」等）
2. 刪除句中的語氣助詞與廢話（如「那個」「就是說」「嗯」「啊」「like」「you know」「對不對」等）
3. 合併斷裂的句子，修正因口語習慣造成的語序混亂
4. 保留說話者的原意、資訊與語氣（不要添加或改變內容）
5. 使用與原文相同的語言（中文口述 → 繁體中文；英文口述 → 英文；混合 → 繁體中文為主）

輸出格式：純 JSON，不要 markdown 包裝：

{{
  "title": "內容主題簡短標籤（10 字以內，不含日期）",
  "sections": [
    {{
      "heading": "段落標題（若內容有明顯主題分段則填；若整體是一段連續內容則留空字串）",
      "paragraphs": [
        "清稿後的第一段...",
        "清稿後的第二段..."
      ]
    }}
  ]
}}

規則：
- sections 至少一個；若內容單一不需分段，heading 留空字串，paragraphs 放所有段落
- 每個 paragraph 為完整一段，不要在一個字串內塞多段（用多個 paragraph 元素分段）
- 不要在任何名詞後加括號標注原文或譯名
- 不要提及「清稿」「刪除廢話」等 meta 資訊
"""

    message = client.messages.create(
        model=config.LLM_MAIN,
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )

    from utils.cost_tracker import tracker
    tracker.record_claude(config.LLM_MAIN, message.usage.input_tokens, message.usage.output_tokens)

    raw = next((b.text for b in message.content if hasattr(b, "text")), "")
    return {"cleaned": _parse_json(raw)}


# ── Node 3: format_output ─────────────────────────────────────────────────────

def format_output(state: VerbalCleanupState) -> dict:
    cleaned = state["cleaned"]
    intern = state["intern_name"]
    task_date = state.get("task_date") or date.today().strftime("%Y-%m-%d")
    subdir = state.get("subdir", "adhoc")

    title = cleaned.get("title", "口述清稿")
    intern_str = _intern_str(intern)

    builder = WordBuilder(title, task_date=task_date, intern_name=intern_str)

    for section in cleaned.get("sections", []):
        heading = section.get("heading", "")
        if heading:
            builder.add_heading(heading)
        for para in section.get("paragraphs", []):
            builder.add_paragraph(para)

    dot_date = task_date.replace("-", ".")
    filename = general(title, intern, dot_date)
    output_path = builder.save(filename, subdir=subdir)

    source = state.get("audio_path") or "text input"
    logger = AgentLogger("verbal_cleanup_agent", f"verbal cleanup [{title}] from: {source}", intern)
    log_path = logger.save(output_path)

    return {"output_path": str(output_path), "log_path": str(log_path)}


# ── Graph ─────────────────────────────────────────────────────────────────────

def build_graph():
    graph = StateGraph(VerbalCleanupState)
    graph.add_node("maybe_transcribe", maybe_transcribe)
    graph.add_node("cleanup_text", cleanup_text)
    graph.add_node("format_output", format_output)

    graph.set_entry_point("maybe_transcribe")
    graph.add_edge("maybe_transcribe", "cleanup_text")
    graph.add_edge("cleanup_text", "format_output")
    graph.add_edge("format_output", END)

    return graph.compile()


# ── Public entry point ────────────────────────────────────────────────────────

def run(
    raw_text: str = None,
    audio_path: str = None,
    intern_name: Union[str, list[str]] = None,
    task_date: str = None,
    subdir: str = "adhoc",
    task_instruction: str = None,  # router compat: treated as raw_text
    mode: str = "short",           # router compat: not used here
) -> dict:
    if not raw_text and not audio_path:
        raw_text = task_instruction or ""

    app = build_graph()

    final_state = app.invoke({
        "raw_text":    raw_text or "",
        "audio_path":  audio_path or "",
        "intern_name": intern_name or config.DEFAULT_INTERN_NAME,
        "task_date":   task_date or date.today().strftime("%Y-%m-%d"),
        "subdir":      subdir,
        "mode":        mode,
        "cleaned":     {},
        "output_path": "",
        "log_path":    "",
    })

    return {
        "output_path": final_state["output_path"],
        "log_path":    final_state["log_path"],
    }


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Verbal cleanup agent — remove filler words from dictation")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--text",      help="Raw transcript text (inline)")
    group.add_argument("--text-file", dest="text_file",
                       help="Path to .txt file containing the transcript")
    group.add_argument("--audio",     help="Path to audio file (.m4a, .mp3, .wav)")
    parser.add_argument("--intern",  default=None)
    parser.add_argument("--date",    default=None)
    parser.add_argument("--subdir",  default="adhoc", choices=["daily", "weekly", "adhoc"])
    args = parser.parse_args()

    if args.audio:
        raw_text, audio_path = None, args.audio
    elif args.text_file:
        raw_text = Path(args.text_file).read_text(encoding="utf-8")
        audio_path = None
    else:
        raw_text, audio_path = args.text, None

    intern = (
        [n.strip() for n in args.intern.split(",")]
        if args.intern and "," in args.intern
        else args.intern
    )

    print("清稿中...")
    result = run(
        raw_text=raw_text,
        audio_path=audio_path,
        intern_name=intern,
        task_date=args.date,
        subdir=args.subdir,
    )
    print(f"  Output: {result['output_path']}")
    print(f"  Log:    {result['log_path']}")

    from utils.cost_tracker import tracker
    tracker.print_task_summary()
