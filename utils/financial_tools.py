"""
utils/financial_tools.py — Financial data fetchers (yfinance + FinanceDatabase).

Each public function returns a dict. On failure it returns {"error": "<reason>"}
instead of raising, so the agent can always continue gracefully.

Tool catalogue split by data source:
  YFINANCE_TOOL_DESCRIPTIONS  → Q2, triggered when Q1=Y (specific listed company)
  SECTOR_TOOL_DESCRIPTIONS    → Q3, triggered for industry/sector discovery

Rate limiting: _CALL_DELAY seconds are inserted between successive API calls.
"""
import time
import warnings
from typing import Any

# ── Q2 tool catalogue — yfinance（specific listed company） ───────────────────

YFINANCE_TOOL_DESCRIPTIONS: dict[str, str] = {
    "stock_price":  "股價（近 3 個月歷史走勢、現價、漲跌幅、52 週高低）",
    "financials":   "財報（最新季度損益表 / 資產負債表 / 現金流量表）",
    "key_metrics":  "估值指標（市值、PE、EV/EBITDA、股息率、Beta…）",
    "holders":      "股東結構（前 10 大機構 / 法人持股）",
    "news":         "近期新聞（Yahoo Finance 最新 5 則標題與連結）",
}

# ── Q3 tool catalogue — FinanceDatabase（sector / industry discovery） ────────

SECTOR_TOOL_DESCRIPTIONS: dict[str, str] = {
    "sector_scan":  "產業掃描（列出某產業 / 國家的上市公司清單，含 ticker、交易所、市場）",
}

# Keep a combined alias for backward compatibility
TOOL_DESCRIPTIONS = YFINANCE_TOOL_DESCRIPTIONS

_CALL_DELAY = 1.5   # seconds between yfinance API calls


# ── Internal helpers ──────────────────────────────────────────────────────────

def _safe(fn, *args, **kwargs) -> Any:
    """Call fn, catch all exceptions, return {"error": str} on failure."""
    try:
        return fn(*args, **kwargs)
    except Exception as exc:
        return {"error": str(exc)}


def _ticker(symbol: str):
    """Return a yf.Ticker object. Import here so import errors surface clearly."""
    import yfinance as yf
    return yf.Ticker(symbol)


# ── Ticker resolution ─────────────────────────────────────────────────────────

def resolve_ticker(company_name: str) -> str | None:
    """
    Try to find a ticker symbol for company_name.
    Strategy 1: yfinance Search (fast, covers most major markets)
    Strategy 2: FinanceDatabase equity search (broader but slower)
    Returns the best-guess symbol string, or None if nothing found.
    """
    # Strategy 1 — yfinance Search
    def _yf_search():
        import yfinance as yf
        results = yf.Search(company_name, max_results=5).quotes
        if results:
            return results[0].get("symbol")
        return None

    symbol = _safe(_yf_search)
    if symbol and not isinstance(symbol, dict):  # dict means {"error": ...}
        return symbol

    time.sleep(_CALL_DELAY)

    # Strategy 2 — FinanceDatabase
    def _fd_search():
        import financedatabase as fd
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            equities = fd.Equities()
            matches = equities.search(company_name)
        if not matches.empty:
            return matches.index[0]
        return None

    symbol = _safe(_fd_search)
    if symbol and not isinstance(symbol, dict):
        return symbol

    return None


# ── Individual data fetchers ──────────────────────────────────────────────────

def fetch_stock_price(symbol: str) -> dict:
    def _fetch():
        t = _ticker(symbol)
        hist = t.history(period="3mo")
        if hist.empty:
            return {"error": "no price history returned"}
        start_close = float(hist.iloc[0]["Close"])
        latest_close = float(hist.iloc[-1]["Close"])
        change_pct = round((latest_close - start_close) / start_close * 100, 2) if start_close else None
        info = _safe(lambda: t.info) or {}
        return {
            "symbol": symbol,
            "current_price": round(latest_close, 4),
            "change_3mo_pct": change_pct,
            "high_3mo": round(float(hist["High"].max()), 4),
            "low_3mo": round(float(hist["Low"].min()), 4),
            "week52_high": info.get("fiftyTwoWeekHigh"),
            "week52_low": info.get("fiftyTwoWeekLow"),
            "currency": info.get("currency"),
        }
    result = _safe(_fetch)
    if "error" in result:
        print(f"[financial_tools] ⚠ stock_price({symbol}): {result['error']}")
    return result


def fetch_financials(symbol: str) -> dict:
    def _fetch():
        t = _ticker(symbol)
        out = {"symbol": symbol}
        for attr, label in [
            ("quarterly_income_stmt",   "income_stmt_latest_q"),
            ("quarterly_balance_sheet", "balance_sheet_latest_q"),
            ("quarterly_cashflow",      "cashflow_latest_q"),
        ]:
            df = getattr(t, attr, None)
            if df is not None and not df.empty:
                col = df.iloc[:, 0].dropna()
                # Keep only numeric rows; convert to plain float for JSON safety
                out[label] = {str(k): float(v) for k, v in col.items() if isinstance(v, (int, float))}
        if len(out) == 1:   # only "symbol" key → nothing fetched
            return {"error": "no financial statements returned"}
        return out
    result = _safe(_fetch)
    if "error" in result:
        print(f"[financial_tools] ⚠ financials({symbol}): {result['error']}")
    return result


