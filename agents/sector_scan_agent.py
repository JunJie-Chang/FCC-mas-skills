"""
agents/sector_scan_agent.py — Structured sector / list ranking agent.

Designed for tasks like:
  「列出台灣前十大半導體公司，比較市值與營收」
  「香港金融業上市公司清單，按 PE 排序」

Flow:
    parse_request → check_feasibility → fetch_companies → enrich_metrics → format_output
                          ↓ (infeasible)
                      fallback_note (terminate with dry note)

Key design:
  - Haiku is constrained to picking from FinanceDatabase's actual enum values
    (cached in utils/_fdb_enum.json). No free-form input → no illegal queries
    like industry='semiconductor company'.
  - Per-ticker yfinance enrichment runs at _CALL_DELAY rate limit.
  - Output is a single sortable table — no Tavily, no narrative synthesis.
  - When task isn't representable in FDB taxonomy (e.g. "AI 概念股"), the
    agent terminates gracefully with a one-section note advising the user
    to fall back to company_info / web search.
"""
import json
import os
import re
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
from utils.financial_tools import (
    fetch_key_metrics,
    fetch_sector_scan,
    fetch_stock_price,
    get_fdb_enum,
)
from utils.logger import AgentLogger

load_dotenv(override=True)


# ── Tunables ─────────────────────────────────────────────────────────────────

_DEFAULT_TOP_N        = 10   # how many companies to enrich + show in the table
_MAX_COMPANIES        = 30   # hard upper bound regardless of user request
_PER_TICKER_DELAY     = 1.5  # rate-limit between yfinance calls


# ── State ────────────────────────────────────────────────────────────────────

class SectorScanState(TypedDict):
    task_instruction: str
    intern_name: Union[str, list[str]]
    task_date: str
    subdir: str
    mode: str
    plan: dict                  # {"feasible":Y/N, "industry":..., "country":..., "top_n":int, "rank_by":..., "metrics":[...], "reason":""}
    companies: list[dict]       # raw FDB list
    enriched: list[dict]        # per-ticker yfinance metrics merged in
    output_path: str
    log_path: str


# ── Helpers ──────────────────────────────────────────────────────────────────

def _get_client() -> Anthropic:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise EnvironmentError("ANTHROPIC_API_KEY not set in .env")
    return Anthropic(api_key=api_key)


def _parse_json(text: str):
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text).strip()
    m = re.search(r"(\{[\s\S]*\}|\[[\s\S]*\])", text)
    if m:
        text = m.group(1)
    return json.loads(text)


# ── Node 1: parse_request + feasibility check ───────────────────────────────

_AVAILABLE_METRICS = {
    "market_cap":       "市值（USD）",
    "revenue_ttm":      "TTM 營收",
    "trailing_pe":      "Trailing PE",
    "forward_pe":       "Forward PE",
    "dividend_yield":   "股息率",
    "current_price":    "現價",
    "change_3mo_pct":   "近 3 個月漲跌幅",
}


