# FCC MAS — Codex Context

## Project Overview
FCC Partners 實習生日常工作流程的 Multi-Agent System。
CY（老闆）口述指令 → STT → Planner → 確認 → Agents → Word 輸出 + Log。

## Environment
- Python: system Python 3.13 (`/Library/Frameworks/Python.framework/Versions/3.13`)
- `.venv` 存在但未使用（packages 裝在 system Python）
- `.env` 有 ANTHROPIC_API_KEY、TAVILY_API_KEY、OPENAI_API_KEY

## Tech Stack
- LangGraph（每個 agent 都是獨立 graph）
- Anthropic Codex（opus-4-6 = LLM_MAIN, haiku-4-5 = LLM_FAST）
- Tavily（web search）
- OpenAI Whisper（STT）
- python-docx（Word 輸出）

## Current Build Status

### ✅ Done
- `config.py` — format settings（字體、字號、頁面、行距）
- `.env.example`
- `requirements.txt`
- `utils/file_naming.py` — `general()` / `speech()`，含 filename sanitize
- `utils/search.py` — Tavily wrapper，max_results 由 agent 傳入
- `utils/stt.py` — Whisper API，測試過 CY 的 m4a（667s/10MB 正常）
- `utils/logger.py` — AgentLogger，在 output .docx 旁寫 .log（sources）
- `utils/planner.py` — parse_tasks()（haiku 解析+分類）+ confirm()（CLI互動）
- `formatters/word_formatter.py` — WordBuilder，save() 自動複製到 ~/Downloads
- `agents/company_info_agent.py` — LangGraph 4-node，tested ✓
- `agents/person_info_agent.py` — LangGraph 4-node，tested ✓
- `router.py` — dispatch table，未實作的 agent 給 NotImplementedError
- `main.py` — CLI 入口，STT+planner+confirm+router 全接通

### ⏳ Not Yet Built (Build Order)
1. `formatters/pdf_formatter.py` — **已廢棄，改為 word_formatter 自動匯出 ~/Downloads**
2. `agents/translation_agent.py`
3. `agents/dictation_agent.py`（letter + meeting 兩種 task_type）
4. `agents/podcast_agent.py`
5. `delivery/email_draft.py`

## Key Architecture Decisions

### Planner → Confirm → Router 流程
所有 agent 都走這條：
1. STT（或直接文字）→ `planner.parse_tasks()` → CLI confirm → `router.dispatch()`
2. `PlanTask` 有 `agent_type` / `label` / `instruction` 三個欄位
3. `force_type` 參數：單獨跑某個 agent CLI 時傳入，跳過自動分類

### Word 格式規範（從 Works/ 實際檔案逆向）
- 字體：微軟正黑體，ascii + eastAsia + hAnsi + cs 都設到
- Title：14pt Bold；Body：14pt Normal
- 頁面：A4，margins top/bottom=2.5cm, left/right=3.2cm
- 行距：1.15 multiple
- 頁面邊框：四邊 single，sz=12，space=24，offsetFrom=page
- Header：右對齊「Private & Confidential」，11pt Bold
- 命名：`YYYY.MM.DD_TaskName_InternName.docx`

### Agent 內部 Prompt 策略
- **company_info**: parse_task 強制帶股票代碼進 query（避免 haiku 亂搜）
- **person_info**: 搜尋方向 → 工商登記、現職、公協會身份；報告結構以關聯組織為 heading

### PDF Formatter
廢棄，不做。Word 輸出後直接在 ~/Downloads 取檔。

## Reference Files
- 範本路徑：`/Users/junjie/Library/CloudStorage/OneDrive-個人(2)/Internship/Works/`
- company_info 範本：`2026.03.26_Nutrition Startup Huel_Justin.docx`
- person_info 範本：`2026.04.02_林振宏_Justin.docx`
- podcast 範本：`2026.03.25_K-pop_Podcast.docx`

## CLI Usage
```bash
# 混合任務（自動分類）
python main.py --input "查英維克（002837.SZ）；另外查林志明" --intern "Justin"

# STT 全流程
python main.py --audio ./recordings/20260407.m4a --intern "Justin" --subdir daily

# 指定類型
python main.py --input "調查林志明" --type person_info --intern "Justin"

# 直接跑單一 agent
python agents/company_info_agent.py --task "查 Tesla" --intern "Justin"
```

## Remaining Agent Notes
- `translation_agent`：輸入文字/.txt/.docx，輸出 Word（格式同其他 agent）
- `dictation_agent`：audio → STT → Codex 整理 → Word；letter/meeting 兩種 prompt
- `podcast_agent`：N 個問題 → 每題搜 3 篇原文 → Word（每題一 section，不做摘要）
- `email_draft.py`：根據任務類型產生 email 草稿（主旨/收件人/CC/內文）
