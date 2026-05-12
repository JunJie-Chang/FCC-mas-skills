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
import utils.react_loop as react_loop
from formatters.word_formatter import WordBuilder
from utils.file_naming import general
from utils.logger import AgentLogger

load_dotenv(override=True)


# ── State ─────────────────────────────────────────────────────────────────────

class CompanyInfoState(TypedDict):
    task_instruction: str
    intern_name: Union[str, list[str]]
    task_date: str                         # YYYY-MM-DD
    subdir: str                            # output subfolder: daily / weekly / adhoc
    mode: str                              # "short" | "medium"
    # ReAct loop state
    todos: list[dict]                      # [{"id":int,"question":str,"status":"pending"|"done"|"unresolved","attempts":int}]
    evidence: list[dict]                   # [{query, results:[...]}] accumulated across rounds
    round: int                             # current loop iteration (0-indexed)
    # Legacy / shared
    search_queries: list[str]
    search_results: list[dict]             # [{query, results:[{title,url,content,score}]}]
    financial_check: dict                  # {"q1":"Y"|"N","tickers":[...],"company_name":str,"q2":[tool_ids],"q3":{...}}
    financial_data: dict                   # {ticker: {tool_id: data, ...}, ..., "_resolve_failed":[names]} — empty / {"_ticker_error":...} when none resolved
    sector_data: dict                      # FinanceDatabase sector scan result
    number_items: list[dict]               # raw Haiku echo from utils/number_extract (audit)
    numbers_zh: dict                       # {label: canonical Chinese string} for prompt
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

_MAX_ROUNDS = 6
_COMPANY_SEARCH_HINT = (
    "若任務有股票代碼，每條 query 都帶入；"
    "優先搜財報、公告、投資人說明會、行業分析報告等一手來源"
)


def parse_task(state: CompanyInfoState) -> dict:
    """
    Use Haiku to build a research plan (todo list) from the task instruction.
    Each todo is a specific question / fact to find.
    Also generate the first batch of search queries.
    """
    client = _get_client()

    prompt = f"""{config.time_context()}

你是一個商業研究規劃師。根據以下任務指令，產出一份研究計劃。

任務指令：{state['task_instruction']}

輸出兩件事：
1. todos：這份報告需要回答的具體問題清單（3-6 個）
2. initial_queries：第一輪的搜尋查詢（英文，2-3 條）

搜尋查詢設計原則（推論式，而非正面表述）：
- 不要直接搜「XX 公司業務結構」，而是搜「XX annual report 2024」「XX investor presentation」「XX 10-K filing」
- 不要搜「XX 競爭優勢」，而是搜「XX market share industry analysis」「XX vs competitors benchmark」
- 目標：找到一手來源（財報、公司公告、行業報告），再從來源推斷答案
- 若有股票代碼，每條 query 都帶入

回傳純 JSON，格式：
{{
  "todos": [
    {{"id": 1, "question": "公司的主要業務線和營收結構？"}},
    {{"id": 2, "question": "最近兩個季度的財務表現（營收、利潤、成長率）？"}},
    {{"id": 3, "question": "主要競爭對手和市場定位？"}}
  ],
  "initial_queries": [
    "Envicool 002837.SZ annual report 2024 investor",
    "liquid cooling data center China market share 2024"
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
    initial_queries = parsed.get("initial_queries", [])

    return {
        "todos":         todos,
        "evidence":      [],
        "round":         0,
        "search_queries": initial_queries,
        "search_results": [],
    }


# ── ReAct loop nodes (thin wrappers over utils/react_loop) ───────────────────

def run_search(state: CompanyInfoState) -> dict:
    return react_loop.run_initial_search(state)

def next_action(state: CompanyInfoState) -> dict:
    return react_loop.next_action(state, max_rounds=_MAX_ROUNDS, search_hint=_COMPANY_SEARCH_HINT)

def execute_search(state: CompanyInfoState) -> dict:
    return react_loop.execute_search(state)

def evaluate(state: CompanyInfoState) -> dict:
    return react_loop.evaluate(state)

def _should_continue(state: CompanyInfoState) -> str:
    return react_loop.should_continue(state, max_rounds=_MAX_ROUNDS)


# ── Financial nodes ────────────────────────────────────────────────────────────

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

    prompt = f"""你是一個任務分析助理。根據以下任務指令，回答下列問題。