def fetch_key_metrics(symbol: str) -> dict:
    _WANTED = [
        "marketCap", "trailingPE", "forwardPE", "priceToBook",
        "enterpriseToEbitda", "dividendYield", "beta",
        "revenueGrowth", "earningsGrowth", "grossMargins",
        "operatingMargins", "currency",
    ]
    def _fetch():
        info = _ticker(symbol).info
        out = {"symbol": symbol}
        out.update({k: info[k] for k in _WANTED if k in info and info[k] is not None})
        if len(out) == 1:
            return {"error": "no key metrics returned"}
        return out
    result = _safe(_fetch)
    if "error" in result:
        print(f"[financial_tools] ⚠ key_metrics({symbol}): {result['error']}")
    return result


def fetch_holders(symbol: str) -> dict:
    def _fetch():
        t = _ticker(symbol)
        inst = t.institutional_holders
        if inst is None or inst.empty:
            return {"error": "no institutional holder data"}
        records = inst.head(10).to_dict(orient="records")
        # Ensure all values are JSON-serialisable
        clean = []
        for row in records:
            clean.append({k: (str(v) if not isinstance(v, (int, float, str, type(None))) else v)
                          for k, v in row.items()})
        return {"symbol": symbol, "institutional_holders": clean}
    result = _safe(_fetch)
    if "error" in result:
        print(f"[financial_tools] ⚠ holders({symbol}): {result['error']}")
    return result


def fetch_news(symbol: str) -> dict:
    def _fetch():
        raw = _ticker(symbol).news
        if not raw:
            return {"error": "no news returned"}
        articles = []
        for item in raw[:5]:
            # yfinance ≥0.2.x nests content under "content" key
            content = item.get("content", item)
            title = content.get("title", "")
            url = (content.get("canonicalUrl") or {}).get("url", "") or content.get("link", "")
            if title:
                articles.append({"title": title, "url": url})
        return {"symbol": symbol, "news": articles} if articles else {"error": "no parseable news"}
    result = _safe(_fetch)
    if "error" in result:
        print(f"[financial_tools] ⚠ news({symbol}): {result['error']}")
    return result


# ── FinanceDatabase: sector scan ─────────────────────────────────────────────

def fetch_sector_scan(sector: str, country: str = None, limit: int = 30) -> dict:
    """
    Search FinanceDatabase for listed companies matching sector + optional country.
    Returns a list of {name, symbol, exchange, country} dicts.
    """
    def _fetch():
        import financedatabase as fd
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            equities = fd.Equities()

        kwargs: dict = {}
        if sector:
            kwargs["industry_group"] = sector
        if country:
            kwargs["country"] = country

        df = equities.search(**kwargs) if kwargs else equities.select()
        if df.empty:
            # Retry with looser sector match (drop country constraint)
            if country:
                df = equities.search(industry_group=sector) if sector else df
        if df.empty:
            return {"error": f"no results for sector='{sector}' country='{country}'"}

        cols = [c for c in ["name", "exchange", "country", "currency", "market"] if c in df.columns]
        records = (
            df[cols]
            .dropna(subset=["name"])
            .head(limit)
            .reset_index()          # brings ticker symbol into column
            .rename(columns={"index": "symbol"})
            .to_dict(orient="records")
        )
        return {"sector": sector, "country": country, "companies": records}

    result = _safe(_fetch)
    if "error" in result:
        print(f"[financial_tools] ⚠ sector_scan('{sector}', '{country}'): {result['error']}")
    return result


# ── Tool registry ─────────────────────────────────────────────────────────────

TOOL_REGISTRY: dict[str, Any] = {
    "stock_price":  fetch_stock_price,
    "financials":   fetch_financials,
    "key_metrics":  fetch_key_metrics,
    "holders":      fetch_holders,
    "news":         fetch_news,
}

SECTOR_TOOL_REGISTRY: dict[str, Any] = {
    "sector_scan": fetch_sector_scan,
}


# ── Public batch fetchers ─────────────────────────────────────────────────────

def fetch_sector_data(q3: dict) -> dict:
    """
    Execute FinanceDatabase tools based on Q3 classification output.
    q3 format: {"needed": "Y", "sector": str, "country": str | null}
    Returns combined results dict.
    """
    sector  = q3.get("sector", "")
    country = q3.get("country") or None
    print(f"[financial_tools] sector_scan: sector='{sector}' country='{country}'…")
    time.sleep(_CALL_DELAY)
    return fetch_sector_scan(sector, country)


def fetch_all(symbol: str, tools: list[str]) -> dict:
    """
    Fetch data for each requested tool with _CALL_DELAY between calls.
    Returns {"ticker": symbol, "tool_id": data_dict, ...}.
    Unknown tool ids are skipped with a warning.
    """
    results: dict = {"ticker": symbol}
    valid = [t for t in tools if t in TOOL_REGISTRY]
    unknown = [t for t in tools if t not in TOOL_REGISTRY]
    if unknown:
        print(f"[financial_tools] ⚠ unknown tools skipped: {unknown}")

    for i, tool_id in enumerate(valid):
        if i > 0:
            time.sleep(_CALL_DELAY)
        print(f"[financial_tools] fetching {tool_id} for {symbol}…")
        results[tool_id] = TOOL_REGISTRY[tool_id](symbol)

    return results
