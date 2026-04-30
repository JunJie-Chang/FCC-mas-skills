"""
utils/react_loop.py — Shared ReAct (plan-and-execute) loop for research agents.

Used by company_info_agent and person_info_agent. Each agent's LangGraph state
must contain: task_instruction, todos, evidence, round, search_queries, search_results.

Node functions are plain callables; agents wrap them in thin typed stubs so that
LangGraph gets the correct TypedDict annotation per agent.

Public API:
    run_initial_search(state)           — executes the initial batch of queries
    next_action(state, max_rounds, search_hint)  — picks the next query
    execute_search(state)               — runs one query, appends to evidence
    evaluate(state)                     — marks todos done / pending / unresolved
    should_continue(state, max_rounds)  — conditional edge: "loop" | "done"

Constants:
    RESULTS_PER_QUERY   — Tavily results per search call (3)
    STALL_ROUNDS        — consecutive empty-result rounds before early exit (2)
"""
import json
import os
import re

from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv(override=True)

import config

RESULTS_PER_QUERY = 3
STALL_ROUNDS      = 2


# ── Internal helpers ──────────────────────────────────────────────────────────

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


# ── Public nodes ──────────────────────────────────────────────────────────────

def run_initial_search(state: dict) -> dict:
    """
    Execute the initial batch of search queries produced by parse_task.
    Seeds both search_results and evidence with the results.
    """
    from utils.search import search
    from utils.cost_tracker import tracker

    all_results = []
    for query in state.get("search_queries", []):
        if not query:
            continue
        results = search(query, max_results=RESULTS_PER_QUERY)
        tracker.record_tavily(1)
        all_results.append({"query": query, "results": results})

    accumulated = list(state.get("evidence", [])) + all_results
    return {"search_results": accumulated, "evidence": accumulated}


def next_action(
    state: dict,
    max_rounds: int = 6,
    search_hint: str = "",
) -> dict:
    """
    Haiku picks the single best next search query given current todos + evidence.
    Returns {"search_queries": [query]} or {"search_queries": []} to signal done.

    Args:
        search_hint: Domain-specific search guidance injected into the prompt
                     (e.g. "include stock ticker in every query" for company research).
    """
    client = _get_client()

    pending = [t for t in state["todos"] if t["status"] == "pending"]
    if not pending or state["round"] >= max_rounds:
        return {"search_queries": []}

    evidence_summary = "\n".join(
        f'- [{e["query"]}]: {len(e["results"])} 筆結果'
        for e in state["evidence"]
    ) or "（尚無搜尋記錄）"

    todos_text = "\n".join(
        f'{t["id"]}. [{t["status"]}] {t["question"]} (嘗試 {t["attempts"]} 次)'
        for t in state["todos"]
    )

    hint_block = f"\n搜尋補充說明：{search_hint}" if search_hint else ""

    prompt = f"""你是一個研究助理，正在規劃下一步搜尋。

研究任務：{state['task_instruction']}

待確認問題：
{todos_text}

已執行搜尋：
{evidence_summary}

請針對最重要的待確認問題，產出一條新的搜尋查詢（英文或中文皆可）。
搜尋設計原則：搜一手來源（財報、官方公告、商業資料庫、新聞），不要直接搜問題本身。{hint_block}

回傳純 JSON：{{"query": "搜尋字串"}}
若所有問題已有足夠資訊，回傳：{{"query": ""}}
"""

    msg = client.messages.create(
        model=config.LLM_FAST,
        max_tokens=200,
        messages=[{"role": "user", "content": prompt}],
    )
    from utils.cost_tracker import tracker
    tracker.record_claude(config.LLM_FAST, msg.usage.input_tokens, msg.usage.output_tokens)

    try:
        result = _parse_json(msg.content[0].text)
        query = result.get("query", "").strip()
    except Exception:
        query = ""

    return {"search_queries": [query] if query else []}


def execute_search(state: dict) -> dict:
    """
    Run the single query decided by next_action and append the result to evidence.
    Increments round counter unconditionally.
    """
    from utils.search import search
    from utils.cost_tracker import tracker

    queries = state.get("search_queries", [])
    if not queries or not queries[0]:
        return {"round": state["round"] + 1}

    query = queries[0]
    results = search(query, max_results=RESULTS_PER_QUERY)
    tracker.record_tavily(1)

    new_entry  = {"query": query, "results": results}
    accumulated = list(state["evidence"]) + [new_entry]
    return {
        "evidence":       accumulated,
        "search_results": accumulated,
        "round":          state["round"] + 1,
    }


def evaluate(state: dict) -> dict:
    """
    Haiku evaluates each todo against the accumulated evidence and updates status:
      - "done"        → evidence contains a usable answer
      - "pending"     → still missing, needs another search round
      - "unresolved"  → attempted ≥2 times with no result, give up
    """
    client = _get_client()

    context_parts = []
    for e in state["evidence"]:
        context_parts.append(f"[搜尋：{e['query']}]")
        for r in e["results"]:
            context_parts.append(f"{r['title']}: {r['content'][:300]}")
    context = "\n".join(context_parts)[:6000]

    todos_json_str = json.dumps(
        [{"id": t["id"], "question": t["question"],
          "status": t["status"], "attempts": t["attempts"]}
         for t in state["todos"]],
        ensure_ascii=False,
    )

    prompt = f"""你是研究進度評估助理。根據目前蒐集到的資料，判斷每個待確認問題是否已有足夠資訊。

待確認問題：
{todos_json_str}

蒐集到的資料摘要（前 6000 字）：
{context}

規則：
- "done"：資料中有明確、具體的回答（不需要完美，有方向即可）
- "pending"：資料不足，還需要搜尋
- "unresolved"：嘗試 2 次以上仍無資訊，放棄（報告中以「資料不足」處理）

回傳純 JSON 陣列，每個元素含 id 和新的 status（attempts 不需要回傳）：
[{{"id": 1, "status": "done"}}, {{"id": 2, "status": "pending"}}, ...]
"""

    msg = client.messages.create(
        model=config.LLM_FAST,
        max_tokens=400,
        messages=[{"role": "user", "content": prompt}],
    )
    from utils.cost_tracker import tracker
    tracker.record_claude(config.LLM_FAST, msg.usage.input_tokens, msg.usage.output_tokens)

    try:
        updates    = _parse_json(msg.content[0].text)
        update_map = {u["id"]: u["status"] for u in updates}
    except Exception:
        update_map = {}

    updated_todos = []
    for t in state["todos"]:
        new_status   = update_map.get(t["id"], t["status"])
        new_attempts = t["attempts"] + (1 if new_status == "pending" else 0)
        if new_attempts >= 2 and new_status == "pending":
            new_status = "unresolved"
        updated_todos.append({**t, "status": new_status, "attempts": new_attempts})

    return {"todos": updated_todos}


def should_continue(state: dict, max_rounds: int = 6) -> str:
    """
    Conditional edge function for LangGraph.
    Returns "loop" to run another search round, or "done" to proceed to report.

    Exit conditions:
      - round >= max_rounds (hard cap)
      - no todos remain in "pending" status
      - last STALL_ROUNDS rounds all returned 0 results (stall detection)
    """
    if state["round"] >= max_rounds:
        return "done"
    pending = [t for t in state["todos"] if t["status"] == "pending"]
    if not pending:
        return "done"
    recent = state["evidence"][-STALL_ROUNDS:] if len(state["evidence"]) >= STALL_ROUNDS else []
    if recent and all(len(e["results"]) == 0 for e in recent):
        return "done"
    return "loop"
