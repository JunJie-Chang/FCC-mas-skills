"""
utils/search.py — Tavily search wrapper + extracted-markdown boilerplate filter.

Each agent passes its own `max_results` so the call count stays flexible
and is not hardcoded here.

`strip_extract_boilerplate` is used by both the podcast agent and the
research ReAct loop: Tavily extract returns raw page markdown (nav menus,
footers, link lists, image embeds), and both paths need to strip that
out before feeding the text downstream.
"""
import os
import re
import time
from typing import Optional
from dotenv import load_dotenv

load_dotenv(override=True)

_MAX_RETRIES = 4
_RETRY_DELAY = 3  # seconds between retries


def search(query: str, max_results: int = 3, topic: str = "general") -> list[dict]:
    """
    Run a Tavily search and return a list of result dicts.

    Each result dict contains:
        title   (str)
        url     (str)
        content (str)  — snippet / extracted text
        score   (float)

    Args:
        query:       Search query string.
        max_results: Number of results to return (agent-defined).
        topic:       Tavily search topic — "general" (default) or "news".
                     "news" biases results toward news articles and away
                     from research reports / PDFs; podcast agent passes it.

    Returns:
        List of result dicts, length <= max_results.
    """
    from tavily import TavilyClient

    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        raise EnvironmentError("TAVILY_API_KEY not set in .env")

    last_exc: Exception = RuntimeError("No attempts made")
    for attempt in range(_MAX_RETRIES):
        try:
            client = TavilyClient(api_key=api_key)
            response = client.search(query=query, max_results=max_results, topic=topic)
            results = []
            for r in response.get("results", []):
                results.append({
                    "title":   r.get("title", ""),
                    "url":     r.get("url", ""),
                    "content": r.get("content", ""),
                    "score":   r.get("score", 0.0),
                })
            return results
        except Exception as e:
            last_exc = e
            if attempt < _MAX_RETRIES - 1:
                time.sleep(_RETRY_DELAY)
    print(f"[search] 放棄 query: {query!r}（{_MAX_RETRIES} 次重試都失敗：{last_exc}）")
    raise last_exc


def fetch_full_content(url: str) -> Optional[str]:
    """
    Use Tavily's extract endpoint to pull the full text of a given URL.
    Returns the extracted text, or None on failure.
    """
    from tavily import TavilyClient

    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        raise EnvironmentError("TAVILY_API_KEY not set in .env")

    client = TavilyClient(api_key=api_key)
    try:
        response = client.extract(urls=[url])
        results = response.get("results", [])
        if results:
            return results[0].get("raw_content", "")
        return None
    except Exception:
        return None


