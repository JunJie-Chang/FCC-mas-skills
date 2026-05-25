"""
utils/number_extract.py — Haiku-driven verbatim number extractor.

Pipeline (treats LLM unit conversion as a known failure mode):
    1. Haiku reads evidence + task instruction, ECHOES every relevant number with
       its raw text, value, scale word, and currency. NO arithmetic, NO Chinese
       translation, NO inferring unspoken units.
    2. utils/unit_convert.to_chinese_amount() converts (value, scale, currency)
       deterministically to canonical Chinese strings.
    3. The result `numbers_zh: dict[label, "XX 億美元"]` is injected into the
       synthesizer prompt and the synthesizer is instructed to echo the strings
       verbatim — never to recompute.

Why two-step LLM→Python rather than one-step LLM:
    The bug in #8 (GameStop/eBay report writing "9.4 億" for "$9.4 billion") is the
    synthesis LLM dropping a digit during long-form Chinese generation. Narrow echo
    + deterministic Python conversion removes LLM from the conversion step entirely.
"""
import json
import os
import re
from typing import Optional

from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv(override=True)

import config
from utils.unit_convert import (
    CURRENCY_ZH,
    SCALE_MULTIPLIERS,
    to_chinese_amount,
)

# Cap on evidence text fed to Haiku. Generous because Haiku is cheap and missing a
# number is worse than spending an extra cent.
_EVIDENCE_CHAR_CAP = 50000


def _get_client() -> Anthropic:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise EnvironmentError("ANTHROPIC_API_KEY not set in .env")
    return Anthropic(api_key=api_key)


def _parse_json(text: str):
    """
    Robust JSON-array extraction. Handles three Haiku failure modes:
      1. Wrapped in ```json ... ``` fences
      2. Leading / trailing prose around the array
      3. Trailing junk after the array (e.g. an explanation object) — the
         original regex captured `{...} ... {...}` together and choked.

    Strategy: strip fences, then walk from the first `[` (preferred) or `{`
    using JSONDecoder.raw_decode, which parses one complete JSON value and
    stops — trailing content is ignored. Prefers arrays since this module
    always asks for an array.
    """
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text).strip()

    def _unwrap(obj):
        """If Haiku wrapped the array in {"items": [...]} or similar, peel it."""
        if isinstance(obj, dict):
            for key in ("items", "numbers", "data", "result"):
                if isinstance(obj.get(key), list):
                    return obj[key]
        return obj

    # 1. Direct parse — common happy path.
    try:
        return _unwrap(json.loads(text))
    except json.JSONDecodeError:
        pass

    decoder = json.JSONDecoder()

    # 2. Prefer the first `[` — this module always asks for an array.
    idx = text.find("[")
    if idx >= 0:
        try:
            obj, _ = decoder.raw_decode(text[idx:])
            return obj
        except json.JSONDecodeError:
            # 2b. Array open but malformed (most common cause: max_tokens cut
            #     mid-array). Walk forward collecting one complete `{...}` at
            #     a time with raw_decode; stop when no more parse. This salvages
            #     truncated responses.
            salvaged: list = []
            i = idx + 1
            while i < len(text):
                next_brace = text.find("{", i)
                if next_brace < 0:
                    break
                try:
                    obj, end = decoder.raw_decode(text[next_brace:])
                    salvaged.append(obj)
                    i = next_brace + end
                except json.JSONDecodeError:
                    break
            if salvaged:
                print(f"[number_extract] (salvaged {len(salvaged)} items from truncated array)")
                return salvaged

    # 3. Fall back to the first `{` (e.g. Haiku wrapped result in {"items":[...]}).
    idx = text.find("{")
    if idx >= 0:
        obj, _ = decoder.raw_decode(text[idx:])
        return _unwrap(obj)

    raise json.JSONDecodeError("No JSON array or object found", text, 0)


def _flatten_evidence(evidence: list[dict]) -> str:
    """Concatenate Tavily full_content (preferred) or snippet for each search result."""
    parts: list[str] = []
    for e in evidence:
        parts.append(f"[搜尋：{e.get('query', '')}]")
        for r in e.get("results", []):
            body = r.get("full_content") or r.get("content") or ""
            parts.append(f"來源：{r.get('title', '')}")
            parts.append(body)
            parts.append("")
    return "\n".join(parts)[:_EVIDENCE_CHAR_CAP]


