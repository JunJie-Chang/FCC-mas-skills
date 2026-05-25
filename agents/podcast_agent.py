"""
agents/podcast_agent.py — Podcast research agent using LangGraph.

Flow:
    generate_queries → search_and_fetch → format_output

Output format (matches Works/2026.03.25_K-pop_Podcast拷貝.docx):
  Title:          Podcast：[Topic]             (Bold)
  Q heading:      1. Question text             (Bold, numbered)
  Article title:  Article Title (InternName)   (Bold, red #EE0000)
  Source label:   YYYY.MM.DD PublicationName   (Normal)
  Body:           Full article paragraphs      (Normal)

Cost strategy:
  - 1× LLM_FAST call to generate all search queries in batch
  - Tavily search (N questions × max_results), fetch extra to survive dedup+filter
  - trafilatura scrape full text + metadata (date, title) — zero LLM cost
  - 1× LLM_FAST call per non-Traditional-Chinese article to translate
  - Social media / aggregator domains blocked
  - Global URL dedup across all questions
"""
import json
import os
import re
import sys
from datetime import date
from pathlib import Path
from typing import TypedDict, Union
from urllib.parse import urlparse

from anthropic import Anthropic
from dotenv import load_dotenv
from langgraph.graph import END, StateGraph

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config
from formatters.word_formatter import WordBuilder
from utils.file_naming import general
from utils.logger import AgentLogger
from utils.progress import ProgressCb, emit
from utils.search import fetch_full_content, search, strip_extract_boilerplate

load_dotenv(override=True)

_RESULTS_PER_QUESTION = 3    # final articles per question
_SEARCH_FETCH_EXTRA   = 6    # extra results to fetch to survive filter + dedup
                              # (blocked / pdf-doc / short / dup all eat into this)
_MIN_ARTICLE_CHARS    = 50   # cleaned body must have at least this many chars
                              # (drops only obvious snippet stubs; trust whitelist)

# Social media / video / low-quality domains to skip outright.
# YouTube and LinkedIn live here (was _BLOCKED_HOMEPAGE_DOMAINS) — Podcast
# task only takes text articles, video/social isn't formal enough.
_BLOCKED_DOMAINS = {
    "facebook.com", "fb.com", "twitter.com", "x.com",
    "instagram.com", "tiktok.com",
    "reddit.com", "pinterest.com", "tumblr.com",
    "weibo.com", "weixin.qq.com", "mp.weixin.qq.com",
    "threads.net", "snapchat.com",
    "youtube.com", "youtu.be", "linkedin.com",
}

# News-source whitelist. Articles from these domains are accepted as
# "verified"; anything else is accepted but tagged [unverified_source]
# in the .log so the user can spot-check during proofreading.
_NEWS_WHITELIST = {
    # ── 台灣主流 ─────────────────────────────────────────────────
    "cna.com.tw", "ctee.com.tw", "udn.com", "ltn.com.tw",
    "chinatimes.com", "ettoday.net", "bnext.com.tw",
    "businessweekly.com.tw", "wealth.com.tw", "cw.com.tw",
    "gvm.com.tw", "storm.mg", "moneydj.com", "mirrormedia.mg",
    # ── 台灣產業專業 ─────────────────────────────────────────────
    "digitimes.com.tw", "ithome.com.tw", "techorange.com",
    "inside.com.tw", "36kr.com",
    # ── 國際中文 ─────────────────────────────────────────────────
    "bbc.com", "cn.nytimes.com", "cn.wsj.com",
    "rfa.org", "voachinese.com", "dw.com",
    "caixin.com", "yicai.com", "21jingji.com",
    # ── 國際英文（自動翻譯）──────────────────────────────────────
    "reuters.com", "bloomberg.com", "ft.com", "nytimes.com",
    "wsj.com", "economist.com",
    "nikkei.com", "asia.nikkei.com",
    "techcrunch.com", "theverge.com", "techinasia.com",
    "scmp.com", "mingpao.com", "hk01.com",
}


def _is_whitelisted_news(url: str) -> bool:
    """True if URL's domain is in the curated news-source whitelist."""
    domain = urlparse(url).netloc.lower().replace("www.", "")
    return any(domain == d or domain.endswith("." + d) for d in _NEWS_WHITELIST)


