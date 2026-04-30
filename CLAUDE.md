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
python3.13 translate.py "Article Title" SourceName 2026-04-15 "Justin,Neil"   # 多人用 comma 分隔
# → 貼文章，輸入 END + Enter 結束

# 翻譯 + OCR（圖片或 PDF，例如 iPhone AirDrop 截圖）
python3.13 translate.py "Article Title" SourceName 2026-04-15 Justin --image ~/Downloads/IMG_xxxx.JPG
python3.13 translate.py "Article Title" SourceName 2026-04-15 Justin --pdf ~/Downloads/article.pdf
# PDF 需先安裝：pip install pymupdf

# 直接跑單一 agent
python3.13 agents/company_info_agent.py --task "查 Tesla" --intern "Justin"

# Podcast agent 直接執行（--questions 用分號分隔，不是 JSON array）
python3.13 agents/podcast_agent.py \
  --topic "全球媒體產業" \
  --questions "問題1; 問題2; 問題3" \
  --intern "Justin"

# 口述清稿（去除廢話與開頭語）
python3.13 agents/verbal_cleanup_agent.py --audio ~/Downloads/recording.m4a --intern "Justin"
python3.13 agents/verbal_cleanup_agent.py --text "嗯好那個今天想說的是..." --intern "Justin"
python3.13 main.py --audio recording.m4a --type verbal_cleanup --intern "Justin"

# 演講 PPT（結構化頁自動生成；非結構化頁 echo notes 給操作者）
python3.13 agents/speech_ppt_agent.py --audio ~/Downloads/recording.m4a --intern "Justin"
python3.13 agents/speech_ppt_agent.py --audio ~/Downloads/recording.m4a --topic "台中智慧製造" --intern "Justin"
python3.13 agents/speech_ppt_agent.py --text "第一頁：智慧製造定義..." --intern "Justin" --no-images
python3.13 main.py --audio recording.m4a --type speech_ppt --intern "Justin"
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
| `podcast` | `agents/podcast_agent.py` | Podcast 研究；屬 `_MANUAL_ONLY_TYPES`，必須 `--type podcast`；router 傳 raw 原文，agent 內 `parse_instruction` node 用 Haiku 解析 topic/questions；全文抓取用 trafilatura（失敗 fallback 到 Tavily snippet） |
| `speech_ppt` | `agents/speech_ppt_agent.py` | 演講 PPT；輸入 CY 口述 transcript；結構化頁自動生成（DALL-E），非結構化頁 echo notes；需 OPENAI_API_KEY |

### Agent 內部結構

**company_info**（10-node LangGraph，ReAct loop）：
1. `parse_task` — Haiku 產出 research plan（todos 3-6 個問題）+ 初始 queries（推論式設計，搜一手來源）
2. `check_financial_need` — Haiku Q1/Q2/Q3 分類（見下方 Financial Data Layer）
3. `fetch_financial_data` — ticker 解析 + yfinance 抓取；**conditional edge**：Q2=[] 跳過
4. `fetch_sector_data` — FinanceDatabase 產業掃描；Q3.needed=N 時 no-op
5. `run_search` — 執行初始 batch queries，結果存入 evidence pool
6. `evaluate` — Haiku 評估每個 todo：done / pending / unresolved；連續 2 輪無新資料自動 done
7. `next_action` — Haiku 依 todo 狀態決定下一條搜尋 query（或觸發 done）
8. `execute_search` — 執行單條 query，結果追加 evidence pool；**loop back to evaluate**
9. `generate_report` — Sonnet（short）/ Opus（medium）合成 JSON 報告；evidence 全部注入 context
10. `format_output` — WordBuilder 渲染 docx，AgentLogger 寫同路徑 `.log`

**company_info loop 控制**：`MAX_ROUNDS=6`（hard cap）；所有 todo 皆 done 或 unresolved 提前結束；連續 2 輪 0 結果（stall）強制結束

**person_info**（8-node LangGraph，同 ReAct loop）：同 company_info，無財務資料層（無 check_financial_need / fetch_financial_data / fetch_sector_data）；`MAX_ROUNDS=5`

**speech_ppt**（4-node LangGraph）：
1. `parse_script` — opus 解析 transcript，分類每頁為 structured / unstructured；同時推斷演講題目
2. `confirm_slides` — CLI 互動展示計劃（標題 + bullets + notes 預覽），**確認後才生成 DALL-E**；取消則 END
3. `generate_images` — DALL-E 3，只對 structured 頁，最多 retry 3 次；`--no-images` 跳過
4. `build_ppt` — 用 python-pptx 建立 structured 頁（標題 + 5 bullets + 右側圖）；unstructured 頁僅 echo notes 到 console + `.log` sidecar

**speech_ppt 的 planner 特殊規則**：同 `verbal_cleanup`，加入 `_MANUAL_ONLY_TYPES`。Haiku 不自動分類，必須 `--type speech_ppt`。`parse_tasks()` early return：raw transcript 原封不動包成一個 PlanTask，不被 Haiku 改寫。