def parse_request(state: SectorScanState) -> dict:
    """
    Haiku reads the task + FDB enum, decides:
      - feasible: Y/N (can we pick a single industry/country combo from the enum?)
      - industry, country: must be enum values (verbatim)
      - top_n, rank_by, metrics: user's requested ranking + columns
      - reason: when N, explain why (so we can show fallback note)
    """
    enum = get_fdb_enum()
    metric_lines = "\n".join(f'  - "{k}": {v}' for k, v in _AVAILABLE_METRICS.items())

    prompt = f"""{config.time_context()}

你是結構化資料調查任務分析助理。判斷使用者請求是否可由 FinanceDatabase + yfinance 回答。

任務指令：{state['task_instruction']}

【FinanceDatabase 可用 industry_group 清單（{len(enum['industry_groups'])} 條，必須逐字選用）】
{json.dumps(enum['industry_groups'], ensure_ascii=False)}

【FinanceDatabase 可用 industry 清單（{len(enum['industries'])} 條）】
{json.dumps(enum['industries'], ensure_ascii=False)}

【FinanceDatabase 可用 country 清單（節錄與亞洲 / 主要市場相關）】
{json.dumps([c for c in enum['countries'] if c in ('Taiwan','Hong Kong','China','Japan','South Korea','Singapore','Vietnam','Thailand','Malaysia','Philippines','Indonesia','India','United States','United Kingdom','Germany','France','Australia','Canada')], ensure_ascii=False)}
（其他國家若需要，從完整清單選用：{len(enum['countries'])} 國）

【可比較的數值欄位】
{metric_lines}

判斷規則：
- feasible="Y" 條件：使用者請求**明確指向某個產業 + 地區的上市公司清單**，且該產業可從上方 industry / industry_group 清單中找到「逐字相符或語意極接近」的值（如「半導體」→ "Semiconductors & Semiconductor Equipment"）
- feasible="N" 條件：使用者請求屬於**主題式 / 概念式 / 非標準分類**（如「AI 概念股」「重電股」「年終排名前十」「綠能新貴」「META 概念」），FDB 沒有對應分類；或地區無法對應到 country
- industry 從上方清單**逐字**選用（不可生造），優先選 industry 層級；若 industry 沒有就退回 industry_group
- country 從上方清單**逐字**選用，國名英文名
- top_n：使用者要前幾名？沒明說預設 10，最多 30
- rank_by：排序依據，從可比較欄位選一個（market_cap / revenue_ttm / trailing_pe …）；無明示則 market_cap
- metrics：報告表格要顯示的欄位（list of metric ids），至少含 rank_by；通常 3-5 個
- reason：feasible="N" 時必填，一句話說為什麼（給使用者看）；Y 時空字串

回傳純 JSON：
{{"feasible": "Y", "industry": "Semiconductors & Semiconductor Equipment", "country": "Taiwan",
  "top_n": 10, "rank_by": "market_cap",
  "metrics": ["market_cap", "trailing_pe", "current_price", "change_3mo_pct"], "reason": ""}}

或：
{{"feasible": "N", "industry": "", "country": "", "top_n": 0, "rank_by": "",
  "metrics": [], "reason": "「AI 概念股」非 FinanceDatabase 標準產業分類，建議改用 company_info + 新聞搜尋"}}
"""

    client = _get_client()
    msg = client.messages.create(
        model=config.LLM_FAST,
        max_tokens=600,
        messages=[{"role": "user", "content": prompt}],
    )

    from utils.cost_tracker import tracker
    tracker.record_claude(config.LLM_FAST, msg.usage.input_tokens, msg.usage.output_tokens)

    plan = _parse_json(msg.content[0].text)

    # Defensive validation: feasibility=Y must produce enum-valid industry + country
    if plan.get("feasible") == "Y":
        industry = plan.get("industry", "")
        country  = plan.get("country", "")
        if industry not in enum["industries"] and industry not in enum["industry_groups"]:
            print(f"[sector_scan] ⚠ Haiku 給的 industry {industry!r} 不在 enum 內，標為不可行")
            plan = {**plan, "feasible": "N",
                    "reason": f"Haiku 選的 industry {industry!r} 不在 FinanceDatabase enum 中"}
        elif country and country not in enum["countries"]:
            print(f"[sector_scan] ⚠ Haiku 給的 country {country!r} 不在 enum 內，標為不可行")
            plan = {**plan, "feasible": "N",
                    "reason": f"Haiku 選的 country {country!r} 不在 FinanceDatabase enum 中"}
        else:
            top_n = min(int(plan.get("top_n") or _DEFAULT_TOP_N), _MAX_COMPANIES)
            plan["top_n"] = top_n

    return {"plan": plan}


def _is_feasible(state: SectorScanState) -> str:
    return "go" if state["plan"].get("feasible") == "Y" else "skip"


# ── Node 2: fetch_companies (FDB) ────────────────────────────────────────────

def fetch_companies(state: SectorScanState) -> dict:
    """Pull the raw company list from FinanceDatabase using the planned filters."""
    plan    = state["plan"]
    industry = plan["industry"]
    country  = plan.get("country") or None
    top_n    = plan["top_n"]

    print(f"[sector_scan] FDB scan: industry={industry!r} country={country!r} top_n={top_n}")
    result = fetch_sector_scan(industry, country, limit=top_n * 3)   # over-fetch in case some lack data
    if "error" in result:
        print(f"[sector_scan] ⚠ FDB returned error: {result['error']}")
        return {"companies": []}
    companies = result.get("companies", [])
    print(f"[sector_scan] FDB returned {len(companies)} candidates")
    return {"companies": companies}


# ── Node 3: enrich_metrics (yfinance per ticker) ─────────────────────────────

