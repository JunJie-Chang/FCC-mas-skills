"""
agents/company_info_agent.py — Company research agent using LangGraph.

Flow:
    parse_task → run_search → generate_report → format_output

Key design principle: schema is NOT hardcoded.
Claude decides what sections to include and whether each section is a
bullet list or a prose paragraph, based solely on the task instruction.

Output: .docx saved to output/ + auto-copied to ~/Downloads
        .log  saved alongside the .docx (sources for fact-checking)
"""
import json
import os
import sys
from datetime import date
from pathlib import Path
from typing import Annotated, TypedDict, Union

from anthropic import Anthropic
from dotenv import load_dotenv
from langgraph.graph import END, StateGraph

# Allow running from project root
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config
from formatters.word_formatter import WordBuilder
from utils.file_naming import general
from utils.logger import AgentLogger
from utils.search import fetch_full_content, search

load_dotenv(override=True)


# ── State ─────────────────────────────────────────────────────────────────────

class CompanyInfoState(TypedDict):
    task_instruction: str
    intern_name: Union[str, list[str]]
    task_date: str                         # YYYY-MM-DD
    subdir: str                            # output subfolder: daily / weekly / adhoc
    mode: str                              # "short" | "medium"
    search_queries: list[str]
    search_results: list[dict]             # [{query, results:[{title,url,content,score}]}]
    financial_check: dict                  # {"q1": "Y"|"N", "q2": [tool_ids] | []}
    financial_data: dict                   # {"ticker": str, tool_id: data_dict, ...}
    report: dict                           # {title, sections:[{heading,type,items|content}]}
    output_path: str
    log_path: str


# ── LLM client ────────────────────────────────────────────────────────────────

def _get_client() -> Anthropic:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise EnvironmentError("ANTHROPIC_API_KEY not set in .env")
    return Anthropic(api_key=api_key)


# ── JSON parsing helper ───────────────────────────────────────────────────────

def _parse_json(text: str):
    """
    Extract and parse a JSON object or array from LLM output.
    Handles markdown code fences and leading/trailing prose.
    """
    import re
    text = text.strip()
    # Strip ```json ... ``` or ``` ... ```
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    text = text.strip()
    # Find the outermost JSON structure
    match = re.search(r"(\{[\s\S]*\}|\[[\s\S]*\])", text)
    if match:
        text = match.group(1)
    return json.loads(text)


# ── Node 1: parse_task ────────────────────────────────────────────────────────

def parse_task(state: CompanyInfoState) -> dict:
    """
    Use claude-haiku to read the task instruction and generate
    3-5 targeted Tavily search queries.
    """
    client = _get_client()

    prompt = f"""你是一個商業研究助理。根據以下任務指令，產生 3 到 5 個英文搜尋查詢（適合 Tavily），
目標是找到完成這份報告所需的資訊。

任務指令：{state['task_instruction']}

規則：
- 查詢語言用英文（搜尋效果更好）
- 若任務指令有提供股票代碼（如 3017.TW、002837.SZ），每一條 query 都必須帶入該代碼，確保搜到正確公司
- 每個查詢聚焦在不同面向（財務、業務、競爭等），不要重複
- 回傳純 JSON 陣列，不要多餘說明

格式範例：
["002837.SZ Envicool data center thermal management revenue", "002837.SZ Envicool liquid cooling business growth", "Shenzhen Envicool Technology competitive advantages IDC"]
"""

    message = client.messages.create(
        model=config.LLM_FAST,
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}],
    )

    from utils.cost_tracker import tracker
    tracker.record_claude(config.LLM_FAST, message.usage.input_tokens, message.usage.output_tokens)

    queries = _parse_json(message.content[0].text)

    return {"search_queries": queries}


# ── Node 1b: check_financial_need ────────────────────────────────────────────

def check_financial_need(state: CompanyInfoState) -> dict:
    """
    Use Haiku to classify whether the task needs financial market data.
    Q1: Does the task subject include a listed company? (Y/N)
    Q2: Which financial tools are needed? (subset of TOOL_REGISTRY keys, or [])
    Both must be Y/non-empty to trigger fetch_financial_data.
    """
    from utils.financial_tools import TOOL_DESCRIPTIONS

    tool_menu = "\n".join(
        f'- "{tid}": {desc}' for tid, desc in TOOL_DESCRIPTIONS.items()
    )

    prompt = f"""你是一個任務分析助理。根據以下任務指令，回答兩個問題。

任務指令：{state['task_instruction']}

可用財務資料工具：
{tool_menu}

回答規則：
- Q1：任務對象是否包含上市櫃公司（股票市場中可查到的公司）？回答 "Y" 或 "N"
- Q2：任務是否需要財務市場資料？若是，從工具清單中選出需要的 id（可複選）；若否或 Q1=N，回答空陣列
- company_name：若 Q1=Y，填入最適合用來搜尋 ticker 的公司名稱（優先用英文，例如 "Tesla" 而非 "特斯拉"）；Q1=N 則填空字串
- 只在任務明確需要財務數據時才選工具；一般公司介紹、業務研究不需要
- 回傳純 JSON，不要多餘說明

格式：
{{"q1": "Y", "company_name": "Tesla", "q2": ["stock_price", "key_metrics"]}}
或
{{"q1": "N", "company_name": "", "q2": []}}
"""

    client = _get_client()
    message = client.messages.create(
        model=config.LLM_FAST,
        max_tokens=200,
        messages=[{"role": "user", "content": prompt}],
    )

    from utils.cost_tracker import tracker
    tracker.record_claude(config.LLM_FAST, message.usage.input_tokens, message.usage.output_tokens)

    try:
        check = _parse_json(message.content[0].text)
        if not isinstance(check.get("q2"), list):
            check["q2"] = []
        if "company_name" not in check:
            check["company_name"] = ""
    except Exception:
        check = {"q1": "N", "company_name": "", "q2": []}

    return {"financial_check": check}


