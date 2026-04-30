"""
agents/person_info_agent.py — Person research agent using LangGraph.

Flow:
    parse_task → run_search → generate_report → format_output

Output focuses on the person's affiliations (companies, associations),
roles, and industry positioning — not financial analysis.

Reference format: 2026.04.02_林振宏_Justin.docx
  - Heading per affiliated company/organisation
  - Under each: role, capital, positioning note
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
import utils.react_loop as react_loop
from formatters.word_formatter import WordBuilder
from utils.file_naming import general
from utils.logger import AgentLogger

load_dotenv(override=True)


# ── State ─────────────────────────────────────────────────────────────────────

class PersonInfoState(TypedDict):
    task_instruction: str
    intern_name: Union[str, list[str]]
    task_date: str
    subdir: str
    mode: str
    todos: list[dict]
    evidence: list[dict]
    round: int
    search_queries: list[str]
    search_results: list[dict]
    report: dict
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
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    text = text.strip()
    match = re.search(r"(\{[\s\S]*\}|\[[\s\S]*\])", text)
    if match:
        text = match.group(1)
    return json.loads(text)


# ── Node 1: parse_task ────────────────────────────────────────────────────────

_MAX_ROUNDS = 5


def parse_task(state: PersonInfoState) -> dict:
    """Build a research plan (todo list) and initial search queries for person research."""
    client = _get_client()

    prompt = f"""你是一個人物背景研究規劃師。根據以下任務指令，產出研究計劃。

任務指令：{state['task_instruction']}

輸出兩件事：
1. todos：這份人物報告需要確認的具體問題（3-5 個）
2. initial_queries：第一輪搜尋查詢（2-3 條，推論式設計）

搜尋設計原則（推論式）：
- 搜工商登記、公司官網、商業資料庫等一手來源，不要直接搜問題本身
- 中文人名同時用中文與英文拼音查（若知道）
- 若有提供公司名稱/職稱，每條 query 都帶入

回傳純 JSON：
{{
  "todos": [
    {{"id": 1, "question": "現任職稱與關聯公司？"}},
    {{"id": 2, "question": "各公司的資本額與持股結構？"}},
    {{"id": 3, "question": "產業協會或公協會身份？"}}
  ],
  "initial_queries": [
    "林志明 大倡國際 董事長 工商登記",
    "Ta-Chung International Lin Chih-ming chairman Taiwan"
  ]
}}
"""

    message = client.messages.create(
        model=config.LLM_FAST,
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )

    from utils.cost_tracker import tracker
    tracker.record_claude(config.LLM_FAST, message.usage.input_tokens, message.usage.output_tokens)

    parsed = _parse_json(message.content[0].text)
    raw_todos = parsed.get("todos", [])
    todos = [
        {"id": t["id"], "question": t["question"], "status": "pending", "attempts": 0}
        for t in raw_todos
    ]
    return {
        "todos":          todos,
        "evidence":       [],
        "round":          0,
        "search_queries": parsed.get("initial_queries", []),
        "search_results": [],
    }


# ── Node 2: run_search ────────────────────────────────────────────────────────

_PERSON_SEARCH_HINT = (
    "搜工商登記、商業資料庫、新聞、官方公告等一手來源；"
    "中文人名同時用中文與英文拼音查"
)


# ── ReAct loop nodes (thin wrappers over utils/react_loop) ───────────────────

def run_search(state: PersonInfoState) -> dict:
    return react_loop.run_initial_search(state)

def next_action(state: PersonInfoState) -> dict:
    return react_loop.next_action(state, max_rounds=_MAX_ROUNDS, search_hint=_PERSON_SEARCH_HINT)

def execute_search(state: PersonInfoState) -> dict:
    return react_loop.execute_search(state)

def evaluate(state: PersonInfoState) -> dict:
    return react_loop.evaluate(state)

def _should_continue(state: PersonInfoState) -> str:
    return react_loop.should_continue(state, max_rounds=_MAX_ROUNDS)


# ── Node 3: generate_report ───────────────────────────────────────────────────

def generate_report(state: PersonInfoState) -> dict:
    """Synthesize search results into a person profile structured by affiliation."""
    client = _get_client()

    context_parts = []
    for entry in state["search_results"]:
        context_parts.append(f"[搜尋：{entry['query']}]")
        for r in entry["results"]:
            context_parts.append(f"來源：{r['title']} ({r['url']})")
            context_parts.append(r["content"])
            context_parts.append("")
    context = "\n".join(context_parts)

    mode = state.get("mode", "short")
    if mode == "short":
        mode_rules = """\
6. 【Short 模式】嚴格依照任務指令範圍，不延伸、不補充任務未要求的背景
7. 報告精簡：最多 3 個 section，bullets 每個最多 6 條，paragraph 最多 150 字
8. 目標篇幅約兩頁，寧可少寫也不要湊字數"""
    else:
        mode_rules = """\
6. 【Medium 模式】可補充相關背景與延伸分析，section 數量不限，確保資訊完整"""

    prompt = f"""你是 FCC Partners 的商業研究助理。根據搜尋資料，針對以下任務產出一份繁體中文人物背景報告。

任務指令：{state['task_instruction']}

搜尋資料：
{context}

輸出規則：
1. 回傳純 JSON，不要 markdown 包裝
2. 報告以「這個人關聯的公司/組織」為核心結構，每個關聯組織作為一個 section
3. 每個 section 選擇最適合的呈現方式：
   - type "bullets"：條列式事實（職稱、資本額、董監事組成等）
   - type "paragraph"：定位說明或分析性描述
   - type "table"：多筆同結構比較資料（如：多家關聯公司的資本額/持股比例對照）