def enrich_metrics(state: SectorScanState) -> dict:
    """
    For each FDB candidate, call yfinance to fetch the requested metrics.
    Sort by rank_by, take top_n.
    """
    import time

    plan    = state["plan"]
    rank_by = plan["rank_by"]
    metrics = plan["metrics"]
    top_n   = plan["top_n"]

    enriched: list[dict] = []
    for i, company in enumerate(state["companies"]):
        if i > 0:
            time.sleep(_PER_TICKER_DELAY)
        symbol = company.get("symbol", "")
        if not symbol:
            continue

        print(f"[sector_scan] enrich {symbol} ({company.get('name','?')})…")
        row = {
            "symbol": symbol,
            "name":   company.get("name", ""),
            "exchange": company.get("exchange", ""),
            "country":  company.get("country", ""),
        }

        # Pull only what's needed
        need_price   = "current_price" in metrics or "change_3mo_pct" in metrics
        need_metrics = any(m in metrics for m in
                           ("market_cap", "trailing_pe", "forward_pe",
                            "dividend_yield", "revenue_ttm")) or rank_by in (
                            "market_cap", "trailing_pe", "forward_pe",
                            "dividend_yield", "revenue_ttm")

        if need_price:
            sp = fetch_stock_price(symbol)
            if "error" not in sp:
                row["current_price"]  = sp.get("current_price")
                row["change_3mo_pct"] = sp.get("change_3mo_pct")
                row["currency"]       = sp.get("currency")
                row["price_as_of"]    = sp.get("as_of")

        if need_metrics:
            km = fetch_key_metrics(symbol)
            if "error" not in km:
                row["market_cap"]     = km.get("marketCap")
                row["trailing_pe"]    = km.get("trailingPE")
                row["forward_pe"]     = km.get("forwardPE")
                row["dividend_yield"] = km.get("dividendYield")
                row["revenue_ttm"]    = None   # yfinance doesn't expose TTM revenue cleanly here

        enriched.append(row)

    # Sort by rank_by — rows missing the value sink to the bottom
    def _key(r):
        v = r.get(rank_by)
        if v is None:
            return (1, 0)
        # PE: ascending (smaller is cheaper); others: descending
        if rank_by in ("trailing_pe", "forward_pe"):
            return (0, v)
        return (0, -v)

    enriched.sort(key=_key)
    enriched = enriched[:top_n]
    return {"enriched": enriched}


# ── Node 4: format_output ────────────────────────────────────────────────────

_METRIC_LABEL = {
    "market_cap":     "市值",
    "revenue_ttm":    "TTM 營收",
    "trailing_pe":    "Trailing PE",
    "forward_pe":     "Forward PE",
    "dividend_yield": "股息率",
    "current_price":  "現價",
    "change_3mo_pct": "3M 漲跌%",
}


def _fmt_value(metric: str, value) -> str:
    if value is None:
        return "—"
    if metric == "market_cap":
        # Convert to billions
        try:
            return f"{value / 1e9:.2f}B"
        except Exception:
            return str(value)
    if metric in ("trailing_pe", "forward_pe"):
        try:
            return f"{value:.2f}x"
        except Exception:
            return str(value)
    if metric in ("dividend_yield", "change_3mo_pct"):
        try:
            return f"{value:.2%}" if metric == "dividend_yield" else f"{value:+.2f}%"
        except Exception:
            return str(value)
    if metric == "current_price":
        try:
            return f"{value:.2f}"
        except Exception:
            return str(value)
    return str(value)


