# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview
FCC Partners 實習生日常工作流程的 Multi-Agent System。
CY（老闆）口述指令 → STT → Planner → 確認 → Agents → Word 輸出。

## Environment
- Python: system Python 3.13 (`/Library/Frameworks/Python.framework/Versions/3.13`)
- `.venv` 存在但未使用（packages 裝在 system Python）
- `.env` 有 `ANTHROPIC_API_KEY`、`TAVILY_API_KEY`、`OPENAI_API_KEY`
- **重要**：所有 `load_dotenv()` 必須用 `override=True`，否則 shell 中已有空字串的 env var 會擋住 `.env` 的值

## CLI Usage
```bash
# STT 全流程（錄音 → 自動分類 → 執行）
python3.13 main.py --audio '/path/to/recording.m4a' --intern "Justin"

# 文字輸入，混合任務
python3.13 main.py --input "查 Tesla；另外查林志明" --intern "Justin"

# 指定 agent 類型（跳過 haiku 分類）
python3.13 main.py --input "調查林志明" --type person_info --intern "Justin"

# 報告模式（預設 short）
python3.13 main.py --audio ... --intern "Justin" --mode short    # 約兩頁，嚴格回應需求
python3.13 main.py --audio ... --intern "Justin" --mode medium   # 延伸分析完整版

# 翻譯快速入口（stdin 貼文章）
python3.13 translate.py "Article Title" SourceName 2026-04-15 Justin
# → 貼文章，輸入 END + Enter 結束

# 翻譯 + OCR（圖片或 PDF，例如 iPhone AirDrop 截圖）
python3.13 translate.py "Article Title" SourceName 2026-04-15 Justin --image ~/Downloads/IMG_xxxx.JPG
python3.13 translate.py "Article Title" SourceName 2026-04-15 Justin --pdf ~/Downloads/article.pdf
# PDF 需先安裝：pip install pymupdf

# 直接跑單一 agent
python3.13 agents/company_info_agent.py --task "查 Tesla" --intern "Justin"

# 口述清稿（去除廢話與開頭語）
python3.13 agents/verbal_cleanup_agent.py --audio ~/Downloads/recording.m4a --intern "Justin"
python3.13 agents/verbal_cleanup_agent.py --text "嗯好那個今天想說的是..." --intern "Justin"
python3.13 main.py --audio recording.m4a --type verbal_cleanup --intern "Justin"
```

## Tech Stack
- LangGraph（每個 agent 都是獨立 graph）
- Anthropic Claude：`LLM_MAIN = claude-opus-4-6`，`LLM_FAST = claude-haiku-4-5-20251001`
- Tavily（web search）
- yfinance + FinanceDatabase（財務資料，`utils/financial_tools.py`）
- OpenAI Whisper（STT，透過 `utils/stt.py`）
- python-docx（Word 輸出，透過 `formatters/word_formatter.py`）

## Architecture

### 主流程：`main.py → router.py → agent`

```
STT (utils/stt.py)
    ↓
parse_tasks() (utils/planner.py) — haiku 解析 + 分類，max_tokens=4096
    ↓
confirm() — CLI 互動：y 確認 / n 取消 / [數字] 修改 / d[數字] 刪除 / a 新增
    ↓
router.dispatch(task, intern_name, task_date, subdir, mode)
    ↓
agent.run(...)  →  WordBuilder.save()  →  output/ + ~/Downloads
```