**speech_ppt 的 confirm_slides vs planner.confirm() 的分工**：
- `planner.confirm()`（外層）：確認「這個任務要交給 speech_ppt agent 執行」
- `confirm_slides`（內層，agent 內）：確認「這些投影片標題 + bullets 是否正確」，此時才燒 DALL-E

**PPTX 版面規格**（10.0" × 7.5"，`assets/ppt_chrome_template.pptx` OBJECT layout）：
- 背景（深藍漸層）、橫線（`#9CC2E5`，y≈1.308in）、右下角 logo、左下角「藍濤亞洲 FCC Partners」標籤、頁碼 placeholder：全部繼承自 OBJECT layout，不需手動加
- Title textbox：(0.51, 0.40) 8.98 × 0.93 in，28pt，白色（`#FFFFFF`）
- Bullets textbox（左半）：(0.51, 1.49) 4.70 × 4.31 in，24pt Bold，白色，150% 行距，10pt spcBef，hanging indent，白色 `•` bullet character
- Image（右半）：(5.45, 1.49) 4.20 × 4.31 in，DALL-E 3 寫實風格，無文字
- Page num：繼承自 layout sldNum placeholder（自動 field）

**Chrome template 維護**：`assets/ppt_chrome_template.pptx` 存在 repo，從 `_PPT_REFERENCE`（OneDrive 的參考 PPTX）以 `_ensure_chrome_template()` 自動建立。template 不存在時首次執行自動重建；reference PPTX 不在時 fallback 到 blank layout。

### utils/react_loop.py — 共用 ReAct loop

`company_info` 和 `person_info` 共用的搜尋迴圈邏輯，避免重複程式碼。

**Public API**：
- `run_initial_search(state)` — 執行 parse_task 產出的初始 batch queries，結果存入 evidence pool
- `next_action(state, max_rounds, search_hint)` — Haiku 決定下一條 query（推論式設計）
- `execute_search(state)` — 執行單條 query，追加 evidence
- `evaluate(state)` — Haiku 標記各 todo 為 done / pending / unresolved
- `should_continue(state, max_rounds)` — conditional edge function，回傳 `"loop"` 或 `"done"`

**常數**：`RESULTS_PER_QUERY=3`、`STALL_ROUNDS=2`

**各 agent 的包裝方式**：每個 agent 定義 `_MAX_ROUNDS` 和 `_SEARCH_HINT` 常數，再用薄包裝函式呼叫 react_loop 的 public API，讓 LangGraph 拿到正確的 TypedDict 型別標注。新增同樣需要 ReAct loop 的 research agent 時直接 import 並包裝，不需修改 react_loop.py。

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
- **絕對禁止免責聲明**：不得出現「僅供參考」「請以官方為準」「資料可能有誤」等 hedge / disclaimer
- **Short mode**（預設）：1-3 sections，bullets ≤6 條，paragraph ≤150 字，目標兩頁；合成用 `LLM_SYNTHESIS`（Sonnet）
- **Medium mode**：section 數量不限，可延伸分析；合成用 `LLM_MAIN`（Opus）
- **Section types**：`bullets`（條列）/ `paragraph`（敘述）/ `table`（多欄比較，含 headers + rows）；Sonnet/Opus 自選最合適的

### Word 輸出不含 references
`company_info` / `person_info` 的 Word 文件**不含**內文引用標記（`[N]`）和「參考來源」section。來源資訊只存於 `.log` sidecar，不出現在文件裡。`WordBuilder.add_references()` 方法仍存在於 formatter，但這兩個 agent 不呼叫它。

### podcast 的 planner 特殊規則
`podcast` 屬 `_MANUAL_ONLY_TYPES`，Haiku 不自動分類。必須 `--type podcast`。`parse_tasks()` early return：raw 原文原封不動傳給 agent，不被 Haiku 改寫。topic/questions 解析在 agent 內的 `parse_instruction` node（Haiku）執行。router 直接傳 `task_instruction=raw`，不再解析 JSON。

### podcast 的 domain 過濾
`_BLOCKED_DOMAINS` 封社群 / 低品質站（Facebook、Twitter / X、Instagram、TikTok、Reddit 等）；`_BLOCKED_HOMEPAGE_DOMAINS`（YouTube、LinkedIn）只封首頁（`path in ("", "/")`），放行 `/watch`、`/posts/` 等內容路徑。原因：這兩個網站是 podcast 訪談原生平台，完全封鎖會漏掉主要來源。新增 podcast 常見平台時先評估是要完全封還是只封首頁。

### confirm() 的範圍限制
`planner.confirm()` 展示的是 Haiku 解析出的 `task.instruction`，讓使用者在執行前確認或修改。**Tavily 搜尋 queries 是在 confirm 之後、agent Node 1 內部才生成**，使用者看不到。若 query 生成跑偏（如研究對象被誤解為產業生態），只能在 confirm 階段透過修改 instruction 間接影響。