# ── Node 1c: fetch_financial_data ─────────────────────────────────────────────

def fetch_financial_data(state: CompanyInfoState) -> dict:
    """
    Resolve ticker and fetch financial data for requested tools.
    Skipped entirely (via conditional edge) when Q1=N or Q2=[].
    Returns empty dict on ticker resolution failure so the graph continues.
    """
    from utils.financial_tools import fetch_all, resolve_ticker

    tools = state["financial_check"].get("q2", [])
    company_name = state["financial_check"].get("company_name") or state["task_instruction"][:40]

    print(f"[financial_tools] 解析 ticker：{company_name}…")
    symbol = resolve_ticker(company_name)

    if not symbol:
        print("[financial_tools] ⚠ 找不到對應 ticker，跳過財務資料抓取")
        return {"financial_data": {}}

    print(f"[financial_tools] ticker = {symbol}，抓取：{tools}")
    data = fetch_all(symbol, tools)
    return {"financial_data": data}


# ── Node 2: run_search ────────────────────────────────────────────────────────

_RESULTS_PER_QUERY = 3   # configurable per agent


def run_search(state: CompanyInfoState) -> dict:
    """
    Execute Tavily search for each query and collect results.
    """
    from utils.cost_tracker import tracker
    all_results = []
    for query in state["search_queries"]:
        results = search(query, max_results=_RESULTS_PER_QUERY)
        tracker.record_tavily(1)
        all_results.append({"query": query, "results": results})
    return {"search_results": all_results}


# ── Node 3: generate_report ───────────────────────────────────────────────────