# ── State ─────────────────────────────────────────────────────────────────────

class PodcastState(TypedDict):
    task_instruction: str    # raw text from planner (empty when called via CLI)
    topic: str
    questions: list[str]
    intern_name: Union[str, list[str]]
    task_date: str
    subdir: str
    queries: list[dict]      # [{"question": str, "query": str}]
    articles: list[dict]     # [{"question": str, "items": [article_dict]}]
    output_path: str
    log_path: str
    progress_cb: ProgressCb


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_client() -> Anthropic:
    key = os.getenv("ANTHROPIC_API_KEY")
    if not key:
        raise EnvironmentError("ANTHROPIC_API_KEY not set in .env")
    return Anthropic(api_key=key)


def _parse_json(text: str):
    original = text
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    text = text.strip()
    match = re.search(r"(\{[\s\S]*\}|\[[\s\S]*\])", text)
    if match:
        text = match.group(1)
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        print(f"\n[DEBUG] JSON parse failed: {e}")
        print(f"[DEBUG] Raw response:\n{original[:2000]}")
        raise


def _is_blocked(url: str) -> bool:
    domain = urlparse(url).netloc.lower().replace("www.", "")
    return any(domain == b or domain.endswith("." + b) for b in _BLOCKED_DOMAINS)


_DOC_EXTENSIONS = (".pdf", ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx")


def _is_document_url(url: str) -> bool:
    """
    True if the URL points to a document file (PDF / Office) rather than a
    news page. Podcast wants news articles, not research reports / filings.
    """
    return urlparse(url).path.lower().endswith(_DOC_EXTENSIONS)


def _scrape(url: str) -> dict:
    """
    Scrape full text + metadata via trafilatura.
    Returns dict: {text, title, date, publication}
    Returns empty dict on failure.
    """
    try:
        import trafilatura
        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            return {}
        result = trafilatura.bare_extraction(
            downloaded,
            include_comments=False,
            include_tables=False,
            favor_precision=True,
        )
        if not result or not result.get("text"):
            return {}
        return {
            "text":        result.get("text", ""),
            "title":       result.get("title", ""),
            "date":        result.get("date", ""),
            "publication": result.get("sitename", ""),
            "author":      result.get("author", "") or "",
        }
    except Exception:
        return {}




def _is_traditional_chinese(text: str) -> bool:
    """
    Heuristic: check ratio of Traditional-Chinese-only characters.
    A text is considered Traditional Chinese if it has more trad-only
    chars than simplified-only chars, and CJK content is significant.
    """
    # Sample first 500 chars for speed
    sample = text[:500]
    cjk = sum(1 for c in sample if "\u4e00" <= c <= "\u9fff")
    if cjk < 20:
        return False   # Not enough CJK — probably English, skip translation

    # Characters that exist only in Traditional Chinese (not in Simplified)
    trad_only = set("國來發時還電們點說這個樣體對應後從給關戰現設處學習臺灣兒萬龍義傳實將產業開為歷會機車")
    # Characters that exist only in Simplified Chinese
    simp_only  = set("国来发时还电们点说这个样体对应后从给关战现设处学习台湾儿万龙义传实将产业开为历会机车")

    trad_count = sum(1 for c in sample if c in trad_only)
    simp_count = sum(1 for c in sample if c in simp_only)

    # If clearly simplified or no CJK signal, not Traditional Chinese
    if simp_count > trad_count:
        return False
    return True


_TRANSLATE_CHUNK_CHARS = 2500   # body split into ~this-size chunks for translation


def _split_for_translation(body: str, limit: int = _TRANSLATE_CHUNK_CHARS) -> list[str]:
    """
    Split body into chunks of <= `limit` chars on paragraph (newline)
    boundaries, so each chunk translates within a single LLM call. A single
    paragraph longer than the limit is hard-split.
    """
    chunks: list[str] = []
    buf = ""
    for para in body.split("\n"):
        if len(para) > limit:
            if buf:
                chunks.append(buf)
                buf = ""
            for i in range(0, len(para), limit):
                chunks.append(para[i:i + limit])
            continue
        if buf and len(buf) + len(para) + 1 > limit:
            chunks.append(buf)
            buf = para
        else:
            buf = f"{buf}\n{para}" if buf else para
    if buf:
        chunks.append(buf)
    return chunks


def _translate_chunk(text: str) -> str:
    """Translate one chunk of text to Traditional Chinese (plain text in/out)."""
    client = _get_client()
    prompt = f"""將以下內容翻譯成繁體中文。
若已是繁體中文，原樣回傳。
保留英文專有名詞（公司名、人名、產品名）。
保留原有的段落換行。
只輸出譯文本身，不要加任何說明、前言或標記。

{text}
"""
    msg = client.messages.create(
        model=config.LLM_FAST,
        max_tokens=8192,
        messages=[{"role": "user", "content": prompt}],
    )
    from utils.cost_tracker import tracker
    tracker.record_claude(config.LLM_FAST, msg.usage.input_tokens, msg.usage.output_tokens)
    return next((b.text for b in msg.content if hasattr(b, "text")), "").strip()


def _translate_to_traditional(title: str, body: str) -> tuple[str, str]:
    """
    Translate title + body to Traditional Chinese with LLM_FAST.

    The body is split into paragraph-aligned chunks so full-length articles
    translate end to end — no input truncation, no output-token clipping.
    A chunk that fails to translate degrades to its original text rather
    than dropping content. Returns (translated_title, translated_body).
    """
    try:
        trans_title = _translate_chunk(title) if title.strip() else title
    except Exception as exc:
        print(f"    [translate] ⚠ 標題翻譯失敗，保留原文：{exc}")
        trans_title = title

    trans_parts: list[str] = []
    for chunk in _split_for_translation(body):
        if not chunk.strip():
            continue
        try:
            trans_parts.append(_translate_chunk(chunk))
        except Exception as exc:
            print(f"    [translate] ⚠ 段落翻譯失敗，保留原文：{exc}")
            trans_parts.append(chunk)

    trans_body = "\n".join(p for p in trans_parts if p)
    return (trans_title or title), (trans_body or body)


def _format_source_label(meta: dict, fallback_url: str) -> str:
    """
    Build source label like '2024.08 中國證券時報評論'.
    """
    parts = []
    if meta.get("date"):
        # YYYY-MM-DD → YYYY.MM
        d = meta["date"][:7].replace("-", ".")
        parts.append(d)
    pub = meta.get("publication", "") or urlparse(fallback_url).netloc.replace("www.", "")
    if pub:
        parts.append(pub)
    return " ".join(parts) if parts else fallback_url


def _clean_body(text: str) -> str:
    """
    Remove web UI artifacts from scraped article text:
    - Table rows (2+ pipe chars)
    - Breadcrumb navigation (A > B > C with short segments)
    - Horizontal rules (----, ====, ···)
    - Very short lines without sentence-ending punctuation (buttons/tags)
    - Tag/category lists (4+ short comma-separated items)
    - Consecutive blank lines collapsed to one
    """
    lines = text.split("\n")
    cleaned = []

    for line in lines:
        s = line.strip()

        if not s:
            cleaned.append("")
            continue

        # Table rows
        if s.count("|") >= 2:
            continue

        # Horizontal rules
        if re.match(r'^[-=_*·•]{4,}$', s):
            continue

        # Breadcrumb navigation: A > B > C or A / B / C (all short segments)
        if re.search(r'[>»›]', s) and len(s) < 100:
            segs = re.split(r'\s*[>»›]\s*', s)
            if len(segs) >= 2 and all(len(p.strip()) < 25 for p in segs if p.strip()):
                continue

        # Very short lines without meaningful punctuation are likely UI elements
        # (buttons, labels, tags). Allow short lines that end with Chinese/Latin
        # sentence-ending punctuation — they may be legitimate headings in body.
        if len(s) < 10 and not re.search(r'[。！？：!?:]$', s):
            continue

        # Lines that look like a flat tag/category list: ≥4 short comma items
        parts = [p.strip() for p in s.split(',') if p.strip()]
        if len(parts) >= 4 and all(len(p) <= 15 for p in parts):
            continue

        cleaned.append(s)

    # Collapse consecutive blank lines to at most one
    result: list[str] = []
    prev_blank = False
    for line in cleaned:
        if line == "":
            if not prev_blank:
                result.append(line)
            prev_blank = True
        else:
            result.append(line)
            prev_blank = False

    return "\n".join(result).strip()


def _intern_str(intern_name) -> str:
    if isinstance(intern_name, list):
        return ", ".join(intern_name)
    return intern_name or config.DEFAULT_INTERN_NAME


def _build_subtitle(article: dict, intern_str: str) -> str:
    """
    Build podcast article subtitle line: 'YYYY.MM.DD_intern_媒體_作者'.
    Segments missing from the article are silently dropped; trailing
    underscores are not produced.
    """
    parts: list[str] = []
    pub_date = article.get("pub_date", "")
    if pub_date:
        # trafilatura returns YYYY-MM-DD or YYYY-MM. Convert to dot form.
        parts.append(pub_date.replace("-", "."))
    parts.append(intern_str)
    pub = (article.get("publication") or "").strip()
    if pub:
        parts.append(pub)
    author = (article.get("author") or "").strip()
    if author:
        parts.append(author)
    return "_".join(parts)


# ── Node 0: parse_instruction ────────────────────────────────────────────────

def parse_instruction(state: PodcastState) -> dict:
    """
    Parse raw STT/text instruction into topic + questions.
    No-op when topic is already set (CLI path: topic/questions passed directly).
    """
    if state.get("topic"):
        return {}
    emit(state.get("progress_cb"), "node_start", node="parse_instruction")

    raw = state.get("task_instruction", "").strip()
    if not raw:
        return {"topic": "未指定", "questions": []}

    client = _get_client()
    prompt = f"""你是一個 Podcast 研究任務解析助理。根據以下口述或文字指令，提取 Podcast 研究的主題與問題清單。

指令原文：
{raw}

輸出規則：
- topic：Podcast 的研究主題（一句話）
- questions：問題清單（每個問題是一條字串）
- 回傳純 JSON，不要 markdown 包裝

格式：
{{"topic": "主題名稱", "questions": ["問題1", "問題2", ...]}}
"""
    msg = client.messages.create(
        model=config.LLM_FAST,
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    from utils.cost_tracker import tracker
    tracker.record_claude(config.LLM_FAST, msg.usage.input_tokens, msg.usage.output_tokens)
    raw_out = next((b.text for b in msg.content if hasattr(b, "text")), "")
    parsed = _parse_json(raw_out)
    return {
        "topic":     parsed.get("topic", "未指定"),
        "questions": parsed.get("questions", []),
    }


# ── Node 1: generate_queries ──────────────────────────────────────────────────

def generate_queries(state: PodcastState) -> dict:
    """Single LLM_FAST call to generate one search query per question."""
    emit(state.get("progress_cb"), "node_start", node="generate_queries",
         n_questions=len(state.get("questions", [])))
    client = _get_client()

    questions_json = json.dumps(state["questions"], ensure_ascii=False)
    prompt = f"""{config.time_context()}

你是一個搜尋查詢生成助理。針對 Podcast 主題「{state['topic']}」，
為以下每個問題生成最佳的搜尋查詢字串（適合 Tavily / Google）。

規則：
- 每個問題生成 1 條查詢
- 優先搜尋繁體中文內容，可加入關鍵詞如「繁體」「台灣」「香港」，或中文關鍵詞
- 查詢要具體，包含主題關鍵詞
- 回傳純 JSON 陣列，格式如下：

[
  {{"question": "原始問題", "query": "搜尋查詢字串"}},
  ...
]

問題列表：
{questions_json}
"""
    msg = client.messages.create(
        model=config.LLM_FAST,
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )
    from utils.cost_tracker import tracker
    tracker.record_claude(config.LLM_FAST, msg.usage.input_tokens, msg.usage.output_tokens)
    raw = next((b.text for b in msg.content if hasattr(b, "text")), "")
    return {"queries": _parse_json(raw)}


# ── Node 2: search_and_fetch ──────────────────────────────────────────────────

def search_and_fetch(state: PodcastState) -> dict:
    cb = state.get("progress_cb")
    emit(cb, "node_start", node="search_and_fetch",
         n_questions=len(state.get("queries", [])))
    seen_urls: set[str] = set()
    articles_by_question: list[dict] = []

    for entry in state["queries"]:
        question = entry["question"]
        query    = entry["query"]
        emit(cb, "search_query", query=query, question=question, phase="podcast")

        print(f"  搜尋：{query}")
        results = search(
            query,
            max_results=_RESULTS_PER_QUESTION + _SEARCH_FETCH_EXTRA,
            topic="news",
        )
        from utils.cost_tracker import tracker
        tracker.record_tavily(1)

        items = []
        for r in results:
            if len(items) >= _RESULTS_PER_QUESTION:
                break

            url = r["url"]

            # Skip social media / blocked domains
            if _is_blocked(url):
                print(f"    [skip blocked] {url}")
                continue

            # Skip PDF / Office documents — podcast wants news, not reports
            if _is_document_url(url):
                print(f"    [skip pdf/doc] {url}")
                continue

            # Skip duplicates
            if url in seen_urls:
                print(f"    [skip dup] {url}")
                continue
            seen_urls.add(url)

            # Full-text cascade:
            #   1. trafilatura — free, carries metadata (date/author/sitename)
            #   2. Tavily extract — paid, but bot-blocking handled server-side
            #      (trafilatura's default UA gets blocked by many news sites)
            #   3. Tavily snippet — last resort, only 1-2 sentences
            meta = _scrape(url)
            if meta and meta.get("text"):
                body  = meta["text"]
                title = meta.get("title") or r["title"]
                scrape_src = "scraped"
            else:
                snippet   = r.get("content", "")
                extracted = fetch_full_content(url)
                tracker.record_tavily(1)
                if extracted and len(extracted) > len(snippet):
                    body  = extracted
                    scrape_src = "extract"
                else:
                    body  = snippet
                    scrape_src = "snippet"
                title = r["title"]
                # Backfill pub_date + publication from Tavily search response
                # and domain lookup so snippet/extract-path articles still
                # produce a proper subtitle (issue #6). The scrape_src set
                # by the cascade above ("extract" or "snippet") is preserved.
                # Author is left empty — Tavily does not surface it, and a
                # wrong author is worse than none.
                from utils.news_publications import lookup as _pub_lookup
                meta = {
                    "date":        r.get("published_date", ""),
                    "publication": _pub_lookup(url),
                    "author":      "",
                }

            # Strip nav menus / link lists / boilerplate (Tavily extract
            # returns raw page markdown), then remove web UI artifacts.
            # Done before translation so junk isn't translated or pasted.
            body, n_dropped = strip_extract_boilerplate(body)
            if n_dropped:
                print(f"    [clean] dropped {n_dropped} boilerplate line(s)")
            body = _clean_body(body)

            # Reject articles that are too short to be substantive
            if len(body) < _MIN_ARTICLE_CHARS:
                print(f"    [skip short={len(body)}] {title[:50]}")
                continue

            # Translate if not Traditional Chinese
            if not _is_traditional_chinese(body):
                print(f"    [translate] {title[:50]}")
                title, body = _translate_to_traditional(title, body)
                scrape_src += "+translated"

            verified = _is_whitelisted_news(url)
            verify_tag = "verified" if verified else "unverified"
            print(f"    [{scrape_src}/{verify_tag}] {title[:55]}")
            items.append({
                "title":        title,
                "url":          url,
                "source_label": _format_source_label(meta, url),
                "pub_date":     meta.get("date", ""),
                "publication":  meta.get("publication", "") or urlparse(url).netloc.replace("www.", ""),
                "author":       (meta.get("author") or "").strip(),
                "body":         body,
                "verified":     verified,
            })

        articles_by_question.append({
            "question": question,
            "items":    items,
        })

    return {"articles": articles_by_question}


# ── Node 3: format_output ─────────────────────────────────────────────────────

def format_output(state: PodcastState) -> dict:
    emit(state.get("progress_cb"), "node_start", node="format_output")
    topic     = state["topic"]
    intern    = state["intern_name"]
    task_date = state.get("task_date") or date.today().strftime("%Y-%m-%d")
    subdir    = state.get("subdir", "adhoc")
    intern_str = _intern_str(intern)

    builder = WordBuilder(f"Podcast：{topic}", task_date, intern)
    builder.add_blank_line()

    for qi, section in enumerate(state["articles"], start=1):
        # Numbered question heading
        builder.add_heading(f"{qi}. {section['question']}")

        for article in section["items"]:
            # Title: red + bold + underlined; subtitle below via shift+enter.
            # Subtitle format: YYYY.MM.DD_intern_媒體_作者 (segments dropped if missing)
            subtitle = _build_subtitle(article, intern_str)
            builder.add_red_underline_title_with_subtitle(article["title"], subtitle)
            # Body paragraphs
            for para in article["body"].split("\n"):
                para = para.strip()
                if para:
                    builder.add_paragraph(para)
            builder.add_blank_line()

    dot_date = task_date.replace("-", ".")
    filename = general(f"{topic}_Podcast", intern, dot_date)
    out_path = builder.save(filename, subdir=subdir)

    logger = AgentLogger("podcast_agent", f"Podcast: {topic} ({len(state['questions'])} questions)", intern)
    logger.set_queries([e["query"] for e in state["queries"]])
    for section in state["articles"]:
        logger.add_search_result(
            section["question"],
            [
                {
                    # Prefix unverified-source titles so they pop in the .log
                    "title": (
                        a["title"] if a.get("verified", True)
                        else f"[unverified_source] {a['title']}"
                    ),
                    "url": a["url"],
                    "score": 0.0,
                }
                for a in section["items"]
            ],
        )
    log_path = logger.save(out_path)

    return {"output_path": str(out_path), "log_path": str(log_path)}


# ── Graph ─────────────────────────────────────────────────────────────────────

def build_graph():
    graph = StateGraph(PodcastState)
    graph.add_node("parse_instruction", parse_instruction)
    graph.add_node("generate_queries",  generate_queries)
    graph.add_node("search_and_fetch",  search_and_fetch)
    graph.add_node("format_output",     format_output)

    graph.set_entry_point("parse_instruction")
    graph.add_edge("parse_instruction", "generate_queries")
    graph.add_edge("generate_queries",  "search_and_fetch")
    graph.add_edge("search_and_fetch",  "format_output")
    graph.add_edge("format_output",     END)

    return graph.compile()


# ── Public entry point ────────────────────────────────────────────────────────

def run(
    task_instruction: str = "",
    topic: str = "",
    questions: list[str] = None,
    intern_name: Union[str, list[str]] = None,
    task_date: str = None,
    subdir: str = "weekly",
    progress_cb: ProgressCb = None,
) -> dict:
    """
    Two calling paths:
      Planner path: run(task_instruction="口述原文...")
      CLI path:     run(topic="...", questions=[...])
    """
    app = build_graph()
    final_state = app.invoke({
        "task_instruction": task_instruction,
        "topic":            topic or "",
        "questions":        questions or [],
        "intern_name":      intern_name or config.DEFAULT_INTERN_NAME,
        "task_date":        task_date or date.today().strftime("%Y-%m-%d"),
        "subdir":           subdir,
        "queries":          [],
        "articles":         [],
        "output_path":      "",
        "log_path":         "",
        "progress_cb":      progress_cb,
    })
    return {
        "output_path": final_state["output_path"],
        "log_path":    final_state["log_path"],
    }


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Podcast research agent")
    parser.add_argument("--topic",     required=True)
    parser.add_argument("--questions", required=True,
                        help="Semicolon-separated questions")
    parser.add_argument("--intern",    default=None)
    parser.add_argument("--date",      default=None)
    parser.add_argument("--subdir",    default="weekly", choices=["daily", "weekly", "adhoc"])
    args = parser.parse_args()

    questions = [q.strip() for q in args.questions.split(";") if q.strip()]
    intern = (
        [n.strip() for n in args.intern.split(",")]
        if args.intern and "," in args.intern
        else args.intern
    )

    print(f"Podcast：{args.topic}（{len(questions)} 個問題）")
    result = run(
        topic=args.topic,
        questions=questions,
        intern_name=intern,
        task_date=args.date,
        subdir=args.subdir,
    )
    print(f"  Output: {result['output_path']}")
    print(f"  Log:    {result['log_path']}")