任務指令：{state['task_instruction']}

【Q2 可用工具 — 針對特定上市公司（yfinance）】
{yf_menu}

【Q3 可用工具 — 針對產業 / 地區掃描（FinanceDatabase）】
{sector_menu}

回答規則：
- Q1：任務是否「明確需要」該公司的市場交易資料（股價 / 估值倍數 / 財報數字）？回答 "Y" 或 "N"
  - Y 條件：任務字面提到「股價」「市值」「PE」「EV/EBITDA」「股息」「最近一季 / 最新財報數字」「機構持股」「Yahoo 新聞」其中之一
  - N 條件：純業務面研究（戰略、產品線、競爭定位、人事、海外佈局、併購歷史、客戶關係）— 即使任務帶公司名與股票代碼，只要沒明問財務數字，一律 N
  - **保守原則**：不確定 → N（這層只是抓**結構化市場資料**，業務細節走 Tavily 即可）

- Q2：若 Q1=Y，從 Q2 工具清單選出實際需要的 id（可複選，所有 ticker 共用同一份工具清單）；否則空陣列

- tickers：若 Q1=Y 且【你能直接判定股票代碼】，填**list of 純 ticker 字串**（最多 3 個，按任務指令出現順序）；否則空 list []
  - 任務明寫了 ticker（例「Tesla (TSLA)」「環旭電子 (3033.TW)」「GameStop NYSE: GME」），直接擷取
  - 任務只給中／英文公司名但你 high-confidence 知道對應 ticker（例「Tesla」→ TSLA、「台積電」→ 2330.TW），也填
  - 任務涉及多家公司（M&A / 比較 / 競合），逐個填進 list（M&A 把【收購方 / 任務主角】放第一位）
  - 不確定就不要硬猜（寧可空 list 走 fallback，也不要填錯）
  - 嚴格格式：純 ticker 字串（如 "GME"、"2330.TW"、"9988.HK"），禁止加括號 / 交易所前綴 / 公司名

- company_name：若 tickers=[] 但 Q1=Y（任務需要財務資料但你不確定任何 ticker），填【乾淨】公司英文名（單一公司，例：Envicool / Universal Scientific Industrial），禁止加括號 / 交易所 / ticker；否則空字串

- Q3：任務是否需要產業 / 地區的公司清單或掃描？若是，填 needed=Y，並**必須**指定 sector（英文產業名）與 country（英文國名）；country 不可填 null，若任務未明示地區，請從 task context 推斷（CY / FCC Partners 業務以台灣、東南亞、香港為主，無法推斷時預設 "Taiwan"）；否則 needed=N

- Q2 與 Q3 互相獨立，可同時觸發
- 回傳純 JSON，不要多餘說明

