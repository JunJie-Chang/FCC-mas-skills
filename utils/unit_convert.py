"""
utils/unit_convert.py — Deterministic numeric → Chinese-string conversion.

Pure Python, no LLM. Turns (value, scale, currency) triples into canonical
Chinese strings (e.g. "$9.4 billion" → "94 億美元") so report writers echo a
correct string instead of recomputing unit conversions by hand.

Conversion rules (deterministic):
    value × scale_multiplier → base units of currency
    base < 1e4      → "{N:,} {currency_zh}"           e.g. "5,000 美元"
    1e4  ≤ b < 1e8  → "{b/1e4} 萬{currency_zh}"       e.g. "100 萬美元"  ($1M)
    1e8  ≤ b < 1e12 → "{b/1e8} 億{currency_zh}"       e.g. "90 億美元"   ($9B)
    1e12 ≤ b        → "{b/1e12} 兆{currency_zh}"      e.g. "1.5 兆美元"  ($1.5T)

Percent and ratio passthroughs:
    scale == "percent" → "{value}%"
    scale == "ratio"   → echo raw (e.g. "1.2x")

Chinese-unit scales (added per #16 — symmetric to issue #8's English-unit case):
    "ten_thousand"    = 1e4   for 中文「萬」
    "hundred_million" = 1e8   for 中文「億」（注意：≠ 英文 billion=1e9）
    "trillion"        = 1e12  for 中文「兆」、英文 trillion 共用
"""

# Scale word → base-unit multiplier.
# Note: Chinese scales (ten_thousand / hundred_million) intentionally listed
# alongside English ones; they convert to the same base units, but echoing
# Chinese 億 as scale="hundred_million" rather than "billion" prevents the
# 10× inflation bug where Haiku would map 中文「億」 → English "billion" (1e9).
SCALE_MULTIPLIERS: dict[str, float] = {
    "plain":           1.0,
    "ten_thousand":    1e4,    # 中文「萬」
    "thousand":        1e3,
    "million":         1e6,
    "hundred_million": 1e8,    # 中文「億」(NOT English billion)
    "billion":         1e9,
    "trillion":        1e12,   # 中文「兆」/ English trillion
}

# Currency ISO / symbol / alias → Chinese name.
CURRENCY_ZH: dict[str, str] = {
    "USD": "美元",
    "TWD": "新台幣",
    "NTD": "新台幣",
    "HKD": "港幣",
    "CNY": "人民幣",
    "RMB": "人民幣",
    "JPY": "日圓",
    "EUR": "歐元",
    "GBP": "英鎊",
    "KRW": "韓元",
    "SGD": "新加坡元",
}


def _fmt_num(x: float) -> str:
    """
    Format a float for Chinese amount display:
      - integer-ish → "1,234"
      - one decimal → "9.4"
      - two decimals → "1.23"
    """
    if abs(x - round(x)) < 0.005:
        return f"{round(x):,}"
    if abs(x * 10 - round(x * 10)) < 0.05:
        return f"{x:.1f}"
    return f"{x:.2f}"


def to_chinese_amount(value: float, scale: str, currency: str) -> str:
    """
    Deterministic conversion: (value, scale, currency) → canonical Chinese string.

    Args:
        value:    Raw numeric value as it appears in the source (e.g. 9.4 for "$9.4 billion").
        scale:    One of SCALE_MULTIPLIERS keys, or "percent", or "ratio".
        currency: ISO code (USD/TWD/HKD/CNY/JPY/EUR/...) or empty string when scale=="percent".

    Returns:
        Canonical Chinese string suitable for direct echo in the final report.
        Returns the raw string-form of inputs if conversion fails (caller should log).
    """
    scale = (scale or "plain").lower()

    if scale == "percent":
        return f"{_fmt_num(float(value))}%"
    if scale == "ratio":
        return f"{_fmt_num(float(value))}x"

    mult = SCALE_MULTIPLIERS.get(scale)
    if mult is None:
        raise ValueError(f"unknown scale: {scale!r}")

    base = float(value) * mult
    zh_curr = CURRENCY_ZH.get((currency or "").upper(), currency or "")

    if base >= 1e12:
        return f"{_fmt_num(base / 1e12)} 兆{zh_curr}"
    if base >= 1e8:
        return f"{_fmt_num(base / 1e8)} 億{zh_curr}"
    if base >= 1e4:
        return f"{_fmt_num(base / 1e4)} 萬{zh_curr}"
    return f"{_fmt_num(base)} {zh_curr}".rstrip()


