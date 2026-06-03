"""
utils/financial_tools.py — Financial data fetchers (yfinance + FinanceDatabase).

Each public function returns a dict. On failure it returns {"error": "<reason>"}
instead of raising, so callers can always continue gracefully.

Callable from `fcc-company-info` skill via Bash:

    python3 -c "
    import json, os, sys
    sys.path.insert(0, os.environ.get('FCC_MAS_HOME', os.path.expanduser('~/.fcc-mas')))
    from utils.financial_tools import fetch_all
    print(json.dumps(fetch_all('TSLA',
        tools=['stock_price','financials','key_metrics','holders','news']),
        default=str, ensure_ascii=False))
    "

The skill chooses the ticker itself; this module no longer normalizes
company names via Haiku (removed during Skills migration in May 2026).
Pass a ticker that matches the yfinance format directly. Shanghai .SH
inputs are auto-canonicalized to .SS.

Rate limiting: _CALL_DELAY seconds are inserted between successive API calls.
"""
import re
import sys
import time
import warnings
from datetime import datetime, timezone
from typing import Any


def _now_taipei_str() -> str:
    """Return current time in Taipei tz as 'YYYY-MM-DD HH:MM TPE'."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("Asia/Taipei")).strftime("%Y-%m-%d %H:%M TPE")
    except Exception:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

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


# ── FinanceDatabase enum cache ───────────────────────────────────────────────

_FDB_ENUM_CACHE: dict | None = None


def get_fdb_enum() -> dict:
    """
    Load FinanceDatabase's available sector / industry_group / industry /
    country / exchange values into a cached dict.

    Cached on disk at utils/_fdb_enum.json so subsequent calls are zero-cost.
    Delete that file to refresh. Used by company_info's Q3 sector-data layer
    so its prompt can constrain Haiku to selecting from a fixed enum (no
    free-form input that would produce illegal queries like
    industry='semiconductor company').
    """
    global _FDB_ENUM_CACHE
    if _FDB_ENUM_CACHE is not None:
        return _FDB_ENUM_CACHE

    import json
    from pathlib import Path
    cache_path = Path(__file__).parent / "_fdb_enum.json"
    if cache_path.exists():
        _FDB_ENUM_CACHE = json.loads(cache_path.read_text(encoding="utf-8"))
        return _FDB_ENUM_CACHE

    import financedatabase as fd
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        eq = fd.Equities()
        _FDB_ENUM_CACHE = {
            "sectors":         sorted(eq.show_options("sector").tolist()),
            "industry_groups": sorted(eq.show_options("industry_group").tolist()),
            "industries":      sorted(eq.show_options("industry").tolist()),
            "countries":       sorted(eq.show_options("country").tolist()),
            "exchanges":       sorted(eq.show_options("exchange").tolist()),
        }
    cache_path.write_text(
        json.dumps(_FDB_ENUM_CACHE, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return _FDB_ENUM_CACHE


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

# Strict mode: require ticker to match one of these patterns. Anything else
# (free-form names, partial codes) is rejected to prevent illegal symbols like
# "Semiconductor company" leaking into yfinance calls.
#
# Note on .SH: yfinance only accepts .SS for SSE-listed symbols (e.g. 601138.SS),
# not .SH (would 404). But Wind / 同花順 / 新浪財經 / instructions all use .SH,
# so we accept both at the validation layer and canonicalize to .SS before fetch.
_VALID_TICKER_RE = re.compile(
    r"^("
    r"[A-Z0-9]{1,5}"                  # US (TSLA, NVDA, BRK.B handled below via .)
    r"|[A-Z0-9.\-]{1,8}\.(TW|TWO|HK|SZ|SS|SH|T|KS|L|TO|AX|PA|DE|MI|MX|SA|F)"
    r")$"
)

def _canonicalize_ticker(ticker: str) -> str:
    """
    Map ticker to yfinance-compatible form. Idempotent.

    Currently: .SH → .SS (SSE Shanghai). Other suffixes pass through unchanged.
    """
    if not ticker:
        return ticker
    t = ticker.strip().upper()
    if t.endswith(".SH"):
        t = t[:-3] + ".SS"
    return t


def _is_valid_ticker_format(ticker: str) -> bool:
    """Strict ticker format check — used to reject Haiku hallucinations."""
    if not ticker or not isinstance(ticker, str):
        return False
    return bool(_VALID_TICKER_RE.match(ticker.strip().upper()))


# ── Individual data fetchers ──────────────────────────────────────────────────

def _tag_source(fn_name: str, result: dict, source: str) -> dict:
    """Attach _source to successful fetches; pass through errors untouched."""
    if isinstance(result, dict) and "error" not in result:
        result["_source"] = source
    return result


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
        # Last bar date (e.g. 2026-05-07) — accurate market data date, not just fetch time
        last_bar_date = hist.index[-1].strftime("%Y-%m-%d")
        return {
            "symbol": symbol,
            "as_of": last_bar_date,
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
        print(f"[financial_tools] ⚠ stock_price({symbol}): {result['error']}", file=sys.stderr)
    return _tag_source("stock_price", result, "yfinance")


def fetch_financials(symbol: str) -> dict:
    def _fetch():
        t = _ticker(symbol)
        out = {"symbol": symbol}
        period_ends = {}
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
                # Period end date (e.g. 2026-03-31) lives in the column header
                try:
                    period_ends[label] = df.columns[0].strftime("%Y-%m-%d")
                except Exception:
                    period_ends[label] = str(df.columns[0])
        if len(out) == 1:   # only "symbol" key → nothing fetched
            return {"error": "no financial statements returned"}
        out["period_end"] = period_ends   # {"income_stmt_latest_q": "2026-03-31", ...}
        out["as_of"] = _now_taipei_str()
        return out
    result = _safe(_fetch)
    if "error" in result:
        print(f"[financial_tools] ⚠ financials({symbol}): {result['error']}", file=sys.stderr)
    return _tag_source("financials", result, "yfinance")


def fetch_key_metrics(symbol: str) -> dict:
    _WANTED = [
        "marketCap", "trailingPE", "forwardPE", "priceToBook",
        "enterpriseToEbitda", "dividendYield", "beta",
        "revenueGrowth", "earningsGrowth", "grossMargins",
        "operatingMargins", "currency",
    ]
    def _fetch():
        info = _ticker(symbol).info
        out = {"symbol": symbol, "as_of": _now_taipei_str()}
        out.update({k: info[k] for k in _WANTED if k in info and info[k] is not None})
        if len(out) == 2:   # only "symbol" + "as_of" → nothing fetched
            return {"error": "no key metrics returned"}
        return out
    result = _safe(_fetch)
    if "error" in result:
        print(f"[financial_tools] ⚠ key_metrics({symbol}): {result['error']}", file=sys.stderr)
    return _tag_source("key_metrics", result, "yfinance")


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
        # yfinance includes a "Date Reported" column on each record; surface the latest as as_of
        try:
            latest_reported = max(
                (r.get("Date Reported") for r in clean if r.get("Date Reported")),
                default=None,
            )
        except Exception:
            latest_reported = None
        return {
            "symbol": symbol,
            "as_of": _now_taipei_str(),
            "latest_reported": latest_reported,
            "institutional_holders": clean,
        }
    result = _safe(_fetch)
    if "error" in result:
        print(f"[financial_tools] ⚠ holders({symbol}): {result['error']}", file=sys.stderr)
    return _tag_source("holders", result, "yfinance")


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
        return (
            {"symbol": symbol, "as_of": _now_taipei_str(), "news": articles}
            if articles else {"error": "no parseable news"}
        )
    result = _safe(_fetch)
    if "error" in result:
        print(f"[financial_tools] ⚠ news({symbol}): {result['error']}", file=sys.stderr)
    return _tag_source("news", result, "yfinance")


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
        print(f"[financial_tools] ⚠ sector_scan('{sector}', '{country}'): {result['error']}", file=sys.stderr)
    return _tag_source("sector_scan", result, "FinanceDatabase")


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
    print(f"[financial_tools] sector_scan: sector='{sector}' country='{country}'…", file=sys.stderr)
    time.sleep(_CALL_DELAY)
    return fetch_sector_scan(sector, country)


def fetch_all(symbol: str, tools: list[str]) -> dict:
    """
    Fetch data for each requested tool with _CALL_DELAY between calls.
    Returns {"ticker": symbol, "tool_id": data_dict, ...}.
    Unknown tool ids are skipped with a warning.

    Symbol is canonicalized to yfinance form (.SH → .SS) before fetch —
    .SH is used by 同花順 / 新浪財經 / instructions but yfinance only
    accepts .SS for SSE-listed symbols.
    """
    canon = _canonicalize_ticker(symbol)
    if canon != symbol:
        print(f"[financial_tools] canonicalize {symbol} → {canon}", file=sys.stderr)
    results: dict = {"ticker": canon}
    valid = [t for t in tools if t in TOOL_REGISTRY]
    unknown = [t for t in tools if t not in TOOL_REGISTRY]
    if unknown:
        print(f"[financial_tools] ⚠ unknown tools skipped: {unknown}", file=sys.stderr)

    for i, tool_id in enumerate(valid):
        if i > 0:
            time.sleep(_CALL_DELAY)
        print(f"[financial_tools] fetching {tool_id} for {canon}…", file=sys.stderr)
        results[tool_id] = TOOL_REGISTRY[tool_id](canon)

    return results
