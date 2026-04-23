"""
utils/search.py — Tavily search wrapper.

Each agent passes its own `max_results` so the call count stays flexible
and is not hardcoded here.
"""
import os
import time
from typing import Optional
from dotenv import load_dotenv

load_dotenv(override=True)

_MAX_RETRIES = 4
_RETRY_DELAY = 3  # seconds between retries


def search(query: str, max_results: int = 3) -> list[dict]:
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
            response = client.search(query=query, max_results=max_results)
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