def extract_numbers(
    task_instruction: str,
    evidence: list[dict],
    task_subject: str = "",
) -> tuple[list[dict], dict[str, str]]:
    """
    Args:
        task_instruction: Full instruction text (used both for subject inference
                          and label naming).
        evidence:         Tavily search batches; full_content preferred over snippet.
        task_subject:     Optional high-confidence subject hint (e.g. "GME / EBAY"
                          for an M&A task, or "佰維存儲" for a single-company task).
                          When set, the Haiku prompt is anchored on this string;
                          when empty, Haiku must infer the subject from the
                          instruction itself.

    Returns:
        items:        Raw Haiku echo list — preserved for .log sidecar / debugging.
        numbers_zh:   Canonical Chinese strings keyed by Haiku-assigned label.
                      The synthesizer prompt should embed this dict and require
                      verbatim echo of its values.
    """
    if not evidence:
        return [], {}

    context = _flatten_evidence(evidence)
    if not context.strip():
        return [], {}

    scale_keys = ", ".join(sorted(SCALE_MULTIPLIERS.keys()))
    currency_keys = ", ".join(sorted(CURRENCY_ZH.keys()))

    # Subject anchor: anchor explicitly when the caller has high-confidence
    # subject info; otherwise instruct Haiku to infer subject from instruction
    # and apply the same off-topic filter.
    if task_subject.strip():
        subject_block = (
            f"任務主角（caller 已確認）：{task_subject.strip()}\n"
            "→ 只抽取明確屬於這個主角的數字；其他公司 / 機構的數字一律 drop。"
        )
    else:
        subject_block = (
            "任務主角：請從任務指令辨識主角（公司 / 人物 / 機構 / 概念）。\n"
            "→ 只抽取明確屬於該主角的數字；其他公司 / 機構的數字一律 drop。"
        )

    prompt = f"""你是數字抽取助理。從下方 evidence 中，**逐字 echo** 與任務主角相關的數字（金額、百分比、倍數），不做任何計算、不轉換單位、不翻譯成中文。

任務指令：{task_instruction}

{subject_block}

【硬規則】
0. **主角過濾（最優先）**：每個 candidate 數字都要先回答「這個數字是不是在講主角？」
   - evidence 內常出現其他公司的廣告 / 推薦欄 / 同產業對照 / 完全不相關但 Tavily 撈進來的新聞
   - 即使數字本身完整、量級驚人、敘述清楚，**只要主體不是任務主角，一律 drop**
   - 例 1：任務主角 = 智伸科（越南廠），evidence 提到 Lite-On 在越南投資 1.49 億美元 → **drop**（Lite-On 不是主角）
   - 例 2：任務主角 = 佰維存儲，evidence 提到 BayREN 灣區能源組織節省 166 百萬噸碳 → **drop**（不同實體）
   - 例 3：任務主角 = 智帆風能，evidence 提到公牛集團（Goneo）營收 168.31 億人民幣 → **drop**（公牛是插座廠，與風能無關）
   - 例 4：任務主角 = 巨漢系統科技，evidence 提到漢氏雷射（Han's Laser）營收 162 億人民幣 → **drop**（名字相似但不同公司）
   - 不確定主體是不是主角 → drop，**寧缺勿濫**
   - label 命名必須清楚標明主角，不要用 `revenue_2025` 這種任何公司都可套用的 key；用 `<subject>_revenue_2025` 形式

1. **只 echo，不計算、不換算**：value 直接用原文寫的數字；scale 用對應的單位字。對照表：

   原文寫                              → value, scale
   ──────────────────────────────────────────────────────────────────────
   英文 "$9.4 billion"                  → value=9.4,  scale="billion"
   英文 "$1.5 trillion"                 → value=1.5,  scale="trillion"
   英文 "$500 million"                  → value=500,  scale="million"
   財報「NT$99,864,187 thousand」        → value=99864187, scale="thousand"  ← 財報「仟元」慣例
   財報「in thousands」/「仟元」單位      → scale="thousand"                  ← 同上
   中文「9.4 億美元」「140 億新台幣」    → scale="hundred_million"   ← 中文「億」
   中文「8.67 亿元」「34.25 亿元」       → scale="hundred_million"   ← 簡體「亿」也是
   中文「1.5 兆人民幣」「5.2 兆新台幣」  → scale="trillion"           ← 中文「兆」
   中文「1.4 萬」「934.26 萬股」         → scale="ten_thousand"       ← 中文「萬」
   中文純數字「2,510 億」（無幣別）      → value=2510, scale="hundred_million", currency=null
   百分比「46%」「年增 56.52%」          → scale="percent", currency=null
   倍數「3.8 倍」「1.5x」                → scale="ratio",   currency=null

   ⚠ 台股 / 港股財報（年報、季報、損益表、資產負債表、現金流量表）一律以
   「仟元」/「in thousands」/「NT$ thousands」為單位。看到數字後綴 thousand、
   或表頭標明 in thousands / 仟元，**必須 echo scale="thousand"**，絕對不可
   當成 plain。把「NT$99,864,187 thousand」echo 成 scale="plain" 會被下游算
   成「9,986 萬」（正解是 998.6 億），這是與 #8 / #16 同源的 1000× 漏算 bug。

2. **絕對禁止：把中文「億」echo 成 scale="billion"**
   中文「億」= 1e8，英文 billion = 1e9，差 10 倍。把中文「140 億」echo 成 scale="billion" 會被下游算成「1,400 億」，這是 issue #16 的根因。
   同理：中文「萬」≠ million；中文「兆」= trillion 是對的（量級剛好對）。

3. **貨幣忠實**：currency 只能是 [{currency_keys}] 之一；evidence 沒明寫貨幣別就填 null。
   中文「人民幣 / 元 / 元人民幣 / RMB」→ "CNY"；「新台幣 / NT$」→ "TWD"；「美元 / 美金 / USD / $」→ "USD"；「港幣 / HK$」→ "HKD"。

4. **scale 的 enum**：scale 只能是 [{scale_keys}, percent, ratio] 之一；不確定就用 "plain"。

5. **label 用任務語境命名**：例如併購案的「現金部分」用 `cash_portion`、「總交易金額」用 `deal_value_total`、「溢價」用 `premium_pct`；不要用 number_1 / value_2 這種無意義 key。

6. **同一個數字多次出現**：只 echo 一次（取最早出現位置）。

7. **不確定的數字**：寧可漏掉也不要捏造；evidence 裡找不到的數字一律不寫。

8. **任務無關的廣告 / 推薦欄**：忽略（其他公司數字已在規則 0 涵蓋）。

回傳純 JSON 陣列：
[
  {{"label": "deal_value_total",   "raw": "$56 billion",   "value": 56,    "scale": "billion",         "currency": "USD"}},
  {{"label": "cash_portion_cohen", "raw": "$9.4 billion",  "value": 9.4,   "scale": "billion",         "currency": "USD"}},
  {{"label": "premium_unaffected", "raw": "46%",           "value": 46,    "scale": "percent",         "currency": null}},
  {{"label": "loss_recognized",    "raw": "140 億新台幣",   "value": 140,   "scale": "hundred_million", "currency": "TWD"}},
  {{"label": "net_profit_2025",    "raw": "8.67 亿元",      "value": 8.67,  "scale": "hundred_million", "currency": "CNY"}},
  {{"label": "capex_upper",        "raw": "10 億",          "value": 10,    "scale": "hundred_million", "currency": null}}
]

evidence（前 {_EVIDENCE_CHAR_CAP // 1000}k 字元）：
{context}
"""

    print(f"[number_extract] calling Haiku on {len(evidence)} search batches, {len(context)} chars of context…")
    client = _get_client()
    msg = client.messages.create(
        model=config.LLM_FAST,
        max_tokens=8192,   # M&A / complex tasks easily produce 40+ items; 2048 truncated mid-array
        messages=[{"role": "user", "content": prompt}],
    )
    if msg.stop_reason == "max_tokens":
        print(f"[number_extract] ⚠ Haiku hit max_tokens; response may be truncated")

    from utils.cost_tracker import tracker
    tracker.record_claude(config.LLM_FAST, msg.usage.input_tokens, msg.usage.output_tokens)

    raw_text = msg.content[0].text
    try:
        raw_items = _parse_json(raw_text)
    except Exception as exc:
        print(f"[number_extract] ⚠ Haiku JSON parse failed: {exc}")
        print(f"[number_extract] raw response (first 400 chars): {raw_text[:400]!r}")
        return [], {}

    if not isinstance(raw_items, list):
        print(f"[number_extract] ⚠ Haiku returned non-list (type={type(raw_items).__name__}); first 200 chars: {raw_text[:200]!r}")
        return [], {}

    if not raw_items:
        # Distinguish intentional filtering ("[]" with explanation prose) from
        # a Haiku response that failed to produce any structured output at all.
        # The off-topic filter (rule 0) legitimately returns [] when no number
        # in the evidence belongs to the task subject.
        if "[]" in raw_text[:50]:
            print(f"[number_extract] Haiku returned empty array (all evidence numbers attributed to non-subject entities — filter rule 0 active)")
        else:
            print(f"[number_extract] ⚠ Haiku returned empty array; first 200 chars of raw response: {raw_text[:200]!r}")

    items: list[dict] = []
    numbers_zh: dict[str, str] = {}
    for it in raw_items:
        if not isinstance(it, dict):
            continue
        label = (it.get("label") or "").strip()
        if not label or label in numbers_zh:   # dedup by label
            continue
        try:
            value = float(it["value"])
        except (KeyError, TypeError, ValueError):
            continue
        scale = (it.get("scale") or "plain").strip().lower()
        currency: Optional[str] = it.get("currency")

        try:
            zh = to_chinese_amount(value, scale, currency or "")
        except ValueError:
            continue  # unknown scale — skip silently rather than poison the report

        items.append({**it, "label": label, "zh": zh})
        numbers_zh[label] = zh

    n_raw = len(raw_items)
    n_kept = len(items)
    print(f"[number_extract] Haiku returned {n_raw} items, {n_kept} converted → Chinese (rejected {n_raw - n_kept})")
    return items, numbers_zh


def format_for_prompt(numbers_zh: dict[str, str]) -> str:
    """Render the canonical dict as a block ready to paste into a synthesizer prompt."""
    if not numbers_zh:
        return ""
    lines = ["[結構化數字（已預先轉換為中文最終字串，必須直接 echo）]"]
    for label, zh in numbers_zh.items():
        lines.append(f"- {label}: {zh}")
    return "\n".join(lines)
