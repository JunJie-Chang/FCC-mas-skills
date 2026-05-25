"""
utils/news_publications.py — domain → Chinese publication name lookup.

Used by the podcast agent's snippet / extract-fallback path to fill in
the `publication` metadata field that trafilatura would normally provide
via `sitename`. When trafilatura fails and Tavily snippet / extract is
used, this lookup keeps article subtitles consistent with the
trafilatura-success case.

Coverage: the 38 domains in podcast_agent._NEWS_WHITELIST plus a few
common Tavily-surfaced sites. Long tail (uncommon publications) falls
back to the raw netloc — that is acceptable, since the alternative is
either picking a wrong Chinese name or maintaining an unbounded table.
"""
from urllib.parse import urlparse


DOMAIN_TO_PUBLICATION_ZH: dict[str, str] = {
    # ── 台灣主流 ────────────────────────────────────────────────
    "cna.com.tw":            "中央社",
    "ctee.com.tw":           "工商時報",
    "udn.com":               "聯合新聞網",
    "ltn.com.tw":            "自由時報",
    "chinatimes.com":        "中國時報",
    "ettoday.net":           "ETtoday",
    "bnext.com.tw":          "數位時代",
    "businessweekly.com.tw": "商業周刊",
    "wealth.com.tw":         "財訊",
    "cw.com.tw":             "天下雜誌",
    "gvm.com.tw":            "遠見雜誌",
    "storm.mg":              "風傳媒",
    "moneydj.com":           "MoneyDJ理財網",
    "mirrormedia.mg":        "鏡週刊",
    # ── 台灣產業專業 ────────────────────────────────────────────
    "digitimes.com.tw":      "DIGITIMES",
    "ithome.com.tw":         "iThome",
    "techorange.com":        "TechOrange",
    "inside.com.tw":         "INSIDE",
    "36kr.com":              "36氪",
    # ── 國際中文 ────────────────────────────────────────────────
    "bbc.com":               "BBC",
    "cn.nytimes.com":        "紐約時報中文網",
    "cn.wsj.com":            "華爾街日報中文網",
    "rfa.org":               "自由亞洲電台",
    "voachinese.com":        "美國之音",
    "dw.com":                "德國之聲",
    "caixin.com":            "財新",
    "yicai.com":             "第一財經",
    "21jingji.com":          "21世紀經濟報導",
    # ── 國際英文 ────────────────────────────────────────────────
    "reuters.com":           "路透社",
    "bloomberg.com":         "Bloomberg",
    "ft.com":                "Financial Times",
    "nytimes.com":           "紐約時報",
    "wsj.com":               "華爾街日報",
    "economist.com":         "經濟學人",
    "nikkei.com":            "日本經濟新聞",
    "asia.nikkei.com":       "Nikkei Asia",
    "techcrunch.com":        "TechCrunch",
    "theverge.com":          "The Verge",
    "techinasia.com":        "Tech in Asia",
    "scmp.com":              "南華早報",
    "mingpao.com":           "明報",
    "hk01.com":              "香港01",
    # ── Tavily-frequent (not in podcast whitelist but commonly surfaced) ─
    "investing.com":         "Investing.com",
    "variety.com":           "Variety",
    "cnbc.com":              "CNBC",
    "yahoo.com":              "Yahoo Finance",   # finance.yahoo.com etc.
    "forbes.com":            "Forbes",
    "tradingview.com":       "TradingView",
    "thelec.net":            "TheElec",
    "marketwatch.com":       "MarketWatch",
}


