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
from formatters.word_formatter import WordBuilder
from utils.file_naming import general
from utils.logger import AgentLogger
from utils.search import search

load_dotenv(override=True)


# ── State ─────────────────────────────────────────────────────────────────────

class PersonInfoState(TypedDict):
    task_instruction: str
    intern_name: Union[str, list[str]]
    task_date: str
    subdir: str
    mode: str
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

def parse_task(state: PersonInfoState) -> dict:
    """Generate targeted search queries for person research."""
    client = _get_client()

    prompt = f"""你是一個商業研究助理。根據以下任務指令，產生 3 到 5 個搜尋查詢（適合 Tavily），
目標是找到這個人的背景、現職、公司關聯與產業位置。

任務指令：{state['task_instruction']}

規則：
- 中文人名同時搜中文與英文拼音（如果知道）
- 若有提供公司名稱或職稱，每條 query 都要帶入，確保搜到正確的人
- 查詢方向涵蓋：工商登記（公司負責人）、現職/職稱、產業協會/公協會身份、新聞或公開資料
- 回傳純 JSON 陣列，不要多餘說明

格式範例：
["林振宏 大倡國際 董事長", "林振宏 台灣防火材料協會", "Ta-Chung International Lin Chen-hong chairman"]
"""

    message = client.messages.create(
        model=config.LLM_FAST,
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}],
    )

    from utils.cost_tracker import tracker
    tracker.record_claude(config.LLM_FAST, message.usage.input_tokens, message.usage.output_tokens)

    return {"search_queries": _parse_json(message.content[0].text)}


# ── Node 2: run_search ────────────────────────────────────────────────────────

_RESULTS_PER_QUERY = 3


def run_search(state: PersonInfoState) -> dict:
    from utils.cost_tracker import tracker
    all_results = []
    for query in state["search_queries"]:
        results = search(query, max_results=_RESULTS_PER_QUERY)
        tracker.record_tavily(1)
        all_results.append({"query": query, "results": results})
    return {"search_results": all_results}


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
4. 若搜尋資料不足，據實標注「資料不足，無法確認」，不要捏造
5. 語言：繁體中文，保留英文專有名詞與公司名；不要在任何名詞後加括號標注其他語言的原文或譯名（不論英文、越南文或其他語言），直接寫名稱本身
6. 不要在報告內容中提及任務指令的措辭、比喻或身份設定
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
    }}
  ]
}}
"""

    message = client.messages.create(
        model=config.LLM_MAIN,
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )

    from utils.cost_tracker import tracker
    tracker.record_claude(config.LLM_MAIN, message.usage.input_tokens, message.usage.output_tokens)

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
    graph.add_node("parse_task", parse_task)
    graph.add_node("run_search", run_search)
    graph.add_node("generate_report", generate_report)
    graph.add_node("format_output", format_output)

    graph.set_entry_point("parse_task")
    graph.add_edge("parse_task", "run_search")
    graph.add_edge("run_search", "generate_report")
    graph.add_edge("generate_report", "format_output")
    graph.add_edge("format_output", END)

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