def generate_report(state: CompanyInfoState) -> dict:
    """
    Use claude-opus to synthesize search results into a structured JSON report.
    Schema (sections and types) is decided dynamically by the model.
    """
    client = _get_client()

    # Flatten search results into readable context
    context_parts = []
    for entry in state["search_results"]:
        context_parts.append(f"[搜尋：{entry['query']}]")
        for r in entry["results"]:
            context_parts.append(f"來源：{r['title']} ({r['url']})")
            context_parts.append(r["content"])
            context_parts.append("")

    # Append structured financial data if available
    fin = state.get("financial_data") or {}
    if fin and len(fin) > 1:   # more than just "ticker" key
        import json as _json
        context_parts.append("[結構化財務資料（來自 yfinance）]")
        context_parts.append(_json.dumps(fin, ensure_ascii=False, default=str))
        context_parts.append("")

    context = "\n".join(context_parts)

    mode = state.get("mode", "short")
    if mode == "short":
        mode_rules = """\
6. 【Short 模式】嚴格依照任務指令範圍，不延伸、不補充任務未要求的背景資訊
7. 報告結構精簡：1-3 個 section，每個 bullets section 最多 6 條，paragraph 最多 150 字
8. 目標篇幅約兩頁，寧可少寫也不要湊字數"""
    else:
        mode_rules = """\
6. 【Medium 模式】可適度補充相關背景與延伸分析，section 數量不限
7. 確保資訊完整、分析深度足夠"""

    prompt = f"""你是 FCC Partners 的商業研究助理。根據搜尋資料，針對以下任務產出一份繁體中文報告。

任務指令：{state['task_instruction']}

搜尋資料：
{context}

輸出規則：
1. 回傳純 JSON，不要 markdown 包裝
2. sections 的數量和名稱由你根據任務指令決定，不要硬套固定格式
3. 每個 section 選擇最適合的呈現方式：
   - type "bullets"：適合事實性、條列式資訊（用 items 陣列）
   - type "paragraph"：適合分析性、敘述性內容（用 content 字串）
4. 語言：繁體中文，保留英文專有名詞（公司名、人名、產品名）；不要在任何名詞後加括號標注其他語言的原文或譯名（例如不要寫「環球集團（Global Group）」或「芽莊（Nha Trang）」，直接寫名稱本身）
5. 精簡準確，不要堆砌廢話；不要在報告內容中提及任務指令的措辭、比喻或身份設定（例如不要出現「類似麥肯錫」、「根據您的要求」等）
{mode_rules}

JSON 格式：
{{
  "title": "公司名稱 + 報告主題",
  "sections": [
    {{
      "heading": "節標題",
      "type": "bullets",
      "items": ["條目一", "條目二"]
    }},
    {{
      "heading": "節標題",
      "type": "paragraph",
      "content": "段落內容..."
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

    report = _parse_json(message.content[0].text)

    return {"report": report}


# ── Node 4: format_output ─────────────────────────────────────────────────────

def format_output(state: CompanyInfoState) -> dict:
    """
    Render the report JSON into a Word document and write the source log.
    """
    report = state["report"]
    intern = state["intern_name"]
    task_date = state.get("task_date") or date.today().strftime("%Y-%m-%d")
    subdir = state.get("subdir", "adhoc")

    # Build Word document
    builder = WordBuilder(report["title"], task_date, intern)
    for section in report.get("sections", []):
        builder.add_heading(section["heading"])
        if section["type"] == "bullets":
            for item in section.get("items", []):
                builder.add_bullet(item)
        else:
            builder.add_paragraph(section.get("content", ""))
        builder.add_blank_line()

    # Generate filename and save
    # Use dot-separated date for filename (YYYY.MM.DD)
    dot_date = task_date.replace("-", ".")
    filename = general(report["title"], intern, dot_date)
    output_path = builder.save(filename, subdir=subdir)

    # Write source log
    logger = AgentLogger("company_info_agent", state["task_instruction"], intern)
    logger.set_queries(state["search_queries"])
    for entry in state["search_results"]:
        logger.add_search_result(entry["query"], entry["results"])
    log_path = logger.save(output_path)

    return {
        "output_path": str(output_path),
        "log_path": str(log_path),
    }


# ── Graph ─────────────────────────────────────────────────────────────────────

def _needs_financial_fetch(state: CompanyInfoState) -> str:
    check = state.get("financial_check") or {}
    if check.get("q1") == "Y" and check.get("q2"):
        return "fetch"
    return "skip"


def build_graph():
    graph = StateGraph(CompanyInfoState)
    graph.add_node("parse_task",            parse_task)
    graph.add_node("check_financial_need",  check_financial_need)
    graph.add_node("fetch_financial_data",  fetch_financial_data)
    graph.add_node("run_search",            run_search)
    graph.add_node("generate_report",       generate_report)
    graph.add_node("format_output",         format_output)

    graph.set_entry_point("parse_task")
    graph.add_edge("parse_task", "check_financial_need")
    graph.add_conditional_edges(
        "check_financial_need",
        _needs_financial_fetch,
        {"fetch": "fetch_financial_data", "skip": "run_search"},
    )
    graph.add_edge("fetch_financial_data", "run_search")
    graph.add_edge("run_search",           "generate_report")
    graph.add_edge("generate_report",      "format_output")
    graph.add_edge("format_output",        END)

    return graph.compile()


# ── Public entry point ────────────────────────────────────────────────────────

def run(
    task_instruction: str,
    intern_name: Union[str, list[str]] = None,
    task_date: str = None,
    subdir: str = "adhoc",
    mode: str = "short",
) -> dict:
    """
    Run the company_info agent end-to-end.

    Args:
        task_instruction: Free-text research request, e.g.
                          "調查 Tesla，重點放自動駕駛業務和近期財務狀況"
        intern_name:      Name(s) for file naming. Defaults to config default.
        task_date:        Date string YYYY-MM-DD. Defaults to today.
        subdir:           Output subfolder — 'daily', 'weekly', or 'adhoc'.

    Returns:
        dict with keys 'output_path' and 'log_path'.
    """
    app = build_graph()

    initial_state: CompanyInfoState = {
        "task_instruction": task_instruction,
        "intern_name": intern_name or config.DEFAULT_INTERN_NAME,
        "task_date": task_date or date.today().strftime("%Y-%m-%d"),
        "subdir": subdir,
        "mode": mode,
        "search_queries": [],
        "search_results": [],
        "financial_check": {},
        "financial_data": {},
        "report": {},
        "output_path": "",
        "log_path": "",
    }

    final_state = app.invoke(initial_state)
    return {
        "output_path": final_state["output_path"],
        "log_path":    final_state["log_path"],
    }


# ── CLI shortcut ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    from utils.planner import confirm, parse_tasks

    parser = argparse.ArgumentParser(description="Company info research agent")
    parser.add_argument("--task",   required=True, help="Task instruction in Chinese or English")
    parser.add_argument("--intern", default=None,  help="Intern name(s), comma-separated")
    parser.add_argument("--date",   default=None,  help="Task date YYYY-MM-DD")
    parser.add_argument("--subdir", default="adhoc", choices=["daily", "weekly", "adhoc"])
    args = parser.parse_args()

    intern = [n.strip() for n in args.intern.split(",")] if args.intern and "," in args.intern else args.intern

    # ── Plan → confirm before running ─────────────────────────────
    print("正在解析任務...")
    tasks = parse_tasks(args.task, force_type="company_info")
    confirmed = confirm(tasks)

    if not confirmed:
        exit(0)

    # ── Run one agent invocation per confirmed task ────────────────
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