格式範例：
{{"q1": "Y", "tickers": ["TSLA"], "company_name": "", "q2": ["stock_price", "key_metrics"], "q3": {{"needed": "N", "sector": "", "country": null}}}}
{{"q1": "Y", "tickers": ["GME", "EBAY"], "company_name": "", "q2": ["stock_price", "key_metrics", "financials"], "q3": {{"needed": "N", "sector": "", "country": null}}}}
{{"q1": "Y", "tickers": [], "company_name": "Envicool", "q2": ["financials"], "q3": {{"needed": "N", "sector": "", "country": null}}}}
{{"q1": "N", "tickers": [], "company_name": "", "q2": [], "q3": {{"needed": "Y", "sector": "Electric Vehicles", "country": "United States"}}}}
"""

    client = _get_client()
    message = client.messages.create(
        model=config.LLM_FAST,
        max_tokens=400,   # tickers list + JSON scaffolding needs a bit more headroom than 300
        messages=[{"role": "user", "content": prompt}],
    )

    from utils.cost_tracker import tracker
    tracker.record_claude(config.LLM_FAST, message.usage.input_tokens, message.usage.output_tokens)

    _empty = {"q1": "N", "tickers": [], "company_name": "", "q2": [],
              "q3": {"needed": "N", "sector": "", "country": None}}
    try:
        check = _parse_json(message.content[0].text)
        if not isinstance(check.get("q2"), list):
            check["q2"] = []
        # tickers: list of clean uppercase strings, dedup preserving order, cap at 3
        raw_tickers = check.get("tickers") if isinstance(check.get("tickers"), list) else []
        seen = set()
        tickers = []
        for t in raw_tickers:
            if not isinstance(t, str):
                continue
            t = t.strip().upper()
            if t and t not in seen:
                seen.add(t)
                tickers.append(t)
        check["tickers"] = tickers[:3]
        if "company_name" not in check or not isinstance(check["company_name"], str):
            check["company_name"] = ""
        if not isinstance(check.get("q3"), dict):
            check["q3"] = {"needed": "N", "sector": "", "country": None}
    except Exception:
        check = _empty

    return {"financial_check": check}


# ── Node 1c: fetch_financial_data ─────────────────────────────────────────────

def fetch_financial_data(state: CompanyInfoState) -> dict:
    """
    Resolve tickers (multi) and fetch financial data for each, per requested tools.
    Skipped entirely (via conditional edge) when Q1=N or Q2=[].

    Resolution order:
      1. `tickers` list from check_financial_need — direct path, only format-validated
         tickers used (Haiku occasionally still slips a name in here)
      2. If no valid direct tickers AND `company_name` is set — single-name fallback
         via resolve_ticker (existing Haiku #2 normalizer path)

    Output shape:
        {"GME": {tool_id: data, ...}, "EBAY": {...}, "_resolve_failed": [names]}
    or, when nothing resolves:
        {"_ticker_error": "...", "_resolve_failed": [...]}
    """
    from utils.financial_tools import (
        _is_valid_ticker_format, fetch_all, resolve_ticker,
    )

    check = state["financial_check"]
    tools = check.get("q2", [])

    # ── 1. Direct tickers from check_financial_need ───────────────────────────
    direct = check.get("tickers", []) or []
    resolved: list[str] = []
    rejected_direct: list[str] = []
    for t in direct:
        if _is_valid_ticker_format(t):
            resolved.append(t.upper())
        else:
            rejected_direct.append(t)
    for r in rejected_direct:
        print(f"[financial_tools] ⚠ rejecting direct ticker {r!r} (bad format)")

    # ── 2. Fallback: resolve company_name when no valid direct ticker ─────────
    failed_names: list[str] = []
    if not resolved:
        name = (check.get("company_name") or "").strip()
        if not name:
            # Last-ditch: prefix of task instruction (matches legacy behavior)
            name = state["task_instruction"][:40]
        print(f"[financial_tools] 解析 ticker：{name}…")
        sym = resolve_ticker(name, task_context=state["task_instruction"])
        if sym:
            resolved.append(sym)
        else:
            failed_names.append(name)

    if not resolved:
        print("[financial_tools] ⚠ 找不到對應 ticker，跳過財務資料抓取")
        err = f"ticker resolution failed; direct={direct!r}, name={check.get('company_name')!r}"
        return {"financial_data": {"_ticker_error": err, "_resolve_failed": failed_names}}

    # ── 3. Fetch all tools for each resolved ticker ──────────────────────────
    print(f"[financial_tools] fetching {len(tools)} tools × {len(resolved)} tickers: {resolved}")
    data: dict = {}
    for symbol in resolved:
        print(f"[financial_tools] ticker = {symbol}，抓取：{tools}")
        payload = fetch_all(symbol, tools)
        # fetch_all puts the symbol under "ticker" — redundant when top-level key already is the ticker
        payload.pop("ticker", None)
        data[symbol] = payload
    if failed_names:
        data["_resolve_failed"] = failed_names
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


# ── Node 2b: extract_numbers ──────────────────────────────────────────────────

def extract_numbers_node(state: CompanyInfoState) -> dict:
    """
    After the ReAct loop finishes, run Haiku to echo all task-relevant numbers
    from the evidence pool, then convert deterministically to Chinese strings
    via utils/unit_convert. The synthesizer is then told to echo those strings
    verbatim — removing LLM from the unit-conversion step.
    """
    from utils.number_extract import extract_numbers

    items, numbers_zh = extract_numbers(
        task_instruction=state["task_instruction"],
        evidence=state.get("evidence", []),
    )
    return {"number_items": items, "numbers_zh": numbers_zh}


# ── Node 3: generate_report ───────────────────────────────────────────────────

def generate_report(state: CompanyInfoState) -> dict:
    """
    Use claude-opus to synthesize search results into a structured JSON report.
    Schema (sections and types) is decided dynamically by the model.
    """
    client = _get_client()

    # Flatten search results into readable context.
    # Prefer Tavily-extracted full text when available; fall back to snippet.
    context_parts = []
    for entry in state["search_results"]:
        context_parts.append(f"[搜尋：{entry['query']}]")
        for r in entry["results"]:
            context_parts.append(f"來源：{r['title']} ({r['url']})")
            context_parts.append(r.get("full_content") or r["content"])
            context_parts.append("")

    import json as _json
    fin = state.get("financial_data") or {}
    # Top-level keys are tickers (uppercase); meta keys are prefixed with "_".
    ticker_keys = [k for k in fin.keys() if not k.startswith("_")]
    for ticker in ticker_keys:
        context_parts.append(f"[結構化財務資料 — {ticker}（來自 yfinance）]")
        context_parts.append(_json.dumps(fin[ticker], ensure_ascii=False, default=str))
        context_parts.append("")

    sec = state.get("sector_data") or {}
    if sec and "companies" in sec:
        context_parts.append("[產業公司清單（來自 FinanceDatabase）]")
        context_parts.append(_json.dumps(sec, ensure_ascii=False, default=str))
        context_parts.append("")

    from utils.number_extract import format_for_prompt
    numbers_block = format_for_prompt(state.get("numbers_zh") or {})
    if numbers_block:
        context_parts.append(numbers_block)
        context_parts.append("")

    context = "\n".join(context_parts)

    mode = state.get("mode", "short")
    if mode == "short":
        mode_rules = """\
10. 【Short 模式】嚴格依照任務指令範圍，不延伸、不補充任務未要求的背景資訊
11. 報告結構精簡：1-3 個 section，每個 bullets section 最多 6 條，paragraph 最多 150 字
12. 目標篇幅約兩頁，寧可少寫也不要湊字數"""
    else:
        mode_rules = """\
10. 【Medium 模式】可適度補充相關背景與延伸分析，section 數量不限
11. 確保資訊完整、分析深度足夠"""

    prompt = f"""{config.time_context()}

你是 FCC Partners 的商業研究助理。根據搜尋資料，針對以下任務產出一份繁體中文報告。

任務指令：{state['task_instruction']}

搜尋資料：
{context}

輸出規則：
1. 回傳純 JSON，不要 markdown 包裝
2. sections 的數量和名稱由你根據任務指令決定，不要硬套固定格式
3. 每個 section 選擇最適合的呈現方式：
   - type "bullets"：適合事實性、條列式資訊（用 items 陣列）
   - type "paragraph"：適合分析性、敘述性內容（用 content 字串）
   - type "table"：適合多筆同結構數值、比較性資料（用 headers 陣列 + rows 二維陣列）；例如：財務指標比較、多公司對照、歷年數據
4. 語言：繁體中文，保留英文專有名詞（公司名、人名、產品名）；不要在任何名詞後加括號標注其他語言的原文或譯名（例如不要寫「環球集團（Global Group）」或「芽莊（Nha Trang）」，直接寫名稱本身）
5. 精簡準確，不要堆砌廢話；不要在報告內容中提及任務指令的措辭、比喻或身份設定（例如不要出現「類似麥肯錫」、「根據您的要求」等）
6. 財務數字優先採用結構化財務資料（yfinance）；Tavily 的財務數字僅作為背景參考，若與結構化資料矛盾，以結構化資料為準。**引用 yfinance 數字時必須附資料日期**（股價用 `as_of` 欄位，例如「截至 2026-05-07」；財報數字用 `period_end` 欄位，例如「2026 Q1（截至 2026-03-31）」）。**多家公司情境**：context 可能有多個 `[結構化財務資料 — TICKER]` 區塊（如 M&A 雙方），每個區塊對應一家公司的 yfinance 資料，引用時務必指明是哪一家的數字（例：「GME 市值 103.9 億美元（截至 2026-05-11）」），不可混淆來源
7. **絕對禁止免責聲明**：不得出現「僅供參考」「請以官方公告為準」「資料可能有誤」「本報告基於公開資料」「無法保證準確性」或任何類似的 hedge / disclaimer 語句。FCC 內部研究文件不需要這些，直接陳述事實即可
8. **禁用空洞修辭** — 任務若涉及數字 / 規模 / 排名 / 市占，必須給具體數值、金額或來源；evidence 沒有就明寫「資料不足」，不得用形容詞替代：
   - 禁用：「成長雙位數」「顯著成長」「大幅提升」「快速擴張」「高速增長」 → 必須給 % 或金額
   - 禁用：「重要環節」「戰略佈局」「核心競爭力」「關鍵角色」 → 必須說「做什麼產品 / 服務什麼客戶 / 在哪一段價值鏈」
   - 禁用：「行業領先」「市場領導者」「龍頭」 → 必須附市占率、營收排名或來源
   - 禁用：「持續優化」「不斷精進」「全方位」「一站式」 → 直接刪掉這類無資訊量副詞
9. **【結構化數字 echo 規則】**：若 context 內有「[結構化數字]」區塊，**該區塊的中文字串已是最終格式**，報告中提及對應金額 / 百分比 / 倍數時必須**逐字 echo**，禁止：
   - 改寫數值（例如把「94 億美元」寫成「約 90 億美元」「9.4 億美元」「9,400 萬美元」）
   - 重新做單位換算（不要把 "$9.4 billion" 自己翻譯，直接用區塊裡的 "94 億美元"）
   - 用「約」「大約」「近」「逾」「超過」等模糊化前綴包裹（除非 evidence 本身就有這些字）
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
    }},
    {{
      "heading": "節標題",
      "type": "table",
      "headers": ["欄位一", "欄位二", "欄位三"],
      "rows": [["A1", "A2", "A3"], ["B1", "B2", "B3"]]
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
        elif section["type"] == "table":
            builder.add_table(section.get("headers", []), section.get("rows", []))
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
    if state.get("number_items"):
        logger.add_extracted_numbers(state["number_items"])
    log_path = logger.save(output_path)

    return {
        "output_path": str(output_path),
        "log_path": str(log_path),
    }


# ── Graph ─────────────────────────────────────────────────────────────────────

def build_graph():
    graph = StateGraph(CompanyInfoState)

    # ── Nodes ──────────────────────────────────────────────────────────────────
    graph.add_node("parse_task",           parse_task)
    graph.add_node("check_financial_need", check_financial_need)
    graph.add_node("fetch_financial_data", fetch_financial_data)
    graph.add_node("fetch_sector_data",    fetch_sector_data)
    graph.add_node("run_search",           run_search)       # initial batch
    graph.add_node("evaluate",             evaluate)         # ReAct: assess progress
    graph.add_node("next_action",          next_action)      # ReAct: plan next query
    graph.add_node("execute_search",       execute_search)   # ReAct: run one query
    graph.add_node("extract_numbers",      extract_numbers_node)  # Haiku echo → Python convert
    graph.add_node("generate_report",      generate_report)
    graph.add_node("format_output",        format_output)

    # ── Edges ──────────────────────────────────────────────────────────────────
    graph.set_entry_point("parse_task")

    # Financial data (unchanged)
    graph.add_edge("parse_task", "check_financial_need")
    graph.add_conditional_edges(
        "check_financial_need",
        lambda s: "fetch" if s["financial_check"].get("q2") else "skip",
        {"fetch": "fetch_financial_data", "skip": "fetch_sector_data"},
    )
    graph.add_edge("fetch_financial_data", "fetch_sector_data")

    # Initial search batch → first evaluate
    graph.add_edge("fetch_sector_data", "run_search")
    graph.add_edge("run_search",        "evaluate")

    # ReAct loop: evaluate → next_action → execute_search → evaluate (or done)
    graph.add_conditional_edges(
        "evaluate",
        _should_continue,
        {"loop": "next_action", "done": "extract_numbers"},
    )
    graph.add_edge("next_action",     "execute_search")
    graph.add_edge("execute_search",  "evaluate")
    graph.add_edge("extract_numbers", "generate_report")

    # Final synthesis
    graph.add_edge("generate_report", "format_output")
    graph.add_edge("format_output",   END)

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
        "todos":          [],
        "evidence":       [],
        "round":          0,
        "search_queries": [],
        "search_results": [],
        "financial_check": {},
        "financial_data": {},
        "sector_data": {},
        "number_items": [],
        "numbers_zh": {},
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
