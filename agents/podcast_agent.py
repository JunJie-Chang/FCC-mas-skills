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
from utils.search import search

load_dotenv(override=True)

_RESULTS_PER_QUESTION = 3    # final articles per question
_SEARCH_FETCH_EXTRA   = 4    # extra results to fetch to survive filter + dedup
_MIN_ARTICLE_CHARS    = 400  # cleaned body must have at least this many chars

# Social media / low-quality domains to skip
_BLOCKED_DOMAINS = {
    "facebook.com", "fb.com", "twitter.com", "x.com",
    "instagram.com", "youtube.com", "youtu.be", "tiktok.com",
    "reddit.com", "linkedin.com", "pinterest.com", "tumblr.com",
    "weibo.com", "weixin.qq.com", "mp.weixin.qq.com",
    "threads.net", "snapchat.com",
}


# ── State ─────────────────────────────────────────────────────────────────────

class PodcastState(TypedDict):
    topic: str
    questions: list[str]
    intern_name: Union[str, list[str]]
    task_date: str
    subdir: str
    queries: list[dict]      # [{"question": str, "query": str}]
    articles: list[dict]     # [{"question": str, "items": [article_dict]}]
    output_path: str
    log_path: str


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
    trad_only = set("國來發時還電們點說這個樣體對應還後從給關戰現設關處")
    # Characters that exist only in Simplified Chinese
    simp_only  = set("国来发时还电们点说这个样体对应还后从给关战现设关处")

    trad_count = sum(1 for c in sample if c in trad_only)
    simp_count = sum(1 for c in sample if c in simp_only)

    # If clearly simplified or no CJK signal, not Traditional Chinese
    if simp_count > trad_count:
        return False
    return True


def _translate_to_traditional(title: str, body: str) -> tuple[str, str]:
    """
    Use LLM_FAST to translate title + body to Traditional Chinese.
    Returns (translated_title, translated_body).
    """
    client = _get_client()
    prompt = f"""將以下文章標題和內文翻譯成繁體中文。
若已是繁體中文，原文回傳即可。
保留英文專有名詞（公司名、人名、產品名）。
回傳純 JSON，不要 markdown：

{{"title": "翻譯後標題", "body": "翻譯後內文（保留段落換行）"}}

原標題：{title}

原內文：
{body[:6000]}
"""
    msg = client.messages.create(
        model=config.LLM_FAST,
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )
    from utils.cost_tracker import tracker
    tracker.record_claude(config.LLM_FAST, msg.usage.input_tokens, msg.usage.output_tokens)

    raw = next((b.text for b in msg.content if hasattr(b, "text")), "")
    try:
        parsed = _parse_json(raw)
        return parsed.get("title", title), parsed.get("body", body)
    except Exception:
        return title, body


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


# ── Node 1: generate_queries ──────────────────────────────────────────────────

def generate_queries(state: PodcastState) -> dict:
    """Single LLM_FAST call to generate one search query per question."""
    client = _get_client()

    questions_json = json.dumps(state["questions"], ensure_ascii=False)
    prompt = f"""你是一個搜尋查詢生成助理。針對 Podcast 主題「{state['topic']}」，
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
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    from utils.cost_tracker import tracker
    tracker.record_claude(config.LLM_FAST, msg.usage.input_tokens, msg.usage.output_tokens)
    raw = next((b.text for b in msg.content if hasattr(b, "text")), "")
    return {"queries": _parse_json(raw)}


# ── Node 2: search_and_fetch ──────────────────────────────────────────────────

def search_and_fetch(state: PodcastState) -> dict:
    seen_urls: set[str] = set()
    articles_by_question: list[dict] = []

    for entry in state["queries"]:
        question = entry["question"]
        query    = entry["query"]

        print(f"  搜尋：{query}")
        results = search(query, max_results=_RESULTS_PER_QUESTION + _SEARCH_FETCH_EXTRA)
        from utils.cost_tracker import tracker
        from utils.search import fetch_full_content
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

            # Skip duplicates
            if url in seen_urls:
                print(f"    [skip dup] {url}")
                continue
            seen_urls.add(url)

            # Fetch full text via Tavily extract
            raw_content = fetch_full_content(url)
            tracker.record_tavily(1)
            if not raw_content:
                print(f"    [skip no content] {r['title'][:50]}")
                continue
            body  = raw_content
            title = r["title"]
            meta  = {}
            scrape_src = "tavily_extract"

            # Remove web UI artifacts
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

            print(f"    [{scrape_src}] {title[:55]}")
            items.append({
                "title":        title,
                "url":          url,
                "source_label": _format_source_label(meta, url),
                "body":         body,
            })

        articles_by_question.append({
            "question": question,
            "items":    items,
        })

    return {"articles": articles_by_question}


# ── Node 3: format_output ─────────────────────────────────────────────────────

def format_output(state: PodcastState) -> dict:
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
            # Red bold article title + (InternName); source metadata goes in comment
            comment = "\n".join(filter(None, [
                article.get("source_label", ""),
                article.get("url", ""),
            ]))
            builder.add_red_heading_with_comment(
                f"{article['title']} ({intern_str})",
                comment,
            )
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
            [{"title": a["title"], "url": a["url"], "score": 0.0} for a in section["items"]],
        )
    log_path = logger.save(out_path)

    return {"output_path": str(out_path), "log_path": str(log_path)}


# ── Graph ─────────────────────────────────────────────────────────────────────

def build_graph():
    graph = StateGraph(PodcastState)
    graph.add_node("generate_queries", generate_queries)
    graph.add_node("search_and_fetch", search_and_fetch)
    graph.add_node("format_output",    format_output)

    graph.set_entry_point("generate_queries")
    graph.add_edge("generate_queries", "search_and_fetch")
    graph.add_edge("search_and_fetch", "format_output")
    graph.add_edge("format_output",    END)

    return graph.compile()


# ── Public entry point ────────────────────────────────────────────────────────

def run(
    topic: str,
    questions: list[str],
    intern_name: Union[str, list[str]] = None,
    task_date: str = None,
    subdir: str = "weekly",
    task_instruction: str = None,
) -> dict:
    app = build_graph()
    final_state = app.invoke({
        "topic":       topic,
        "questions":   questions,
        "intern_name": intern_name or config.DEFAULT_INTERN_NAME,
        "task_date":   task_date or date.today().strftime("%Y-%m-%d"),
        "subdir":      subdir,
        "queries":     [],
        "articles":    [],
        "output_path": "",
        "log_path":    "",
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