def lookup(url_or_domain: str) -> str:
    """
    Resolve a URL or domain to a Chinese publication name.

    Strips `www.` and any leading subdomain layers progressively until a
    table entry is found or the domain is exhausted. Examples:

      finance.yahoo.com         → "Yahoo Finance"   (matches yahoo.com)
      m.au.investing.com        → "Investing.com"   (matches investing.com)
      news.cna.com.tw           → "中央社"           (matches cna.com.tw)
      some-random-blog.example  → ""                 (no match)

    Returns empty string when no match is found; the caller decides how
    to fall back (usually to the raw netloc).
    """
    if not url_or_domain:
        return ""

    parsed = urlparse(url_or_domain)
    domain = (parsed.netloc or parsed.path or url_or_domain).lower().strip()
    domain = domain.removeprefix("www.")
    # Strip port / trailing slash artifacts
    domain = domain.split("/", 1)[0].split(":", 1)[0]

    while domain:
        if domain in DOMAIN_TO_PUBLICATION_ZH:
            return DOMAIN_TO_PUBLICATION_ZH[domain]
        # Strip leftmost subdomain layer and retry
        if "." not in domain:
            break
        domain = domain.split(".", 1)[1]
    return ""


# ── Self-test ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    """Run with: python3.13 utils/news_publications.py — covers lookup() plus
    utils/search.py's _normalize_pub_date helper (the two pieces of issue #6
    metadata machinery share a single test entry point)."""

    # When invoked as a script (not -m), add project root so `utils.search`
    # imports resolve. This is the same shim agents use.
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    # ── Date normalizer ─────────────────────────────────────────────
    from utils.search import _normalize_pub_date
    date_cases = [
        ("",                                          ""),
        ("2025-03-15",                                "2025-03-15"),
        ("2025-03-15T10:30:00Z",                      "2025-03-15"),
        ("2026-05-18T22:26:09+00:00",                 "2026-05-18"),
        ("Mon, 18 May 2026 22:26:09 GMT",             "2026-05-18"),
        ("Thu, 21 May 2026 20:01:00 GMT",             "2026-05-21"),
        ("not a date",                                ""),
        (None,                                        ""),
    ]
    print("== date normalizer ==")
    date_failures: list[str] = []
    for raw, expected in date_cases:
        got = _normalize_pub_date(raw)
        if got == expected:
            print(f"  ✓ {raw!r:<45} → {got!r}")
        else:
            date_failures.append(f"{raw!r}: expected {expected!r}, got {got!r}")
            print(f"  ✗ {raw!r:<45} → got {got!r}, expected {expected!r}")
    print()

    # ── Domain lookup ───────────────────────────────────────────────
    print("== publication lookup ==")
    cases = [
        # (input, expected)
        ("https://finance.yahoo.com/news/foo.html",      "Yahoo Finance"),
        ("https://m.au.investing.com/news/bar",          "Investing.com"),
        ("https://news.cna.com.tw/news/abc.aspx",        "中央社"),
        ("https://www.cnbc.com/2025/11/07/foo.html",     "CNBC"),
        ("https://www.bbc.com/zh/world",                 "BBC"),
        ("https://cn.nytimes.com/business/article",      "紐約時報中文網"),
        ("https://www.nytimes.com/section/business",     "紐約時報"),  # not the .cn variant
        ("variety.com",                                  "Variety"),
        ("www.36kr.com",                                 "36氪"),
        ("https://store.moneydj.com/article/1",          "MoneyDJ理財網"),
        ("",                                             ""),
        ("https://some-random-blog.example.org/post/1",  ""),
        ("blog.fugle.tw",                                ""),   # not in table
    ]
    failures: list[str] = []
    for url, expected in cases:
        got = lookup(url)
        if got == expected:
            print(f"  ✓ {url or '<empty>':<55} → {got!r}")
        else:
            failures.append(f"{url}: expected {expected!r}, got {got!r}")
            print(f"  ✗ {url:<55} → got {got!r}, expected {expected!r}")
    print()
    total_failures = date_failures + failures
    if total_failures:
        print(f"FAIL: {len(total_failures)} case(s) failed")
        for f in total_failures:
            print(f"  - {f}")
        raise SystemExit(1)
    print(f"OK: all {len(date_cases)} date + {len(cases)} lookup cases pass")
