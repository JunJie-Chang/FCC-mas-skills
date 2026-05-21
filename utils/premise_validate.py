"""
utils/premise_validate.py — Premise + coverage validation between ReAct loop
done and generate_report.

Why this exists:
  The ReAct loop's `evaluate` node only judges "did we search enough" (todo
  done / pending / unresolved). It does NOT judge "did we actually answer
  what CY asked". So:

  - environment Vietnam case (#7): synthesizer paraphrases adjacent evidence
    into "戰略佈局" filler when specific 產能 / 廠址 / 投資金額 numbers are
    missing — because evaluate signed off the search as "done" even though
    deliverables weren't covered.

  - 國泰金 Mayapada case (#19): instruction has declarative premise
    "政大校長介紹". All evidence is silent on this. Synthesizer finds a
    politely-adjacent fact (chairman 陳祖培 graduated from 政大) and
    "迂迴" the answer instead of explicitly saying "資料無法驗證".

Fix shape:
  Insert a `verify` node that asks Haiku to decompose the instruction
  into two lists:

    premises[]     — declarative assertions the user takes as given
                     (must be either confirmed by evidence or explicitly
                      marked unverified in the final report)
    deliverables[] — questions / data points the user wants answered
                     (must be either answered with specific numbers /
                      names / dates, or explicitly marked "資料不足")

  Each entry gets a status grounded in the evidence pool. The result is
  injected into generate_report's prompt with hard rules:

    - unverified premise → must literally write "任務指令所述『X』，本次
      搜尋資料無法驗證" (no paraphrase, no 迂迴)
    - missing deliverable → must literally write "資料不足，無法答覆 X"
      (forbidden: "戰略佈局" / "重要環節" filler)

  This neutralizes synthesizer's training-distribution helpfulness habit
  of "弱連結 sound-adjacent evidence to fill gaps".

Cost: 1 Haiku call per agent run, evidence cap 50k chars.
"""
import json
import os
import re

from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv(override=True)

import config


# ── Constants ─────────────────────────────────────────────────────────────────

_PREMISE_STATUSES = ("confirmed", "partial", "unverified")
_DELIVERABLE_STATUSES = ("answered", "partial", "missing")
_EVIDENCE_CAP = 50_000


# ── Public API ────────────────────────────────────────────────────────────────

def validate(task_instruction: str, evidence: list[dict]) -> dict:
    """
    Decompose instruction into premises + deliverables and stamp each with
    a status grounded in evidence.

    Args:
        task_instruction: the full instruction string passed to the agent
        evidence:         the agent's evidence pool, list of
                          {query, results:[{title,url,content,full_content}, ...]}

    Returns:
        {
          "premises": [
            {"claim": str, "status": "confirmed"|"partial"|"unverified",
             "note": str, "evidence_url": str|None},
            ...
          ],
          "deliverables": [
            {"question": str, "status": "answered"|"partial"|"missing",
             "note": str, "evidence_url": str|None},
            ...
          ],
        }
    """
    if not task_instruction or not task_instruction.strip():
        return {"premises": [], "deliverables": []}

    evidence_text = _flatten_evidence(evidence)

    client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    prompt = f"""{config.time_context()}

你是研究覆蓋度檢查助理。把以下任務指令拆成兩類：
- premises（**斷言**）：使用者預設為真的陳述，需要被 evidence **驗證**
- deliverables（**問題**）：使用者明確要答的點，需要從 evidence 抽**具體數字 / 名稱 / 日期**

然後對每一條，根據 evidence 標 status。

任務指令：
{task_instruction}

Evidence pool（搜尋結果摘要，可能含一手 full_content）：
{evidence_text}

【拆解規則】
- premises 範例：「市值比鴻海高」「投資 4 億美金」「政大校長介紹」「2013 年成立」「公司是鴻海旗下」
- deliverables 範例：「今年漲幅多少」「在 A 股排名第幾」「越南產能多少」「投資地點」「最新一季營收」
- 拆解時若使用者問題涉及「產能 / 規模 / 金額 / 員工數 / 廠址 / 時程 / 產品線 / 排名」，**每一項拆成獨立 deliverable**，不要合併成「基本資料」這種模糊類別
- 一條 instruction 可能只有 premises 沒有 deliverables（純驗證型），或反之。也可能兩者皆有

【premise status】
- confirmed：evidence 明確支持（**必須附 evidence_url**）
- partial：evidence 支持其中一部分（明寫支持哪部分、未確認哪部分）
- unverified：evidence 完全沒提到、或不足以判斷
  - 注意：**禁止用「沾邊但不直接對應」的 evidence 撐起 confirmed**（例如 instruction 說「政大校長介紹」，evidence 只提到「某董事畢業於政大」— 這條 premise 必須是 unverified，不可以是 partial 或 confirmed）

【deliverable status】
- answered：evidence 有具體數字 / 名稱 / 日期可回答（**必須附 evidence_url**）
- partial：找到方向但未抓到具體數值（如知道有越南廠但未抓到產能數字）
- missing：完全沒答案，或只有抽象描述（如「戰略重要」「快速擴張」這類**不算 answered**）

回傳純 JSON：
{{
  "premises": [
    {{"claim": "投資 4 億美金", "status": "partial", "note": "找到 NT$94.27 億 + NT$17 億兩筆加總約 $3.7B USD，量級相符", "evidence_url": "https://..."}},
    {{"claim": "政大校長介紹", "status": "unverified", "note": "evidence 未提及任何政大校長相關事實", "evidence_url": null}}
  ],
  "deliverables": [
    {{"question": "越南投資地點", "status": "answered", "note": "海防市亭武－吉海經濟區 CN4.1H", "evidence_url": "https://..."}},
    {{"question": "越南年產能", "status": "missing", "note": "evidence 中無具體產能數字", "evidence_url": null}}
  ]
}}
"""

    try:
        message = client.messages.create(
            model=config.LLM_FAST,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as exc:
        print(f"[premise_validate] Haiku call failed: {exc}")
        return {"premises": [], "deliverables": []}

    from utils.cost_tracker import tracker
    tracker.record_claude(config.LLM_FAST, message.usage.input_tokens, message.usage.output_tokens)

    text = message.content[0].text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text).strip()

    decoder = json.JSONDecoder()
    data = None
    for i, ch in enumerate(text):
        if ch == "{":
            try:
                data, _ = decoder.raw_decode(text[i:])
                break
            except json.JSONDecodeError:
                continue

    if not isinstance(data, dict):
        return {"premises": [], "deliverables": []}

    premises = _clean_entries(
        data.get("premises") or [], key="claim", valid_statuses=_PREMISE_STATUSES,
    )
    deliverables = _clean_entries(
        data.get("deliverables") or [], key="question", valid_statuses=_DELIVERABLE_STATUSES,
    )
    return {"premises": premises, "deliverables": deliverables}


