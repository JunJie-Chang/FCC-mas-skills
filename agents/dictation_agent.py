"""
agents/dictation_agent.py — Meeting minutes agent using LangGraph.

Flow:
    maybe_transcribe → generate_minutes → format_output

Input:
  - text:  raw dictation / transcript text
  - audio: path to .m4a / .mp3 / .wav (triggers STT first)

Output: Word doc matching Works/2026.03.26_Curiosity Lab_Justin.docx format:
  Title:   YYYY/MM/DD [Name]會議紀錄  (Bold, date embedded)
  ─────────────────────────────────────
  Date & Time: ...
  Venue: ...
  Attendees: Org｜Name1, Name2
  Recorder: InternName
  (blank)
  【Meeting Executive Summary】
  paragraph...
  【Meeting Discussion Points】
  Topic Heading
    Term: explanation
    ...
  【Action Items】
  Group Name:
    Label: action text
    ...

Filename: YYYY.MM.DD_[Name]會議紀錄_InternName.docx
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

class DictationState(TypedDict):
    raw_text: str
    audio_path: str
    intern_name: Union[str, list[str]]
    task_date: str
    subdir: str
    # optional overrides — if set, these replace whatever the LLM parsed
    override_attendees: str   # raw string, e.g. "FCC｜CY, Justin; Curiosity Lab｜Seth"
    override_recorder: str    # e.g. "Justin Chang"
    minutes: dict
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

def maybe_transcribe(state: DictationState) -> dict:
    """If audio_path is set, run STT and store result in raw_text."""
    if not state.get("audio_path"):
        return {}
    from utils.stt import transcribe
    print(f"  STT: transcribing {state['audio_path']} ...")
    text = transcribe(state["audio_path"])
    print(f"  STT: done ({len(text)} chars)")
    return {"raw_text": text}


# ── Node 2: generate_minutes ──────────────────────────────────────────────────

def generate_minutes(state: DictationState) -> dict:
    client = _get_client()

    prompt = f"""你是 FCC Partners 的助理，負責將會議口述稿整理成正式繁體中文會議記錄。

以下是會議口述內容（可能是錄音轉文字，語氣較口語）：
{state['raw_text']}

請整理成以下 JSON 結構，回傳純 JSON，不要 markdown 包裝：

{{
  "title": "會議簡短名稱（不含日期，10 字以內，例如 Curiosity Lab）",
  "info": {{
    "datetime": "日期與時間（若有提及，格式如 Wednesday, March 26, 2026 | 08:30 – 09:00；若無則留空）",
    "venue": "會議地點（若有提及；若無則留空）",
    "attendees": [
      {{"org": "公司或組織名稱", "names": ["出席者1", "出席者2"]}}
    ],
    "recorder": "記錄者姓名（若無明確提及則留空）"
  }},
  "summary": [
    "Executive Summary 第一段",
    "Executive Summary 第二段"
  ],
  "discussion": [
    {{
      "heading": "議題大標題（例如 Strategic Positioning）",
      "points": [
        {{"term": "關鍵詞或子議題名稱", "text": "說明內容"}},
        {{"term": "另一子議題", "text": "說明內容"}}
      ]
    }}
  ],
  "action_groups": [
    {{
      "group": "負責方名稱（例如 FCC's Action Items）",
      "items": [
        {{"label": "行動項目標題", "text": "具體說明"}},
        {{"label": "另一項目", "text": "說明"}}
      ]
    }}
  ]
}}