def format_output(state: SectorScanState) -> dict:
    plan      = state["plan"]
    intern    = state["intern_name"]
    task_date = state.get("task_date") or date.today().strftime("%Y-%m-%d")
    subdir    = state.get("subdir", "adhoc")

    if plan.get("feasible") != "Y":
        # Infeasible — produce a short note doc explaining the limitation
        title = f"結構化資料調查（不可行）_{state['task_instruction'][:30]}"
        builder = WordBuilder(title, task_date, intern)
        builder.add_heading("無法以結構化資料回答此任務")
        builder.add_paragraph(plan.get("reason", "請求未對應到 FinanceDatabase 標準分類"))
        builder.add_paragraph("建議改以 company_info agent + Tavily 搜尋處理（如「AI 概念股」這類主題式請求）。")
        out = builder.save(general(title, intern, task_date.replace("-", ".")), subdir=subdir)
        logger = AgentLogger("sector_scan_agent", state["task_instruction"], intern)
        logger.set_queries([])
        log = logger.save(out)
        return {"output_path": str(out), "log_path": str(log)}

    industry  = plan["industry"]
    country   = plan.get("country") or "全球"
    rank_by   = plan["rank_by"]
    metrics   = plan["metrics"]

    title = f"{country} {industry} Top {plan['top_n']}（依 {_METRIC_LABEL.get(rank_by, rank_by)} 排序）"
    builder = WordBuilder(title, task_date, intern)
    builder.add_blank_line()

    # Pre-table summary
    summary = (
        f"資料範圍：FinanceDatabase（公司清單）+ yfinance（市場數據）；"
        f"排序依據：{_METRIC_LABEL.get(rank_by, rank_by)}；"
        f"共 {len(state['enriched'])} 家公司。"
    )
    builder.add_paragraph(summary)
    builder.add_blank_line()

    # Build the table
    headers = ["#", "公司", "Ticker", "交易所"] + [_METRIC_LABEL.get(m, m) for m in metrics]
    rows: list[list[str]] = []
    for i, r in enumerate(state["enriched"], 1):
        row = [
            str(i),
            r.get("name", "")[:40],
            r.get("symbol", ""),
            r.get("exchange", ""),
        ]
        for m in metrics:
            row.append(_fmt_value(m, r.get(m)))
        rows.append(row)
    builder.add_table(headers, rows)

    # Save
    filename = general(title, intern, task_date.replace("-", "."))
    out_path = builder.save(filename, subdir=subdir)

    logger = AgentLogger("sector_scan_agent", state["task_instruction"], intern)
    logger.set_queries([f"FDB scan: industry={industry!r} country={country!r}"])
    # Surface the enriched rows in the .log for fact-check
    logger.add_search_result(
        f"top_{plan['top_n']}_by_{rank_by}",
        [
            {
                "title": f"{r.get('name','')} ({r.get('symbol','')})",
                "url":   "",
                "score": 0.0,
            }
            for r in state["enriched"]
        ],
    )
    log_path = logger.save(out_path)
    return {"output_path": str(out_path), "log_path": str(log_path)}


# ── Graph ─────────────────────────────────────────────────────────────────────

def build_graph():
    graph = StateGraph(SectorScanState)
    graph.add_node("parse_request",     parse_request)
    graph.add_node("fetch_companies",   fetch_companies)
    graph.add_node("enrich_metrics",    enrich_metrics)
    graph.add_node("format_output",     format_output)

    graph.set_entry_point("parse_request")
    graph.add_conditional_edges(
        "parse_request",
        _is_feasible,
        {"go": "fetch_companies", "skip": "format_output"},
    )
    graph.add_edge("fetch_companies", "enrich_metrics")
    graph.add_edge("enrich_metrics",  "format_output")
    graph.add_edge("format_output",   END)

    return graph.compile()


# ── Public entry point ───────────────────────────────────────────────────────

def run(
    task_instruction: str,
    intern_name: Union[str, list[str]] = None,
    task_date: str = None,
    subdir: str = "adhoc",
    mode: str = "short",
) -> dict:
    app = build_graph()
    state = app.invoke({
        "task_instruction": task_instruction,
        "intern_name":      intern_name or config.DEFAULT_INTERN_NAME,
        "task_date":        task_date or date.today().strftime("%Y-%m-%d"),
        "subdir":           subdir,
        "mode":             mode,
        "plan":             {},
        "companies":        [],
        "enriched":         [],
        "output_path":      "",
        "log_path":         "",
    })
    return {
        "output_path": state["output_path"],
        "log_path":    state["log_path"],
    }


# ── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    from utils.planner import confirm, parse_tasks

    parser = argparse.ArgumentParser(description="Sector / list-ranking research agent")
    parser.add_argument("--task",   required=True)
    parser.add_argument("--intern", default=None)
    parser.add_argument("--date",   default=None)
    parser.add_argument("--subdir", default="adhoc", choices=["daily", "weekly", "adhoc"])
    parser.add_argument("--yes",    action="store_true")
    args = parser.parse_args()

    intern = (
        [n.strip() for n in args.intern.split(",")]
        if args.intern and "," in args.intern else args.intern
    )

    print("正在解析任務...")
    tasks = parse_tasks(args.task, force_type="sector_scan")
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
