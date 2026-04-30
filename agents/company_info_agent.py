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
    task_breadth: str                      # "narrow" | "broad" — drives per-query result count
    search_queries: list[str]              # all queries ever run (cumulative)
    pending_queries: list[str]             # queries to execute in the next run_search pass
    rounds: int                            # completed run_search rounds (1-indexed after first call)
    search_results: list[dict]             # [{query, results:[{title,url,content,score}]}]
    financial_check: dict                  # {"q1":"Y"|"N","company_name":str,"q2":[tool_ids],"q3":{"needed":"Y"|"N","sector":str,"country":str}}
    financial_data: dict                   # {"ticker": str, tool_id: data_dict, ...}
    sector_data: dict                      # FinanceDatabase sector scan result
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
    Use claude-haiku to read the task instruction and generate initial
    Tavily search queries plus a task_breadth classification ("narrow" or
    "broad") that drives per-query result count.
    """
    client = _get_client()

    prompt = f"""你是一個商業研究助理。根據以下任務指令，回傳 JSON：
1) breadth 分類：
   - "narrow"：單一公司、單一人物、或範圍明確的主題
   - "broad"：產業掃描、國家/地區投資案例、排行榜、多公司比較等需大量資料的任務
2) 3-5 個英文 Tavily 搜尋查詢

任務指令：{state['task_instruction']}

規則：
- 查詢語言用英文（搜尋效果更好）
- 若任務指令有提供股票代碼（如 3017.TW、002837.SZ），每一條 query 都必須帶入該代碼
- 每個查詢聚焦在不同面向，不要重複
- 回傳純 JSON 物件，不要多餘說明

格式：
{{"breadth": "narrow" | "broad",
  "queries": ["query1", "query2", "query3"]}}
"""

    message = client.messages.create(
        model=config.LLM_FAST,
        max_tokens=600,
        messages=[{"role": "user", "content": prompt}],
    )

    from utils.cost_tracker import tracker
    tracker.record_claude(config.LLM_FAST, message.usage.input_tokens, message.usage.output_tokens)

    try:
        parsed = _parse_json(message.content[0].text)
    except Exception:
        parsed = {}

    if isinstance(parsed, dict):
        queries = parsed.get("queries", [])
        breadth = parsed.get("breadth", "narrow")
    elif isinstance(parsed, list):   # fallback: model returned a bare array
        queries = parsed
        breadth = "narrow"
    else:
        queries, breadth = [], "narrow"

    if breadth not in ("narrow", "broad"):
        breadth = "narrow"

    print(f"[parse_task] breadth={breadth}  queries={len(queries)}")

    return {
        "search_queries": list(queries),
        "pending_queries": list(queries),
        "task_breadth": breadth,
        "rounds": 0,
    }


# ── Node 1b: check_financial_need ────────────────────────────────────────────

def check_financial_need(state: CompanyInfoState) -> dict:
    """
    Use Haiku to classify whether the task needs financial market data.
    Q1: Does the task subject include a listed company? (Y/N)
    Q2: Which financial tools are needed? (subset of TOOL_REGISTRY keys, or [])
    Both must be Y/non-empty to trigger fetch_financial_data.
    """
    from utils.financial_tools import YFINANCE_TOOL_DESCRIPTIONS, SECTOR_TOOL_DESCRIPTIONS

    yf_menu = "\n".join(f'- "{tid}": {desc}' for tid, desc in YFINANCE_TOOL_DESCRIPTIONS.items())
    sector_menu = "\n".join(f'- "{tid}": {desc}' for tid, desc in SECTOR_TOOL_DESCRIPTIONS.items())

    prompt = f"""你是一個任務分析助理。根據以下任務指令，回答三個問題。

任務指令：{state['task_instruction']}

【Q2 可用工具 — 針對特定上市公司（yfinance）】
{yf_menu}

【Q3 可用工具 — 針對產業 / 地區掃描（FinanceDatabase）】
{sector_menu}

回答規則：
- Q1：任務對象是否包含特定上市櫃公司？回答 "Y" 或 "N"
- Q2：若 Q1=Y，任務是否需要該公司的財務市場資料？從 Q2 工具清單選出需要的 id（可複選）；否則空陣列
- company_name：若 Q1=Y，填最適合搜尋 ticker 的名稱（優先英文）；否則空字串
- Q3：任務是否需要產業 / 地區的公司清單或掃描？若是，填 needed=Y 並指定 sector（英文產業名）與 country（英文國名，不限定則填 null）；否則 needed=N
- Q2 與 Q3 互相獨立，可同時觸發
- 只在任務明確需要時才選工具；一般研究不需要
- 回傳純 JSON，不要多餘說明