### Agent 清單
| agent_type | 檔案 | 說明 |
|---|---|---|
| `company_info` | `agents/company_info_agent.py` | 公司/機構研究，7-node graph（含財務資料層） |
| `person_info` | `agents/person_info_agent.py` | 人物背景，4-node graph |
| `translation` | `agents/translation_agent.py` | 翻譯；router 傳 JSON instruction（含 title/source/body_text，`pub_date` 選填，沒給 fallback 今天）；`--body-file` 支援 .jpg/.png/.pdf OCR |
| `letter`/`meeting` | `agents/dictation_agent.py` | 口述整理，兩種 task_type 共用同一 agent |
| `verbal_cleanup` | `agents/verbal_cleanup_agent.py` | 口述清稿，去除廢話與開頭語，輸出乾淨書面稿 |
| `podcast` | `agents/podcast_agent.py` | Podcast 研究；router 傳 JSON instruction（含 topic/questions） |
| `speech_ppt` | `agents/speech_ppt_agent.py` | 簡報研究，需 OPENAI_API_KEY |

### Agent 內部結構

**company_info**（7-node LangGraph）：
1. `parse_task` — haiku 產生 3-5 個 Tavily 搜尋 query
2. `check_financial_need` — haiku Q1/Q2/Q3 分類（見下方 Financial Data Layer）
3. `fetch_financial_data` — ticker 解析 + yfinance 抓取；Q1=N 或 Q2=[] 時 no-op
4. `fetch_sector_data` — FinanceDatabase 產業掃描；Q3.needed=N 時 no-op
5. `run_search` — Tavily 搜尋，每 query 3 筆結果
6. `generate_report` — opus 合成 JSON 報告，prompt 依 `mode` 切換；財務 / 產業資料注入 context
7. `format_output` — WordBuilder 渲染 docx，AgentLogger 寫同路徑 `.log`

**person_info**（4-node LangGraph）：同上的 1 / 5 / 6 / 7，不含財務資料層

### router → agent 的 mode 傳遞規則
- `company_info` / `person_info` / `dictation`：router 用 `**kwargs` 呼叫，State TypedDict 和 `run()` 都必須包含 `mode` 欄位
- `podcast` / `speech_ppt` / `translation`：router 個別傳參，不走 `**kwargs`，不需要 `mode`
- 新增走 `**kwargs` 路徑的 agent，`run()` 必須接受 `mode: str = "short"` 以免 TypeError

### Word 格式規範
由 `formatters/word_formatter.py` 的 `WordBuilder` 統一處理：
- 字體：微軟正黑體（ascii + eastAsia + hAnsi + cs 四個 slot 都設）
- Title 14pt Bold；Body 14pt Normal；行距 1.15 multiple
- 頁面：A4，margins top/bottom=2.5cm, left/right=3.2cm
- 頁面邊框：四邊 single，sz=12，space=24，offsetFrom=page
- Header：右對齊「Private & Confidential」，11pt Bold 紅色斜體
- `save()` 自動複製到 `~/Downloads`，無 PDF 輸出（已廢棄移除）
- 命名：`YYYY.MM.DD_TaskName_InternName.docx`（`utils/file_naming.general()` 產生）

### generate_report Prompt 規則（所有 agent 適用）
- 不在任何名詞後加括號標注其他語言的原文或譯名（不論英文、越南文或任何語言）
- 不在報告內容中提及任務指令的措辭、比喻或身份設定
- **Short mode**（預設）：1-3 sections，bullets ≤6 條，paragraph ≤150 字，目標兩頁
- **Medium mode**：section 數量不限，可延伸分析

### Word 輸出不含 references
`company_info` / `person_info` 的 Word 文件**不含**內文引用標記（`[N]`）和「參考來源」section。來源資訊只存於 `.log` sidecar，不出現在文件裡。`WordBuilder.add_references()` 方法仍存在於 formatter，但這兩個 agent 不呼叫它。

### confirm() 的範圍限制
`planner.confirm()` 展示的是 Haiku 解析出的 `task.instruction`，讓使用者在執行前確認或修改。**Tavily 搜尋 queries 是在 confirm 之後、agent Node 1 內部才生成**，使用者看不到。若 query 生成跑偏（如研究對象被誤解為產業生態），只能在 confirm 階段透過修改 instruction 間接影響。