# ── Self-test ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    cases = [
        # GameStop/eBay case — the original #8 bug (English billion → 億)
        ((56,  "billion",  "USD"), "560 億美元"),
        ((9,   "billion",  "USD"), "90 億美元"),
        ((9.4, "billion",  "USD"), "94 億美元"),
        # Other dollar magnitudes
        ((1,   "million",  "USD"), "100 萬美元"),
        ((1.5, "trillion", "USD"), "1.5 兆美元"),
        ((500, "million",  "USD"), "5 億美元"),
        # Taiwan dollars
        ((5.2, "trillion", "TWD"), "5.2 兆新台幣"),
        ((2.3, "billion",  "TWD"), "23 億新台幣"),
        # Plain numbers (no scale word — already in base units)
        ((5000, "plain",   "USD"), "5,000 美元"),
        ((50000,"plain",   "USD"), "5 萬美元"),
        # Percent passthrough
        ((46,  "percent",  ""),    "46%"),
        ((21.7,"percent",  ""),    "21.7%"),
        # Ratio passthrough
        ((1.2, "ratio",    ""),    "1.2x"),
        # Chinese-unit cases (issue #16 — symmetric to #8)
        # 「億」 must NOT be treated as English billion — these would produce 10× wrong values
        # if Haiku echoed scale="billion" instead of "hundred_million":
        ((140,    "hundred_million", "TWD"), "140 億新台幣"),       # 國泰金 Mayapada 損失
        ((8.67,   "hundred_million", "CNY"), "8.67 億人民幣"),      # 佰維存儲 2025 淨利
        ((112.96, "hundred_million", "CNY"), "112.96 億人民幣"),    # 佰維存儲 2025 營收
        ((34.25,  "hundred_million", "CNY"), "34.25 億人民幣"),     # 佰維 Q4 營收下緣
        ((6174,   "hundred_million", "TWD"), "6,174 億新台幣"),     # 國壽股東權益 (邊界：保持億，不進兆)
        # 「兆」 — both Chinese 兆 and English trillion share scale="trillion"
        ((1.43,   "trillion",        "CNY"), "1.43 兆人民幣"),      # 工業富聯市值
        ((0.6174, "trillion",        "TWD"), "6,174 億新台幣"),     # 同上換 scale 仍應同字串
        # 「萬」
        ((1.4,    "ten_thousand",    ""),    "1.4 萬"),
        ((934.26, "ten_thousand",    ""),    "934.26 萬"),
        # 財報「仟元」/「in thousands」 — scale="thousand" (issue: 1000× under-count
        # when Haiku echoed台股財報「NT$X thousand」as scale="plain"). UMC FY2025 actuals:
        ((99864187,  "thousand", "TWD"), "998.64 億新台幣"),    # 營運現金流
        ((110660052, "thousand", "TWD"), "1106.6 億新台幣"),    # 年底現金及約當現金
        ((237553199, "thousand", "TWD"), "2375.53 億新台幣"),   # 合併營收
        ((1000,      "thousand", "USD"), "100 萬美元"),         # 邊界：1,000 仟 = 1M
        # 智伸科 capex case (was: '6 billion' echoed wrong → '60 億人民幣')
        # Correct echo: 中文 "6 億新台幣" → scale="hundred_million", currency="TWD"
        ((6,      "hundred_million", "TWD"), "6 億新台幣"),
        ((10,     "hundred_million", "TWD"), "10 億新台幣"),
    ]

    fails = 0
    for (value, scale, currency), expected in cases:
        got = to_chinese_amount(value, scale, currency)
        status = "✓" if got == expected else "✗"
        if got != expected:
            fails += 1
        print(f"  {status} to_chinese_amount({value}, {scale!r}, {currency!r}) = {got!r}  (expected {expected!r})")

    print()
    print(f"{len(cases) - fails}/{len(cases)} passed" + (f" — {fails} FAILED" if fails else ""))