### verbal_cleanup 必須手動指定
`verbal_cleanup` 在 `_MANUAL_ONLY_TYPES`，Haiku 不會自動分類到這個 type。必須用 `--type verbal_cleanup` 明確指定，否則會被分類成其他 agent。

此外，`parse_tasks()` 對 `_MANUAL_ONLY_TYPES` 的 `force_type` 做 early return：不呼叫 Haiku，直接把原始 `raw_instruction` 原封不動包成一個 `PlanTask`（label 取前 30 字 + `...`）。這保證 verbal_cleanup agent 收到的是完整 STT 原文，不會被 planner Haiku 改寫成摘要。未來若加其他「原文照搬」型 agent，加進 `_MANUAL_ONLY_TYPES` 即自動獲得此行為。

### OCR（`utils/ocr.py`）
`extract_text(path)` — 圖片或 PDF → 純文字，供 translation agent 使用：
- 圖片（.jpg/.jpeg/.png/.gif/.webp）：base64 → Claude Haiku Vision
- PDF：PyMuPDF 逐頁轉 PNG → 逐頁 OCR 合併
- 自動壓縮超過 3.6MB 的圖片（base64 後不超過 Claude 的 5MB 上限）
- OCR prompt 設計為「純輸出文字，不評論」，避免模型拒絕有版權內容

### Cost Tracking
`utils/cost_tracker.py` singleton `tracker`：
- agent 內呼叫 `tracker.record_claude()` / `tracker.record_tavily()` / `tracker.record_dalle()` 記錄
- `record_claude()` 必須傳入實際使用的 model（`LLM_FAST` 或 `LLM_MAIN`），不能混用；遇到不在 `_CLAUDE_PRICES` 的 model 會印一次 `[cost] ⚠ unknown model ...` 警告再用 `_default` 估價（不會 silent fallback）
- `main.py` 每個任務完成後呼叫 `tracker.print_task_summary()`（印當前任務費用，包含 Claude / Whisper / DALL-E / Tavily）
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

`fetch_financial_data` 走 conditional edge（Q2=[] 時由 `check_financial_need` 直接跳到 `fetch_sector_data`，不浪費 ticker 解析呼叫）。`fetch_sector_data` 是 no-op when Q3.needed≠Y。呼叫之間有 `_CALL_DELAY`（預設 1.5s）rate limiting；失敗回傳 `{"error": "..."}` 並印警告，不中斷流程。

新增工具：yfinance 工具加入 `TOOL_REGISTRY` + `YFINANCE_TOOL_DESCRIPTIONS`；新資料庫工具加入各自的 `*_TOOL_REGISTRY` + `*_TOOL_DESCRIPTIONS`，並在 prompt 新增對應 Qn。

Financial / sector data 以結構化 JSON 注入 `generate_report` context；財務數字優先採用 yfinance，Tavily 數字僅作背景參考。所有 fetched data 同時寫入 `.log` sidecar（`--- Financial Data ---` / `--- Sector Data ---` 區塊）。

**Ticker 解析流程（三段 fallback）**：`resolve_ticker(company_name, task_context)` 依序嘗試：
1. `_haiku_normalize_ticker` — Haiku 讀公司名 + task 內容，直接輸出 market-correct ticker（懂 .TW / .TWO / .HK / .SZ / .SS / .T / .KS / 美股字母）；`confidence=low` 視為 None 不採用
2. `yf.Search` — yfinance 模糊比對
3. FinanceDatabase `Equities().search`

三段都失敗才回 None，`fetch_financial_data` 把 `financial_data` 設為 `{"_ticker_error": "..."}`，log sidecar 寫 `--- Financial Data (not fetched) ---` 並印 WARNING。

**Data source self-declaring**：每個 fetcher 透過 `_tag_source()` 在成功 payload 加 `"_source": "yfinance"` 或 `"FinanceDatabase"`。`utils/logger.py` 讀每筆 payload 的 `_source`，動態產生 log label（例：`--- Financial Data (yfinance: stock_price, key_metrics) ---`），不再 hardcode。新增跨資料源 fetcher 時務必呼叫 `_tag_source()`。

## 尚未建置
- `delivery/email_draft.py` — email 草稿生成

## 已知問題與改進清單

下列為程式碼靜態審閱後仍未修的項目。M1-M5 / L1-L5 已於 2026-04-23 修復。


## Reference Files（範本）
路徑：`/Users/junjie/Library/CloudStorage/OneDrive-個人(2)/Internship/Works/`
- company_info：`2026.03.26_Nutrition Startup Huel_Justin.docx`
- person_info：`2026.04.02_林振宏_Justin.docx`
- podcast：`2026.03.25_K-pop_Podcast.docx`