格式範例：
{{"q1": "Y", "company_name": "Tesla", "q2": ["stock_price", "key_metrics"], "q3": {{"needed": "N", "sector": "", "country": null}}}}
{{"q1": "N", "company_name": "", "q2": [], "q3": {{"needed": "Y", "sector": "Electric Vehicles", "country": "United States"}}}}
"""

    client = _get_client()
    message = client.messages.create(
        model=config.LLM_FAST,
        max_tokens=300,
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
        if not isinstance(check.get("q3"), dict):
            check["q3"] = {"needed": "N", "sector": "", "country": None}
    except Exception:
        check = {"q1": "N", "company_name": "", "q2": [], "q3": {"needed": "N", "sector": "", "country": None}}

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
    symbol = resolve_ticker(company_name, task_context=state["task_instruction"])

    if not symbol:
        print("[financial_tools] ⚠ 找不到對應 ticker，跳過財務資料抓取")
        return {"financial_data": {"_ticker_error": f"ticker resolution failed for {company_name!r}"}}

    print(f"[financial_tools] ticker = {symbol}，抓取：{tools}")
    data = fetch_all(symbol, tools)
    return {"financial_data": data}


# ── Node 1d: fetch_sector_data ────────────────────────────────────────────────

def fetch_sector_data(state: CompanyInfoState) -> dict:
    """
    Run FinanceDatabase sector scan based on Q3 classification.
    No-op (returns empty dict) when Q3.needed != "Y".
    """
    q3 = state.get("financial_check", {}).get("q3", {})
    if q3.get("needed") != "Y" or not q3.get("sector"):
        return {"sector_data": {}}

    from utils.financial_tools import fetch_sector_data as _fetch
    data = _fetch(q3)
    return {"sector_data": data}


# ── Node 2: run_search ────────────────────────────────────────────────────────

_RESULTS_PER_QUERY_NARROW = 3
_RESULTS_PER_QUERY_BROAD  = 6

# Iterative search caps
_MAX_ROUNDS         = 4     # incl. initial round
_MAX_TOTAL_QUERIES  = 15    # hard cap across all rounds


def run_search(state: CompanyInfoState) -> dict:
    """
    Execute Tavily search for the current pending_queries and append to
    search_results. Called once initially, and again each time
    evaluate_coverage decides the corpus is insufficient.
    """
    from utils.cost_tracker import tracker

    pending = state.get("pending_queries", [])
    breadth = state.get("task_breadth", "narrow")
    max_results = _RESULTS_PER_QUERY_BROAD if breadth == "broad" else _RESULTS_PER_QUERY_NARROW

    accumulated = list(state.get("search_results", []))
    for query in pending:
        results = search(query, max_results=max_results)
        tracker.record_tavily(1)
        accumulated.append({"query": query, "results": results})

    rounds = state.get("rounds", 0) + 1
    print(f"[run_search] round={rounds}  +{len(pending)} queries  (total={len(accumulated)})")

    return {
        "search_results": accumulated,
        "pending_queries": [],
        "rounds": rounds,
    }


# ── Node 2b: evaluate_coverage ────────────────────────────────────────────────

def evaluate_coverage(state: CompanyInfoState) -> dict:
    """
    Ask Haiku whether the accumulated search_results are sufficient to answer
    the task. If not, produce follow-up queries targeting the specific gaps.

    Returns pending_queries populated when another round is needed; empty list
    signals "proceed to generate_report" via the conditional edge.
    """
    total_queries = len(state.get("search_queries", []))
    rounds_done = state.get("rounds", 0)

    # Hard stops — don't even call Haiku
    if rounds_done >= _MAX_ROUNDS or total_queries >= _MAX_TOTAL_QUERIES:
        print(f"[evaluate_coverage] cap reached (rounds={rounds_done}, queries={total_queries}) — proceed")
        return {"pending_queries": []}

    # Narrow tasks: one round is usually enough, skip evaluator to save cost
    if state.get("task_breadth") != "broad" and rounds_done >= 1:
        return {"pending_queries": []}

    # Build compact corpus digest for Haiku (titles + snippet only)
    digest_lines = []
    for entry in state.get("search_results", []):
        digest_lines.append(f"[Q] {entry['query']}")
        for r in entry.get("results", [])[:4]:
            digest_lines.append(f"  - {r.get('title','')[:120]}")
            snippet = (r.get("content") or "")[:220].replace("\n", " ")
            if snippet:
                digest_lines.append(f"    {snippet}")
    digest = "\n".join(digest_lines) or "(no results yet)"

    already_run = state.get("search_queries", [])
    remaining_budget = _MAX_TOTAL_QUERIES - total_queries

    prompt = f"""你是一個搜尋結果充分性評估助理。判斷目前蒐集到的資料是否足以回答任務。

任務指令：{state['task_instruction']}

已執行過的查詢（不要重複）：
{chr(10).join('- ' + q for q in already_run)}

已蒐集的資料摘要：
{digest}

規則：
- 若資料足夠完整回答任務，sufficient="Y"
- 若還缺關鍵面向（如數字、具體名單、時間序列），sufficient="N" 並列出具體缺口與追加查詢
- followup_queries 為英文，最多 {min(4, remaining_budget)} 條，不可與「已執行過的查詢」重複
- 每條 follow-up 針對一個具體缺口，不要寬泛覆述
- 回傳純 JSON，無 markdown

