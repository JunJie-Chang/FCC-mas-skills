"""
utils/subject_review.py — Post-STT proper-noun review.

Surface STT errors at the source instead of trying to recover from them
downstream. After Whisper transcription, run a single Haiku pass to list
every proper-noun subject the transcript mentions (公司 / 人名 / 機構 /
課程). The user reviews the list and corrects any STT mishears one by
one; corrections are applied as `replace_all` to the transcript before
it's handed to parse_tasks().

Rationale:
  Downstream pipelines (planner / agent / Tavily) can't reliably distinguish
  "資深客" (STT mishear) from a real obscure company name — both look the
  same to them, and the wrong one happily resolves to "台灣檢驗科技 神秘客
  服務". The user, however, recognizes the error instantly. Putting the
  human in the loop at the STT seam is cheaper and more accurate than
  any LLM-side mitigation.

Cost: 1 Haiku call per recording (a few cents).
"""
import json
import os
import re

from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv(override=True)

import config


def extract_subject_mentions(transcript: str) -> list[dict]:
    """
    Use Haiku to extract proper-noun subject mentions from a transcript.

    Returns:
        List of dicts with keys:
            name    — the proper noun as it appears in the transcript
            context — short surrounding snippet (≤30 chars) for jog memory
            suspect — bool, looks like an STT error (rare structure /
                      near-homophone / contextually impossible)
    """
    if not transcript or not transcript.strip():
        return []

    client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    prompt = f"""你是 STT 校稿助理。從以下口述轉錄稿中找出所有專有名詞主體（公司名、人名、機構名、課程／概念名），讓使用者在進入下一階段前確認 STT 有無聽錯。

轉錄稿：
{transcript}

抽取規則：
- 只列「專有名詞」級別的主體，不要列職位、產業詞、地理通名（如「銀行」「政大校長」「印尼」「越南」不算）
- 同一主體在轉錄中出現多次，只列一次（用最完整字面）
- 中文 / 英文人名、公司名、課程名都要列
- 「ticker / 股票代碼」單獨出現時不列（會跟著公司名一起被改）

對每個主體判斷 suspect（是否疑似 STT 錯字）：
- suspect=true 任一條件即觸發：
  - 字面結構奇怪（兩字以下 + 非常見字、組合不像常見命名習慣）
  - 同音字 / 近音字疑慮（例：「資深客」≈「智伸科」、「工業負面」≈「工業富聯」、「智反」≈「智帆」、「郭泰坤」≈「蔡宏圖 / 國泰金」）
  - 違反常識（例如「氣球發電」、相鄰描述對不上）
  - 知名度極低、Google 搜不到合理結果
- suspect=false：字面常見、結構正常、有 ticker 或公司全名輔證、或是廣為人知的實體

context 規則：
- 給該主體在轉錄中**前後各 ~10 字**的 context（合計 ≤30 字，含主體本身）
- 用「...」表示截斷

回傳純 JSON：
[
  {{"name": "巨漢", "context": "...找一家公司叫巨漢 找這個 先不要放...", "suspect": false}},
  {{"name": "工業負面", "context": "...這個老闆是工業負面 是鴻海下面...", "suspect": true}}
]
"""

    message = client.messages.create(
        model=config.LLM_FAST,
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )

    from utils.cost_tracker import tracker
    tracker.record_claude(config.LLM_FAST, message.usage.input_tokens, message.usage.output_tokens)

    text = message.content[0].text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text).strip()

    # Use raw_decode to consume the first JSON array and ignore trailing prose
    decoder = json.JSONDecoder()
    data = None
    for i, ch in enumerate(text):
        if ch == "[":
            try:
                data, _ = decoder.raw_decode(text[i:])
                break
            except json.JSONDecodeError:
                continue
    if not isinstance(data, list):
        return []

    cleaned: list[dict] = []
    seen_names: set[str] = set()
    for item in data:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        if not name or name in seen_names:
            continue
        seen_names.add(name)
        cleaned.append({
            "name":    name,
            "context": str(item.get("context", "")).strip(),
            "suspect": bool(item.get("suspect", False)),
        })
    return cleaned


def review_subjects(transcript: str, mentions: list[dict]) -> str:
    """
    Interactive CLI loop: show mentions, let user correct any. Returns the
    (possibly modified) transcript.

    Commands:
        [N]      — edit mention N; prompts for replacement, replace_all in transcript
        Enter    — accept all, return
    """
    if not mentions:
        return transcript

    while True:
        print()
        print("─" * 70)
        print("  偵測到的主體（請確認 STT 是否聽對）：")
        print("─" * 70)
        for i, m in enumerate(mentions, 1):
            tag = "⚠" if m["suspect"] else " "
            print(f"  {i}. {tag} {m['name']}")
            if m["context"]:
                print(f"        ↳ {m['context']}")
        print("─" * 70)
        print("  [編號]=修改該主體名稱（會 replace all occurrences）  Enter=全部正確，繼續")
        print("─" * 70)

        try:
            raw = input("  > ").strip()
        except EOFError:
            return transcript

        if not raw:
            return transcript

        if not raw.isdigit():
            print("  請輸入數字或 Enter")
            continue

        idx = int(raw) - 1
        if not (0 <= idx < len(mentions)):
            print(f"  無效編號：{raw}")
            continue

        old = mentions[idx]["name"]
        try:
            new = input(f"  「{old}」改成：").strip()
        except EOFError:
            continue

        if not new:
            print("  未輸入，略過。")
            continue
        if new == old:
            print("  新舊相同，未改動。")
            continue

        count = transcript.count(old)
        if count == 0:
            print(f"  ⚠ 在轉錄文中找不到「{old}」，無法 replace（可能已被 normalize）")
            continue

        transcript = transcript.replace(old, new)
        mentions[idx]["name"] = new
        if old in mentions[idx]["context"]:
            mentions[idx]["context"] = mentions[idx]["context"].replace(old, new)
        mentions[idx]["suspect"] = False
        print(f"  ✓ 已 replace（轉錄文中 {count} 處）")