4. 若搜尋資料不足，據實標注「資料不足，無法確認」，不要捏造
5. 語言：繁體中文，保留英文專有名詞與公司名；不要在任何名詞後加括號標注其他語言的原文或譯名（不論英文、越南文或其他語言），直接寫名稱本身
6. 不要在報告內容中提及任務指令的措辭、比喻或身份設定
7. **絕對禁止免責聲明**：不得出現「僅供參考」「請以官方公告為準」「資料可能有誤」「本報告基於公開資料」「無法保證準確性」或任何類似的 hedge / disclaimer 語句，直接陳述事實即可
{mode_rules}

JSON 格式：
{{
  "title": "人名",
  "sections": [
    {{
      "heading": "公司或組織名稱",
      "type": "bullets",
      "items": ["職稱：董事長", "資本額：2.3億元[1]", "定位：..."]
    }},
    {{
      "heading": "另一個組織",
      "type": "paragraph",
      "content": "說明..."
    }},
    {{
      "heading": "關聯公司總覽",
      "type": "table",
      "headers": ["公司", "職稱", "資本額", "備註"],
      "rows": [["公司A", "董事長", "2.3億", "主要控股"]]
    }}
  ]
}}
"""

    synthesis_model = config.LLM_MAIN if mode == "medium" else config.LLM_SYNTHESIS
    message = client.messages.create(
        model=synthesis_model,
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )

    from utils.cost_tracker import tracker
    tracker.record_claude(synthesis_model, message.usage.input_tokens, message.usage.output_tokens)

    return {"report": _parse_json(message.content[0].text)}


# ── Node 4: format_output ─────────────────────────────────────────────────────

def format_output(state: PersonInfoState) -> dict:
    report = state["report"]
    intern = state["intern_name"]
    task_date = state.get("task_date") or date.today().strftime("%Y-%m-%d")
    subdir = state.get("subdir", "adhoc")

    builder = WordBuilder(report["title"], task_date, intern)
    for section in report.get("sections", []):
        builder.add_heading(section["heading"])
        if section["type"] == "bullets":
            for item in section.get("items", []):
                builder.add_bullet(item)
        elif section["type"] == "table":
            builder.add_table(section.get("headers", []), section.get("rows", []))
        else:
            builder.add_paragraph(section.get("content", ""))
        builder.add_blank_line()

    dot_date = task_date.replace("-", ".")
    filename = general(report["title"], intern, dot_date)
    output_path = builder.save(filename, subdir=subdir)

    logger = AgentLogger("person_info_agent", state["task_instruction"], intern)
    logger.set_queries(state["search_queries"])
    for entry in state["search_results"]:
        logger.add_search_result(entry["query"], entry["results"])
    log_path = logger.save(output_path)

    return {"output_path": str(output_path), "log_path": str(log_path)}


# ── Graph ─────────────────────────────────────────────────────────────────────

def build_graph():
    graph = StateGraph(PersonInfoState)
    graph.add_node("parse_task",     parse_task)
    graph.add_node("run_search",     run_search)
    graph.add_node("evaluate",       evaluate)
    graph.add_node("next_action",    next_action)
    graph.add_node("execute_search", execute_search)
    graph.add_node("generate_report", generate_report)
    graph.add_node("format_output",  format_output)

    graph.set_entry_point("parse_task")
    graph.add_edge("parse_task",  "run_search")
    graph.add_edge("run_search",  "evaluate")
    graph.add_conditional_edges(
        "evaluate",
        _should_continue,
        {"loop": "next_action", "done": "generate_report"},
    )
    graph.add_edge("next_action",    "execute_search")
    graph.add_edge("execute_search", "evaluate")
    graph.add_edge("generate_report", "format_output")
    graph.add_edge("format_output",  END)

    return graph.compile()


# ── Public entry point ────────────────────────────────────────────────────────

def run(
    task_instruction: str,
    intern_name: Union[str, list[str]] = None,
    task_date: str = None,
    subdir: str = "adhoc",
    mode: str = "short",
) -> dict:
    app = build_graph()

    final_state = app.invoke({
        "task_instruction": task_instruction,
        "intern_name": intern_name or config.DEFAULT_INTERN_NAME,
        "task_date": task_date or date.today().strftime("%Y-%m-%d"),
        "subdir": subdir,
        "mode": mode,
        "todos":          [],
        "evidence":       [],
        "round":          0,
        "search_queries": [],
        "search_results": [],
        "report": {},
        "output_path": "",
        "log_path": "",
    })

    return {
        "output_path": final_state["output_path"],
        "log_path":    final_state["log_path"],
    }


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    from utils.planner import confirm, parse_tasks

    parser = argparse.ArgumentParser(description="Person info research agent")
    parser.add_argument("--task",   required=True)
    parser.add_argument("--intern", default=None)
    parser.add_argument("--date",   default=None)
    parser.add_argument("--subdir", default="adhoc", choices=["daily", "weekly", "adhoc"])
    parser.add_argument("--yes",    action="store_true", help="Skip confirmation prompt")
    args = parser.parse_args()

    intern = [n.strip() for n in args.intern.split(",")] if args.intern and "," in args.intern else args.intern

    print("正在解析任務...")
    tasks = parse_tasks(args.task, force_type="person_info")
    confirmed = tasks if args.yes else confirm(tasks)

    if not confirmed:
        exit(0)

    for task in confirmed:
        print(f"\n▶ 執行：{task.label}")
        result = run(
            task_instruction=task.instruction,
            intern_name=intern,
            task_date=args.date,
            subdir=args.subdir,
        )
        print(f"  Output: {result['output_path']}")
        print(f"  Log:    {result['log_path']}")
