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

        lines.append("--- Output ---")
        lines.append(f"File: {self._output_path}")

        return lines