### verbal_cleanup 必須手動指定
`verbal_cleanup` 在 `_MANUAL_ONLY_TYPES`，Haiku 不會自動分類到這個 type。必須用 `--type verbal_cleanup` 明確指定，否則會被分類成其他 agent。

### OCR（`utils/ocr.py`）
`extract_text(path)` — 圖片或 PDF → 純文字，供 translation agent 使用：
- 圖片（.jpg/.jpeg/.png/.gif/.webp）：base64 → Claude Haiku Vision
- PDF：PyMuPDF 逐頁轉 PNG → 逐頁 OCR 合併
- 自動壓縮超過 3.6MB 的圖片（base64 後不超過 Claude 的 5MB 上限）
- OCR prompt 設計為「純輸出文字，不評論」，避免模型拒絕有版權內容

### Cost Tracking
`utils/cost_tracker.py` singleton `tracker`：
- agent 內呼叫 `tracker.record_claude()` / `tracker.record_tavily()` 記錄
- `record_claude()` 必須傳入實際使用的 model（`LLM_FAST` 或 `LLM_MAIN`），不能混用
- `main.py` 每個任務完成後呼叫 `tracker.print_task_summary()`（印當前任務費用）
- `translate.py` 直接執行時同樣呼叫 `print_task_summary()`
- Session 結束呼叫 `tracker.print_summary()`（印總計）

### Financial Data Layer（`utils/financial_tools.py`）
`company_info_agent` 在 `parse_task` 之後執行 Haiku Q1/Q2/Q3 三問分類，Q2 與 Q3 獨立觸發不同 node：

| 問題 | 判斷內容 | 觸發 node | 資料來源 |
|---|---|---|---|
| Q1 + Q2 | 特定上市公司 + 需要財務數據 | `fetch_financial_data` | yfinance |
| Q3 | 需要產業 / 地區公司清單 | `fetch_sector_data` | FinanceDatabase |

**Q2 工具**（`YFINANCE_TOOL_DESCRIPTIONS` / `TOOL_REGISTRY`）：
- `stock_price` — 近 3 個月股價走勢、現價、52 週高低
- `financials`  — 最新季度財報（損益 / 資產負債 / 現金流量）
- `key_metrics` — 估值指標（市值、PE、EV/EBITDA、股息率、Beta）
- `holders`     — 前 10 大機構股東
- `news`        — Yahoo Finance 最新 5 則新聞

**Q3 工具**（`SECTOR_TOOL_DESCRIPTIONS` / `SECTOR_TOOL_REGISTRY`）：
- `sector_scan` — FinanceDatabase 依 sector + country 列出上市公司清單（預設最多 30 筆）

兩個 fetch node 都是 no-op when 條件不滿足，不需要 conditional edge。呼叫之間有 `_CALL_DELAY`（預設 1.5s）rate limiting；失敗回傳 `{"error": "..."}` 並印警告，不中斷流程。

新增工具：yfinance 工具加入 `TOOL_REGISTRY` + `YFINANCE_TOOL_DESCRIPTIONS`；新資料庫工具加入各自的 `*_TOOL_REGISTRY` + `*_TOOL_DESCRIPTIONS`，並在 prompt 新增對應 Qn。

Financial / sector data 以結構化 JSON 注入 `generate_report` context；財務數字優先採用 yfinance，Tavily 數字僅作背景參考。所有 fetched data 同時寫入 `.log` sidecar（`--- Financial Data ---` / `--- Sector Data ---` 區塊）。

## 尚未建置
- `agents/word_count_agent.py` — 字數統計（純文字，不輸出 Word）
- `delivery/email_draft.py` — email 草稿生成

## Reference Files（範本）
路徑：`/Users/junjie/Library/CloudStorage/OneDrive-個人(2)/Internship/Works/`
- company_info：`2026.03.26_Nutrition Startup Huel_Justin.docx`
- person_info：`2026.04.02_林振宏_Justin.docx`
- podcast：`2026.03.25_K-pop_Podcast.docx`