規則：
- 語言：使用與口述相同的語言（中文口述 → 繁體中文；英文口述 → 英文）
- info 欄位若未提及則留空字串或空陣列，不要捏造
- summary：2-4 段，提煉核心內容
- discussion：依議題分組，每組有 heading + 若干 points
- action_groups：若無待辦事項，回傳空陣列
- attendees：若無法辨識組織，org 留空字串
"""

    message = client.messages.create(
        model=config.LLM_MAIN,
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )

    from utils.cost_tracker import tracker
    tracker.record_claude(config.LLM_MAIN, message.usage.input_tokens, message.usage.output_tokens)

    raw = next((b.text for b in message.content if hasattr(b, "text")), "")
    return {"minutes": _parse_json(raw)}


# ── Node 3: format_output ─────────────────────────────────────────────────────

def format_output(state: DictationState) -> dict:
    minutes = state["minutes"]
    intern = state["intern_name"]
    task_date = state.get("task_date") or date.today().strftime("%Y-%m-%d")
    subdir = state.get("subdir", "adhoc")

    meeting_name = minutes.get("title", "會議記錄")
    intern_str = _intern_str(intern)

    # Title: YYYY/MM/DD [Name]會議紀錄  (slashes, date embedded in title)
    slash_date = task_date.replace("-", "/")
    full_title = f"{slash_date} {meeting_name}會議紀錄"

    # Skip standard meta line (date is embedded in title; recorder in info block)
    builder = WordBuilder(full_title, task_date=None, intern_name=None)
    builder.add_blank_line()

    # Info block
    info = minutes.get("info", {})
    if info.get("datetime"):
        builder.add_keyed_info("Date & Time", info["datetime"])
    if info.get("venue"):
        builder.add_keyed_info("Venue", info["venue"])

    # Attendees: use override if provided, else use LLM-parsed result
    override_att = state.get("override_attendees", "")
    if override_att:
        # Format: "Org1｜Name1, Name2; Org2｜Name3"  or just "Name1, Name2"
        for group in override_att.split(";"):
            group = group.strip()
            if not group:
                continue
            if "｜" in group:
                org, names = group.split("｜", 1)
                builder.add_keyed_info(org.strip(), names.strip())
            else:
                builder.add_keyed_info("Attendees", group)
    else:
        for att in info.get("attendees", []):
            names_str = ", ".join(att.get("names", []))
            if att.get("org"):
                builder.add_keyed_info(att["org"], names_str)
            elif names_str:
                builder.add_keyed_info("Attendees", names_str)

    # Recorder: use override if provided, else LLM-parsed, else intern name
    recorder = state.get("override_recorder", "") or info.get("recorder") or intern_str
    if recorder:
        builder.add_keyed_info("Recorder", recorder)

    builder.add_blank_line()

    # Executive Summary
    summary = minutes.get("summary", [])
    if summary:
        builder.add_bracket_heading("Meeting Executive Summary")
        for para in summary:
            builder.add_paragraph(para)

    # Discussion Points
    discussion = minutes.get("discussion", [])
    if discussion:
        builder.add_bracket_heading("Meeting Discussion Points")
        for section in discussion:
            builder.add_topic_heading(section["heading"])
            for point in section.get("points", []):
                builder.add_keyed_paragraph(point["term"], point["text"])

    # Action Items
    action_groups = minutes.get("action_groups", [])
    if action_groups:
        builder.add_bracket_heading("Action Items")
        for group in action_groups:
            builder.add_heading(group["group"] + ":")
            for item in group.get("items", []):
                builder.add_keyed_paragraph(item["label"], item["text"])

    dot_date = task_date.replace("-", ".")
    filename = general(f"{meeting_name}會議紀錄", intern, dot_date)
    output_path = builder.save(filename, subdir=subdir)

    source = state.get("audio_path") or "text input"
    logger = AgentLogger("dictation_agent", f"meeting minutes [{meeting_name}] from: {source}", intern)
    log_path = logger.save(output_path)

    return {"output_path": str(output_path), "log_path": str(log_path)}


# ── Graph ─────────────────────────────────────────────────────────────────────

def build_graph():
    graph = StateGraph(DictationState)
    graph.add_node("maybe_transcribe", maybe_transcribe)
    graph.add_node("generate_minutes", generate_minutes)
    graph.add_node("format_output", format_output)

    graph.set_entry_point("maybe_transcribe")
    graph.add_edge("maybe_transcribe", "generate_minutes")
    graph.add_edge("generate_minutes", "format_output")
    graph.add_edge("format_output", END)

    return graph.compile()


# ── Public entry point ────────────────────────────────────────────────────────

def run(
    raw_text: str = None,
    audio_path: str = None,
    intern_name: Union[str, list[str]] = None,
    task_date: str = None,
    subdir: str = "adhoc",
    override_attendees: str = "",
    override_recorder: str = "",
    task_instruction: str = None,  # router compat: treated as raw_text
    mode: str = "short",           # router compat: not used in dictation
) -> dict:
    if not raw_text and not audio_path:
        raw_text = task_instruction or ""

    app = build_graph()

    final_state = app.invoke({
        "raw_text":           raw_text or "",
        "audio_path":         audio_path or "",
        "intern_name":        intern_name or config.DEFAULT_INTERN_NAME,
        "task_date":          task_date or date.today().strftime("%Y-%m-%d"),
        "subdir":             subdir,
        "override_attendees": override_attendees,
        "override_recorder":  override_recorder,
        "minutes":            {},
        "output_path":        "",
        "log_path":           "",
    })

    return {
        "output_path": final_state["output_path"],
        "log_path":    final_state["log_path"],
    }


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Dictation agent — meeting minutes")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--text",      help="Raw transcript text (inline)")
    group.add_argument("--text-file", dest="text_file",
                       help="Path to .txt file containing the transcript")
    group.add_argument("--audio",     help="Path to audio file (.m4a, .mp3, .wav)")
    parser.add_argument("--intern",     default=None)
    parser.add_argument("--date",       default=None)
    parser.add_argument("--subdir",     default="adhoc", choices=["daily", "weekly", "adhoc"])
    parser.add_argument("--attendees",  default="",
                        help='出席者，格式："Org1｜Name1, Name2; Org2｜Name3" 或 "Name1, Name2"')
    parser.add_argument("--recorder",   default="",
                        help='記錄者姓名，例如 "Justin Chang"')
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

    print("整理會議記錄中...")
    result = run(
        raw_text=raw_text,
        audio_path=audio_path,
        intern_name=intern,
        task_date=args.date,
        subdir=args.subdir,
        override_attendees=args.attendees,
        override_recorder=args.recorder,
    )
    print(f"  Output: {result['output_path']}")
    print(f"  Log:    {result['log_path']}")