def format_for_prompt(validation: dict) -> str:
    """
    Render the validation result as a prompt-injection block for
    generate_report. Returns "" when nothing to render.
    """
    if not validation:
        return ""
    premises = validation.get("premises") or []
    deliverables = validation.get("deliverables") or []
    if not premises and not deliverables:
        return ""

    lines = ["[前提驗證 / 覆蓋度檢查 — 從 instruction 拆解後逐條對 evidence 比對]"]

    if premises:
        lines.append("")
        lines.append("Premises（任務指令中的斷言）：")
        for p in premises:
            tag = {"confirmed": "✓", "partial": "△", "unverified": "✗"}.get(p["status"], "?")
            line = f"  {tag} [{p['status']}] {p['claim']}"
            if p.get("note"):
                line += f" — {p['note']}"
            lines.append(line)

    if deliverables:
        lines.append("")
        lines.append("Deliverables（任務指令要回答的問題 / 資料點）：")
        for d in deliverables:
            tag = {"answered": "✓", "partial": "△", "missing": "✗"}.get(d["status"], "?")
            line = f"  {tag} [{d['status']}] {d['question']}"
            if d.get("note"):
                line += f" — {d['note']}"
            lines.append(line)

    return "\n".join(lines)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _flatten_evidence(evidence: list[dict]) -> str:
    """Render evidence pool into a single capped text blob for Haiku."""
    parts: list[str] = []
    for entry in evidence or []:
        if not isinstance(entry, dict):
            continue
        q = entry.get("query", "")
        parts.append(f"[search: {q}]")
        for r in entry.get("results", []) or []:
            title = r.get("title", "")
            url = r.get("url", "")
            content = r.get("full_content") or r.get("content") or ""
            parts.append(f"來源：{title} ({url})")
            parts.append(content)
            parts.append("")
    blob = "\n".join(parts)
    if len(blob) > _EVIDENCE_CAP:
        blob = blob[:_EVIDENCE_CAP] + "\n... [evidence truncated]"
    return blob


def _clean_entries(raw: list, key: str, valid_statuses: tuple) -> list[dict]:
    """Validate and normalize a list of premise / deliverable dicts."""
    out: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        text = str(item.get(key, "")).strip()
        if not text:
            continue
        status = item.get("status", "")
        if status not in valid_statuses:
            # Best-effort coerce
            status = "unverified" if "premise" in (key or "") else "missing"
            if status not in valid_statuses:
                status = valid_statuses[-1]
        out.append({
            key:            text,
            "status":       status,
            "note":         str(item.get("note") or "").strip(),
            "evidence_url": (item.get("evidence_url") or None),
        })
    return out
