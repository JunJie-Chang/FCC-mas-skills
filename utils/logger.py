"""
utils/logger.py — Source and activity logger for all agents.

Writes a .log file alongside each output document (same base name, .log ext).
Logs are for internal fact-checking — they do NOT appear in the Word output.

Log format:
    === <agent_name> ===
    Time:   YYYY-MM-DD HH:MM:SS
    Task:   <task_instruction>
    Intern: <intern_name>

    --- Search Queries ---
    1. <query>
    2. <query>
    ...

    --- Sources ---
    [Q1] <query>
      1. <title> | <url> | score=<score>
      2. ...
    [Q2] ...

    --- Output ---
    File: <output_path>
"""
from datetime import datetime
from pathlib import Path
from typing import Union


class AgentLogger:
    def __init__(
        self,
        agent_name: str,
        task_instruction: str,
        intern_name: Union[str, list[str]],
    ):
        self._agent_name = agent_name
        self._task = task_instruction
        self._intern = intern_name if isinstance(intern_name, str) else ", ".join(intern_name)
        self._queries: list[str] = []
        self._sources: list[dict] = []   # {"query": str, "results": [{"title","url","score"}]}
        self._financial_data: dict = {}  # {ticker: {tool_id: data, ...}, ..., "_resolve_failed":[names]} | {"_ticker_error":...}
        self._sector_data: dict = {}     # FinanceDatabase sector scan result
        self._number_items: list[dict] = []  # raw Haiku echo from number_extract
        self._validation: dict = {}          # premises + deliverables from premise_validate
        self._output_path: str = ""
        self._started = datetime.now()

    # ── Recording ─────────────────────────────────────────────────────────────

    def set_queries(self, queries: list[str]) -> None:
        self._queries = queries

    def add_search_result(self, query: str, results: list[dict]) -> None:
        """
        Record results for one search query.
        Each result dict should have keys: title, url, score (content is NOT logged).
        """
        self._sources.append({
            "query": query,
            "results": [
                {
                    "title": r.get("title", ""),
                    "url":   r.get("url", ""),
                    "score": r.get("score", 0.0),
                }
                for r in results
            ],
        })

    def add_sector_data(self, sector_data: dict) -> None:
        """Record FinanceDatabase sector scan results."""
        self._sector_data = sector_data

    def add_financial_data(self, financial_data: dict) -> None:
        """
        Record structured financial data fetched from yfinance.

        Multi-ticker shape (issue #13):
            {"GME":  {"stock_price": {...}, "financials": {...}, ...},
             "EBAY": {...},
             "_resolve_failed": ["..."]}     # optional, names that didn't resolve
        Or all-fail:
            {"_ticker_error": "...", "_resolve_failed": [...]}
        """
        self._financial_data = financial_data

    def add_validation(self, validation: dict) -> None:
        """Record premise + coverage validation from utils/premise_validate."""
        self._validation = validation or {}

    def add_extracted_numbers(self, items: list[dict]) -> None:
        """
        Record raw Haiku echo from utils/number_extract (verbatim numbers + scale +
        currency + derived Chinese string). Logged for audit / debugging only.
        """
        self._number_items = items

    def set_output_path(self, path: Union[str, Path]) -> None:
        self._output_path = str(path)

    # ── Save ──────────────────────────────────────────────────────────────────

    def save(self, output_path: Union[str, Path] = None) -> Path:
        """
        Write the log file next to the output document.

        Args:
            output_path: Path of the output .docx file; derives log path by
                         replacing the extension with .log. Falls back to
                         self._output_path if set.

        Returns:
            Path to the written .log file.
        """
        if output_path:
            self._output_path = str(output_path)

        if not self._output_path:
            raise ValueError("output_path must be set before calling save()")

        log_path = Path(self._output_path).with_suffix(".log")
        log_path.parent.mkdir(parents=True, exist_ok=True)

        lines = self._render()
        log_path.write_text("\n".join(lines), encoding="utf-8")
        return log_path

    # ── Rendering ─────────────────────────────────────────────────────────────

    def _render(self) -> list[str]:
        lines = [
            f"=== {self._agent_name} ===",
            f"Time:   {self._started.strftime('%Y-%m-%d %H:%M:%S')}",
            f"Task:   {self._task}",
            f"Intern: {self._intern}",
            "",
        ]

        if self._queries:
            lines.append("--- Search Queries ---")
            for i, q in enumerate(self._queries, 1):
                lines.append(f"{i}. {q}")
            lines.append("")

        if self._sources:
            lines.append("--- Sources ---")
            for i, entry in enumerate(self._sources, 1):
                lines.append(f"[Q{i}] {entry['query']}")
                for j, r in enumerate(entry["results"], 1):
                    lines.append(f"  {j}. {r['title']}")
                    lines.append(f"     {r['url']}  | score={r['score']:.3f}")
            lines.append("")

        if self._sector_data and "companies" in self._sector_data:
            import json
            source = self._sector_data.get("_source", "unknown")
            lines.append(f"--- Sector Data ({source}) ---")
            lines.append(f"Sector:  {self._sector_data.get('sector', '')}")
            lines.append(f"Country: {self._sector_data.get('country') or 'all'}")
            lines.append(f"Results: {len(self._sector_data.get('companies', []))} companies")
            dumped = json.dumps(self._sector_data.get("companies", []), ensure_ascii=False, default=str, indent=2)
            for line in dumped.splitlines():
                lines.append(f"  {line}")
            lines.append("")

        if self._financial_data:
            import json
            fin = self._financial_data
            ticker_keys = [k for k in fin.keys() if not k.startswith("_")]
            if "_ticker_error" in fin and not ticker_keys:
                lines.append("--- Financial Data (not fetched) ---")
                lines.append(f"WARNING: {fin['_ticker_error']}")
                if fin.get("_resolve_failed"):
                    lines.append(f"Unresolved names: {fin['_resolve_failed']}")
                lines.append("No structured financial data fetched; report relies on Tavily only.")
                lines.append("")
            else:
                for ticker in ticker_keys:
                    payload = fin[ticker]
                    # Aggregate sources actually used by each tool payload for this ticker
                    sources: dict[str, list[str]] = {}
                    for tool_id, data in payload.items():
                        if not isinstance(data, dict):
                            continue
                        src = data.get("_source", "unknown")
                        sources.setdefault(src, []).append(tool_id)
                    label = ", ".join(f"{s}: {', '.join(t)}" for s, t in sources.items()) or "unknown"
                    lines.append(f"--- Financial Data ({ticker} | {label}) ---")
                    for tool_id, data in payload.items():
                        lines.append(f"[{tool_id}]")
                        if isinstance(data, dict) and "error" in data:
                            lines.append(f"  ERROR: {data['error']}")
                        else:
                            dumped = json.dumps(data, ensure_ascii=False, default=str, indent=2)
                            for line in dumped.splitlines():
                                lines.append(f"  {line}")
                    lines.append("")
                if fin.get("_resolve_failed"):
                    lines.append(f"--- Financial Data: unresolved names ---")
                    for n in fin["_resolve_failed"]:
                        lines.append(f"  {n}")
                    lines.append("")

        if self._number_items:
            lines.append("--- Extracted Numbers (Haiku echo → Python convert) ---")
            for it in self._number_items:
                label = it.get("label", "")
                raw = it.get("raw", "")
                zh = it.get("zh", "")
                lines.append(f"  {label}: raw={raw!r}  →  zh={zh!r}")
            lines.append("")

        if self._validation:
            premises = self._validation.get("premises") or []
            deliverables = self._validation.get("deliverables") or []
            if premises or deliverables:
                lines.append("--- Premise Validation ---")
                if premises:
                    lines.append("Premises（任務指令斷言）：")
                    for p in premises:
                        tag = {"confirmed": "✓", "partial": "△", "unverified": "✗"}.get(p.get("status", ""), "?")
                        lines.append(f"  {tag} [{p.get('status', '')}] {p.get('claim', '')}")
                        if p.get("note"):
                            lines.append(f"      note: {p['note']}")
                        if p.get("evidence_url"):
                            lines.append(f"      url:  {p['evidence_url']}")
                if deliverables:
                    if premises:
                        lines.append("")
                    lines.append("Deliverables（任務指令問題 / 資料點）：")
                    for d in deliverables:
                        tag = {"answered": "✓", "partial": "△", "missing": "✗"}.get(d.get("status", ""), "?")
                        lines.append(f"  {tag} [{d.get('status', '')}] {d.get('question', '')}")
                        if d.get("note"):
                            lines.append(f"      note: {d['note']}")
                        if d.get("evidence_url"):
                            lines.append(f"      url:  {d['evidence_url']}")
                lines.append("")

        lines.append("--- Output ---")
        lines.append(f"File: {self._output_path}")

        return lines