def fetch_full_content_parallel(
    urls: list[str],
    max_workers: int = 5,
) -> dict[str, str]:
    """
    Fetch full text for multiple URLs concurrently via Tavily extract.

    Returns a dict mapping URL → extracted text. URLs that fail extraction
    are omitted from the returned dict (caller falls back to snippet).
    Each successful extract records 1 Tavily credit via cost_tracker.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from utils.cost_tracker import tracker

    if not urls:
        return {}

    out: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(fetch_full_content, url): url for url in urls}
        for fut in as_completed(futures):
            url = futures[fut]
            try:
                text = fut.result()
            except Exception:
                text = None
            if text:
                out[url] = text
                tracker.record_tavily(1)
    return out


# ── Boilerplate / navigation filter for Tavily extract output ─────────────────
#
# Tavily extract returns raw page markdown — nav menus, footers, link lists,
# image embeds — not just the article body. These patterns strip that out.
# Shared by podcast_agent (article translation path) and react_loop
# (research evidence path) so both consumers get the same cleaned text.

_MD_IMAGE = re.compile(r'!\[[^\]]*\]\([^)]*\)')
_MD_LINK  = re.compile(r'\[[^\]]*\]\([^)]*\)')

# Matched case-insensitively against short lines (incl. markdown headings)
# to drop recommendation-column / page-chrome sections. Multi-word English
# phrases are used (not bare words like "Related") to avoid hitting real
# article headings.
_BOILERPLATE_TOKENS = (
    "延伸閱讀", "推薦閱讀", "相關文章", "相關新聞", "相關主題", "更多內容",
    "更多報導", "探索更多", "你可能也喜歡", "立即訂閱", "訂閱電子報",
    "免費註冊", "點此", "贊助", "熱門內容", "必讀",
    "sponsored", "advertisement", "sign up", "sign in", "subscribe",
    "more from", "most popular", "most read", "most viewed",
    "trending now", "top stories",
    "you may also like", "related stories", "related articles",
    "recommended for you", "explore more", "search query",
)

_SHORT_RUN_MIN    = 5    # this many consecutive short non-sentence lines = a menu
_SHORT_RUN_MAXLEN = 25   # a line counts as "short" at or below this many chars


def _looks_like_navigation(line: str) -> bool:
    """
    True if a line is mostly markdown links / images — i.e. a navigation
    menu item, link list, or image embed rather than article prose. A real
    paragraph that merely contains an inline link keeps plenty of residual
    text and is not flagged. Markdown is stripped repeatedly so nested
    constructs like [![Image](img)](link) are fully removed.
    """
    s = line.strip()
    if not s or not (_MD_LINK.search(s) or _MD_IMAGE.search(s)):
        return False
    residue = s
    for _ in range(5):
        new = _MD_LINK.sub("", _MD_IMAGE.sub("", residue))
        if new == residue:
            break
        residue = new
    residue = re.sub(r'https?://\S+', "", residue)             # orphan URL fragments
    residue = re.sub(r'[\d.\s•\-*|>·\[\]()]+', "", residue)    # markers / leftovers
    return len(residue) <= 8


def _is_short_menu_line(s: str) -> bool:
    """A short, non-sentence, non-structural line — likely a button / menu item."""
    if not s or len(s) > _SHORT_RUN_MAXLEN:
        return False
    if s[0] in "*-#>":                      # markdown bullet / heading — likely real
        return False
    return not re.search(r'[。！？.!?]$', s)


def strip_extract_boilerplate(text: str) -> tuple[str, int]:
    """
    Drop navigation / link-list / boilerplate from extracted markdown:
      1. lines that are mostly markdown links / images
      2. short lines carrying a boilerplate token (延伸閱讀 / Subscribe / ...)
      3. runs of >=_SHORT_RUN_MIN consecutive short non-sentence lines
         (promo / button menus — caught structurally, language-agnostic)
    Returns (cleaned_text, n_dropped); callers print n_dropped for visibility
    so an over-aggressive filter is noticeable rather than silent.
    """
    if not text:
        return text, 0

    lines = text.split("\n")
    drop = [False] * len(lines)

    for i, line in enumerate(lines):
        s = line.strip()
        if _looks_like_navigation(line):
            drop[i] = True
        elif len(s) <= 40 and any(tok in s.lower() for tok in _BOILERPLATE_TOKENS):
            drop[i] = True

    i = 0
    while i < len(lines):
        if _is_short_menu_line(lines[i].strip()):
            j = i
            while j < len(lines) and _is_short_menu_line(lines[j].strip()):
                j += 1
            if j - i >= _SHORT_RUN_MIN:
                for k in range(i, j):
                    drop[k] = True
            i = j
        else:
            i += 1

    kept = [ln for idx, ln in enumerate(lines) if not drop[idx]]
    return "\n".join(kept), sum(drop)


# ── Self-test ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    """
    Self-test for strip_extract_boilerplate. Covers the three filter rules
    plus negative cases (real article prose must survive). Run with:
        python3.13 utils/search.py
    """
    failures: list[str] = []

    def _check(name: str, cond: bool, detail: str = "") -> None:
        if cond:
            print(f"  ✓ {name}")
        else:
            failures.append(f"{name} — {detail}")
            print(f"  ✗ {name}  {detail}")

    # Rule 1: pure markdown link / image lines are dropped
    nav_input = (
        "[![Logo](https://cdn.example.com/logo.png)](https://example.com/)\n"
        "[首頁](/) [財經](/finance) [科技](/tech)\n"
        "這是真正的文章內文段落，包含了具體的研究數字和分析說明，遠超過 40 字門檻。\n"
    )
    cleaned, dropped = strip_extract_boilerplate(nav_input)
    _check("rule1 nav-link lines dropped", dropped == 2, f"dropped={dropped}")
    _check("rule1 article body survives", "真正的文章內文" in cleaned)

    # Rule 2: short line carrying boilerplate token is dropped
    token_input = (
        "延伸閱讀\n"
        "Subscribe to our newsletter\n"
        "You may also like\n"
        "這段是真實段落，介紹公司的營運策略與毛利率變化，內容超過 40 字應該保留下來才對。\n"
    )
    cleaned, dropped = strip_extract_boilerplate(token_input)
    _check("rule2 boilerplate token lines dropped", dropped == 3, f"dropped={dropped}")
    _check("rule2 long prose survives", "毛利率變化" in cleaned)

    # Rule 3: run of >=5 short non-sentence lines is dropped
    menu_input = (
        "首頁\n"
        "財經\n"
        "科技\n"
        "娛樂\n"
        "體育\n"
        "這是真正的文章開頭，討論半導體產業的最新動態與未來展望，內容遠超過 40 字門檻。\n"
    )
    cleaned, dropped = strip_extract_boilerplate(menu_input)
    _check("rule3 5-line short menu dropped", dropped == 5, f"dropped={dropped}")
    _check("rule3 article body survives", "半導體產業" in cleaned)

    # Rule 2 extension: Chinese / mixed-language heading-style chrome
    # (`### Variety 熱門內容`, `## 必讀`, `## Most Viewed`) observed leaking
    # through on Variety / similar sites — added to tokens so they get caught.
    heading_chrome = (
        "### Variety 熱門內容\n"
        "## 必讀\n"
        "## Most Viewed\n"
        "這段是真實段落，介紹串流平台的整合策略與訂閱模式的變化，字數應該足夠跨過 40 字門檻才對。\n"
    )
    cleaned, dropped = strip_extract_boilerplate(heading_chrome)
    _check("rule2 chinese heading chrome dropped", dropped == 3, f"dropped={dropped}")
    _check("rule2 chinese heading body survives", "整合策略" in cleaned)

    # Negative: real article with no chrome should survive untouched
    article_input = (
        "本文介紹台積電 2026 年第一季的財報，營收達到新台幣 6,000 億元，年增 35%。\n"
        "毛利率為 55%，符合市場預期。\n"
        "資本支出計畫維持 280-300 億美元區間，主要投入 N2 製程量產準備。\n"
    )
    cleaned, dropped = strip_extract_boilerplate(article_input)
    _check("negative real article preserved", dropped == 0, f"dropped={dropped}")

    # Negative: real heading containing the word "Related" should survive
    # (the boilerplate tokens are multi-word phrases, not bare "Related")
    related_input = (
        "# Tariff-Related Risks for Asian Suppliers\n"
        "供應鏈分析指出，美國對中國電子產品的關稅政策正在重塑全球採購策略。\n"
    )
    cleaned, dropped = strip_extract_boilerplate(related_input)
    _check("negative real heading with 'Related' word survives",
           "Tariff-Related Risks" in cleaned and dropped == 0,
           f"dropped={dropped}")

    # Edge: empty input is a no-op
    cleaned, dropped = strip_extract_boilerplate("")
    _check("edge empty input no-op", cleaned == "" and dropped == 0)

    # Edge: nested image-link is recognized as nav
    nested = "[![Image](img.jpg)](https://example.com/post)\n"
    cleaned, dropped = strip_extract_boilerplate(nested)
    _check("edge nested image-link dropped", dropped == 1, f"dropped={dropped}")

    print()
    if failures:
        print(f"FAIL: {len(failures)} case(s) failed")
        for f in failures:
            print(f"  - {f}")
        raise SystemExit(1)
    print("OK: all strip_extract_boilerplate self-test cases pass")