格式：
{{"sufficient": "Y" | "N",
  "missing": ["缺口 1", "缺口 2"],
  "followup_queries": ["specific query 1", "specific query 2"]}}
"""

    client = _get_client()
    message = client.messages.create(
        model=config.LLM_FAST,
        max_tokens=600,
        messages=[{"role": "user", "content": prompt}],
    )

    from utils.cost_tracker import tracker
    tracker.record_claude(config.LLM_FAST, message.usage.input_tokens, message.usage.output_tokens)

    try:
        verdict = _parse_json(message.content[0].text)
    except Exception as exc:
        print(f"[evaluate_coverage] parse failed ({exc}); proceeding")
        return {"pending_queries": []}

    if verdict.get("sufficient") == "Y":
        print("[evaluate_coverage] sufficient ✓")
        return {"pending_queries": []}

    followups = verdict.get("followup_queries") or []
    # Dedupe against already-run queries
    seen = {q.lower() for q in already_run}
    new_queries = [q for q in followups if q and q.lower() not in seen]
    # Enforce remaining budget
    new_queries = new_queries[:remaining_budget]

    if not new_queries:
        print("[evaluate_coverage] no new follow-ups — proceed")
        return {"pending_queries": []}

    print(f"[evaluate_coverage] insufficient — +{len(new_queries)} follow-ups: {verdict.get('missing', [])}")
    return {
        "pending_queries": new_queries,
        "search_queries": already_run + new_queries,
    }


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

    import json as _json
    fin = state.get("financial_data") or {}
    if fin and len(fin) > 1:   # more than just "ticker" key
        context_parts.append("[結構化財務資料（來自 yfinance）]")
        context_parts.append(_json.dumps(fin, ensure_ascii=False, default=str))
        context_parts.append("")

    sec = state.get("sector_data") or {}
    if sec and "companies" in sec:
        context_parts.append("[產業公司清單（來自 FinanceDatabase）]")
        context_parts.append(_json.dumps(sec, ensure_ascii=False, default=str))
        context_parts.append("")

    context = "\n".join(context_parts)

    mode = state.get("mode", "short")
    if mode == "short":
        mode_rules = """\
7. 【Short 模式】嚴格依照任務指令範圍，不延伸、不補充任務未要求的背景資訊
8. 報告結構精簡：1-3 個 section，每個 bullets section 最多 6 條，paragraph 最多 150 字
9. 目標篇幅約兩頁，寧可少寫也不要湊字數"""
    else:
        mode_rules = """\
7. 【Medium 模式】可適度補充相關背景與延伸分析，section 數量不限
8. 確保資訊完整、分析深度足夠"""

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
6. 財務數字優先採用結構化財務資料（yfinance）；Tavily 的財務數字僅作為背景參考，若與結構化資料矛盾，以結構化資料為準
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
    if state.get("financial_data"):
        logger.add_financial_data(state["financial_data"])
    if state.get("sector_data"):
        logger.add_sector_data(state["sector_data"])
    log_path = logger.save(output_path)

    return {
        "output_path": str(output_path),
        "log_path": str(log_path),
    }


# ── Graph ─────────────────────────────────────────────────────────────────────

def build_graph():
    graph = StateGraph(CompanyInfoState)
    graph.add_node("parse_task",           parse_task)
    graph.add_node("check_financial_need", check_financial_need)
    graph.add_node("fetch_financial_data", fetch_financial_data)
    graph.add_node("fetch_sector_data",    fetch_sector_data)
    graph.add_node("run_search",           run_search)
    graph.add_node("evaluate_coverage",    evaluate_coverage)
    graph.add_node("generate_report",      generate_report)
    graph.add_node("format_output",        format_output)

    graph.set_entry_point("parse_task")
    graph.add_edge("parse_task",           "check_financial_need")
    graph.add_conditional_edges(
        "check_financial_need",
        lambda s: "fetch" if s["financial_check"].get("q2") else "skip",
        {"fetch": "fetch_financial_data", "skip": "fetch_sector_data"},
    )
    graph.add_edge("fetch_financial_data", "fetch_sector_data")
    graph.add_edge("fetch_sector_data",    "run_search")
    graph.add_edge("run_search",           "evaluate_coverage")
    graph.add_conditional_edges(
        "evaluate_coverage",
        lambda s: "loop" if s.get("pending_queries") else "proceed",
        {"loop": "run_search", "proceed": "generate_report"},
    )
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
        "task_breadth": "narrow",
        "search_queries": [],
        "pending_queries": [],
        "rounds": 0,
        "search_results": [],
        "financial_check": {},
        "financial_data": {},
        "sector_data": {},
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
    parser.add_argument("--yes",    action="store_true", help="Skip confirmation prompt")
    args = parser.parse_args()

    intern = [n.strip() for n in args.intern.split(",")] if args.intern and "," in args.intern else args.intern

    # ── Plan → confirm before running ─────────────────────────────
    print("正在解析任務...")
    tasks = parse_tasks(args.task, force_type="company_info")
    confirmed = tasks if args.yes else confirm(tasks)

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
