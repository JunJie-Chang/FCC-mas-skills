# FCC-mas-skills — Agent / Contributor Context

Context for coding agents (and humans) working in this repo. For the
end-user install/usage story see `README.md`; for shared writing &
formatting rules see `.claude/skills/fcc-shared/SKILL.md`.

## What this is

A toolkit of **Claude Code Skills** that automate an FCC Partners intern's
recurring deliverables (company / person research, dictation → meeting
minutes, verbal cleanup, translation, podcast research, speech → PPTX).

There is **no agent framework, no LLM orchestration layer, and no API
keys for Claude** here. The skills run *inside* a Claude Code session —
Claude is the reasoning engine. This repo only provides:

1. **Skill definitions** — `.claude/skills/fcc-*/SKILL.md` (the workflows
   Claude follows).
2. **Deterministic Python helpers** the skills shell out to — STT,
   docx/pptx builders, file naming, unit conversion, financial data.

> History: an earlier version was a LangGraph multi-agent system
> (`main.py` / `router.py` / `agents/*`). That was removed in the
> May 2026 migration to Skills (see `config.py`). Those modules no longer
> exist — ignore any lingering reference to them.

## Layout

```
.claude/skills/fcc-*/SKILL.md   # the skills (workflows Claude executes)
scripts/build_docx_cli.py       # JSON spec → .docx   (formatters.WordBuilder)
scripts/build_pptx_cli.py       # JSON spec → .pptx   (deep-blue chrome + DALL-E)
formatters/word_formatter.py    # WordBuilder — all .docx formatting
utils/spec_io.py                # shared spec load + safe path components
utils/stt.py                    # OpenAI gpt-4o-transcribe (chunks >4 min)
utils/cost_tracker.py           # non-fatal STT/DALL-E usage logging
utils/file_naming.py            # YYYY.MM.DD_TaskName_Intern.docx
utils/unit_convert.py           # deterministic 億/兆 ↔ million/billion
utils/financial_tools.py        # yfinance + FinanceDatabase fetchers
config.py                       # fonts, page geometry, output paths
assets/ppt_chrome_template.pptx # committed PPT chrome (single source of truth)
install.sh                      # clone → pip → symlink skills → .env → smoke test
output/{adhoc,daily,weekly}/    # generated files (gitignored)
```

## Environment

- **Python 3.10–3.13** (installer picks one; 3.13 recommended). Packages
  install into that interpreter; the `.venv/` dir is not used.
- **`.env`** holds only `OPENAI_API_KEY` (STT + DALL-E). No Anthropic /
  Tavily keys — Tavily search is done via Claude's own tools, not here.

## Build pipeline (how a report is produced)

1. A skill gathers facts (Claude + web tools) and assembles a **JSON spec**.
2. It shells out: `python3 scripts/build_docx_cli.py --spec /tmp/x.json`.
3. `WordBuilder` renders blocks (heading / paragraph / bullet / table /
   keyed_info / references …) into a `.docx` under `output/<subdir>/` and
   copies it to `~/Downloads` (unless `FCC_DISABLE_DOWNLOADS_COPY=1`).

`subdir` is whitelisted to `{adhoc, daily, weekly}` and `filename` is
basenamed (`utils/spec_io.py`) — a spec cannot write outside `output/`.

## Word format rules (reverse-engineered from real deliverables)

- Font 微軟正黑體 (fallback Noto Sans CJK TC); title 14pt bold, body 14pt.
- A4, margins top/bottom 2.5cm, left/right 3.2cm; line spacing 1.15.
- Page border: four sides single, sz=12, space=24, offsetFrom=page.
- Header: right-aligned "Private & Confidential", 11pt bold.
- Filename: `YYYY.MM.DD_TaskName_InternName.docx` (multi-intern: `A, B`).

## Conventions for changes

- Keep Python helpers **pure and non-fatal**: fetchers return
  `{"error": ...}` rather than raise; cost logging never breaks a task.
- Helper diagnostics go to **stderr** — stdout is reserved for the JSON /
  path the skills parse.
- Skill commands should call `python3` (not a hardcoded `python3.13`).
- `utils/unit_convert.py` has a 28-case self-test (`python3 utils/unit_convert.py`);
  add a case when you touch scale/currency logic.
