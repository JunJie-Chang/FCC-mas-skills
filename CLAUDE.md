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

# 結構化資料調查（產業 / 地區 Top N + 多公司比較）
python3.13 agents/sector_scan_agent.py --task "列出台灣前十大半導體公司，比較市值與 PE" --intern "Justin"
python3.13 main.py --input "列出香港金融業前 20 家，按市值排序" --type sector_scan --intern "Justin"

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
confirm() — CLI 互動：y 確認 / n 取消 / [數字] 修改 / d[數字] 刪除 / a 新增 / m a,b[,c] 合併
    ↓
router.dispatch(task, intern_name, task_date, subdir, mode)
    ↓
agent.run(...)  →  WordBuilder.save()  →  output/ + ~/Downloads
```

### Agent 清單
| agent_type | 檔案 | 說明 |
|---|---|---|
| `company_info` | `agents/company_info_agent.py` | 公司/機構研究，10-node graph（含財務資料層 + ReAct loop） |
| `person_info` | `agents/person_info_agent.py` | 人物背景，8-node ReAct loop graph |
| `sector_scan` | `agents/sector_scan_agent.py` | 結構化資料調查（產業 + 地區 Top N + 多公司比較）；FDB enum 作前置 gate，不可行任務直接出 note doc |
| `translation` | `agents/translation_agent.py` | 翻譯；router 傳 JSON instruction（含 title/source/body_text，`pub_date` 選填，沒給 fallback 今天）；`--body-file` 支援 .jpg/.png/.pdf OCR |
| `letter`/`meeting` | `agents/dictation_agent.py` | 口述整理，兩種 task_type 共用同一 agent |
| `verbal_cleanup` | `agents/verbal_cleanup_agent.py` | 口述清稿，去除廢話與開頭語，輸出乾淨書面稿 |
| `podcast` | `agents/podcast_agent.py` | Podcast 研究；屬 `_MANUAL_ONLY_TYPES`，必須 `--type podcast`；router 傳 raw 原文，agent 內 `parse_instruction` node 用 Haiku 解析 topic/questions；全文抓取用 trafilatura（失敗 fallback 到 Tavily snippet） |
| `speech_ppt` | `agents/speech_ppt_agent.py` | 演講 PPT；輸入 CY 口述 transcript；結構化頁自動生成（DALL-E），非結構化頁 echo notes；需 OPENAI_API_KEY |

### Agent 內部結構

**company_info**（11-node LangGraph，ReAct loop + numbers layer）：
1. `parse_task` — Haiku 產出 research plan（todos 3-6 個問題）+ 初始 queries（推論式設計，搜一手來源）
2. `check_financial_need` — Haiku Q1/Q2/Q3 分類（見下方 Financial Data Layer）
3. `fetch_financial_data` — ticker 解析 + yfinance 抓取；**conditional edge**：Q2=[] 跳過
4. `fetch_sector_data` — FinanceDatabase 產業掃描；Q3.needed=N 時 no-op
5. `run_search` — 執行初始 batch queries，結果存入 evidence pool
6. `evaluate` — Haiku 評估每個 todo：done / pending / unresolved；連續 2 輪無新資料自動 done
7. `next_action` — Haiku 依 todo 狀態決定下一條搜尋 query（或觸發 done）
8. `execute_search` — 執行單條 query，結果追加 evidence pool；**loop back to evaluate**
9. `extract_numbers` — Haiku verbatim echo evidence 內所有相關數字 → Python 確定性轉中文字串（見下方 Numbers Layer）
10. `generate_report` — Sonnet（short）/ Opus（medium）合成 JSON 報告；evidence + `numbers_zh` 注入 context
11. `format_output` — WordBuilder 渲染 docx，AgentLogger 寫同路徑 `.log`

**company_info loop 控制**：`MAX_ROUNDS=6`（hard cap）；所有 todo 皆 done 或 unresolved 提前結束；連續 2 輪 0 結果（stall）強制結束

**person_info**（9-node LangGraph，同 ReAct loop + numbers layer）：同 company_info，無財務資料層（無 check_financial_need / fetch_financial_data / fetch_sector_data）；`MAX_ROUNDS=5`

**sector_scan**（4-node LangGraph，conditional edge）：
1. `parse_request` — Haiku 拿 `get_fdb_enum()` 載入的 enum，做 feasibility 判斷 + 鎖定 `industry / country / top_n / rank_by / metrics`；defensive 二次驗證 Haiku 給的 industry 真的在 enum 內，否則自動翻 N
2. conditional edge `_is_feasible` — Y → `fetch_companies`；N → `format_output` 出 note doc 建議走 `company_info` + Tavily fallback
3. `fetch_companies` — `fetch_sector_scan(industry, country, limit=top_n*3)` over-fetch 3x 抗 yfinance miss
4. `enrich_metrics` — 對每個 ticker 呼叫 yfinance（`_PER_TICKER_DELAY=1.5s`），按 `rank_by` 排序，截 `top_n`
5. `format_output` — 摘要段 + Table Grid 表格；數值格式化（B for billions / x for PE / +%.2f% for change_3mo）

**sector_scan 任務分類觸發**：planner Haiku 看到「前十大 / Top X / 列出 / 排名 / 比較 / 哪些公司」+「同產業／同地區」+「市值 / PE / 營收」即優先選 `sector_scan`；單一公司研究即使含財務數字仍走 `company_info`。

**sector_scan 不可行的判斷**：FinanceDatabase 沒有對應分類的請求（如「AI 概念股」「重電股」「綠能新貴」「年終排名」），Haiku 設 `feasible=N`，graph 直接跳 `format_output` 出 note doc 建議 fallback。

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
- `company_info` / `person_info` / `dictation` / `sector_scan`：router 用 `**kwargs` 呼叫，State TypedDict 和 `run()` 都必須包含 `mode` 欄位
- `podcast` / `speech_ppt` / `translation`：router 個別傳參，不走 `**kwargs`，不需要 `mode`
- 新增走 `**kwargs` 路徑的 agent，`run()` 必須接受 `mode: str = "short"` 以免 TypeError

### Word 格式規範
由 `formatters/word_formatter.py` 的 `WordBuilder` 統一處理：
- 字體：微軟正黑體（ascii + eastAsia + hAnsi + cs 四個 slot 都設）
- Title 14pt Bold；Body 14pt Normal；行距 1.15 multiple
- 頁面：A4，margins top/bottom=2.5cm, left/right=3.2cm
- 頁面邊框：四邊 single，sz=12，space=24，offsetFrom=page
- Header：右對齊「Private & Confidential」，11pt Bold 紅色斜體
- 表格：`add_table()` 套 `Table Grid` style → 內外四邊細黑線
- Podcast 文章標題：`add_red_underline_title_with_subtitle(title, subtitle)` 產出紅字 Bold underline 主標 + soft break (`w:br` = shift+enter) + 黑字副標（格式 `YYYY.MM.DD_intern_媒體_作者`，缺欄位略過）
- `save()` 自動複製到 `~/Downloads`，無 PDF 輸出（已廢棄移除）
- 命名：`YYYY.MM.DD_TaskName_InternName.docx`（`utils/file_naming.general()` 產生）

### generate_report Prompt 規則（所有 agent 適用）
- **時間錨點**：所有 prompt 開頭注入 `config.time_context()`（「現在是 YYYY 年；t=YYYY / t-1=... / t-2=...」），避免模型把訓練 cutoff 年份（常為 2024）當作 t
- 不在任何名詞後加括號標注其他語言的原文或譯名（不論英文、越南文或任何語言）
- 不在報告內容中提及任務指令的措辭、比喻或身份設定
- **絕對禁止免責聲明**：不得出現「僅供參考」「請以官方為準」「資料可能有誤」等 hedge / disclaimer
- **禁用空洞修辭清單**：禁用「成長雙位數」「戰略佈局」「行業領先」「持續優化」等沒有資訊量的詞；必須給具體數字 / 名稱 / 日期，evidence 沒有就明寫「資料不足」
- **yfinance 引用必附日期**：股價用 `as_of` 欄位，財報數字用 `period_end` 欄位（如「2026 Q1（截至 2026-03-31）」「截至 2026-05-07」）
- **Short mode**（預設）：1-3 sections，bullets ≤6 條，paragraph ≤150 字，目標兩頁；合成用 `LLM_SYNTHESIS`（Sonnet）
- **Medium mode**：section 數量不限，可延伸分析；合成用 `LLM_MAIN`（Opus）
- **Section types**：`bullets`（條列）/ `paragraph`（敘述）/ `table`（多欄比較，含 headers + rows）；Sonnet/Opus 自選最合適的
- **結構化數字 echo 規則**（rule 9 in prompt）：context 內若有 `[結構化數字]` 區塊，該區塊中文字串為最終格式，必須**逐字 echo**；禁止改寫、禁止重算單位、禁止用「約 / 大約 / 近 / 逾 / 超過」前綴包裹（除非 evidence 本身就有這些字）— 這條規則是 Numbers Layer 的對接點

### Numbers Layer（`utils/number_extract.py` + `utils/unit_convert.py`）

**為什麼存在**：issue #8 case — GameStop/eBay 報告同段內把 "$9.4 billion" 寫成「9.4 億美元」（應為 94 億）。根因是 synthesizer LLM 在長 prose 生成中對「相同量綱重複轉換」會掉位。`extract_numbers → 結構化數字 echo` 把單位換算從 LLM 移出。

**兩步式 pipeline**：
1. `extract_numbers` node — Haiku **verbatim echo** evidence 內所有任務相關數字，產出 `[{label, raw, value, scale, currency}, ...]`；**禁止計算 / 翻譯 / 推單位**，找不到就漏掉，不准捏造
2. `utils/unit_convert.to_chinese_amount(value, scale, currency)` — 純 Python 確定性轉換為 `"XX 億美元"` / `"X.X 兆新台幣"` / `"XX%"` 等中文字串

**注入點**：`generate_report` context 的最後一段（在 evidence / financial_data / sector_data 之後），透過 `format_for_prompt(numbers_zh)` 渲染。Synthesizer rule 9 強制 echo。

**Scale 字典**（`SCALE_MULTIPLIERS` in `utils/unit_convert.py`）：`plain / ten_thousand / thousand / million / hundred_million / billion / trillion`，加上 `percent` / `ratio` 兩個 passthrough。

**中英 scale 對應**（issue #16 — 對稱於 #8 的反向 case）：
- 中文「萬」 → `ten_thousand` (1e4)
- 中文「億」 → `hundred_million` (1e8)  **← 不是 billion（1e9 差 10 倍）**
- 中文「兆」 → `trillion` (1e12)
- 英文 thousand/million/billion/trillion → 同名 scale

`number_extract.py` 的 Haiku echo prompt 強制：中文「億」/「亿」echo 為 `hundred_million`、不要翻譯成 `billion`。違反這條會產生 10× inflation bug（佰維 8.67 億 → 86.7 億、國泰 140 億 → 1,400 億 等實際案例）。

**Currency 字典**（`CURRENCY_ZH`）：USD/TWD/NTD/HKD/CNY/RMB/JPY/EUR/GBP/KRW/SGD → 中文名。

**確定性轉換規則**（`to_chinese_amount`）：value × scale_multiplier → base units → 自動依量級選 萬 / 億 / 兆 單位，附中文貨幣名。例：`(9.4, "billion", "USD")` → `"94 億美元"`。

**失敗模式**：Haiku 回傳 JSON 解析失敗 → 印警告、回傳空 dict、graceful degrade（synthesizer 沒拿到 `numbers_zh` block，照舊跑）。

**Audit 追蹤**：每筆 echo 連同 derived Chinese 都寫入 `.log` 的 `--- Extracted Numbers ---` 區塊，方便對照 raw → zh 是否正確。

**成本**：每次 agent run 多一次 Haiku 呼叫（evidence cap 50k 字元），約 $0.01-0.02 等級。

**Self-test**：`python3.13 utils/unit_convert.py` 跑 24 個 case（含 #8 的 GameStop 9 vs 9.4 billion 與 #16 的中文「億」/「兆」/「萬」回歸）；所有 case 過才能 ship。新增 scale / currency 時加 case。

**目前接入**：`company_info_agent` 與 `person_info_agent`。新增 research agent 若會引用 evidence 數字，照樣插入 `evaluate(done) → extract_numbers → generate_report` 並在 prompt 加 rule 9。

### 時間錨點 helper（`config.time_context()`）
所有觸及「最新」「最近一季」「去年」「年初至今」等相對時間的 LLM prompt 都要在開頭注入 `config.time_context()`。注入點：
- `utils/planner.py` parse_tasks
- `agents/company_info_agent.py` parse_task / generate_report
- `agents/person_info_agent.py` parse_task / generate_report
- `utils/react_loop.py` next_action / evaluate
- `agents/podcast_agent.py` generate_queries
- `agents/sector_scan_agent.py` parse_request

新增有時間敏感性的 prompt 時務必加注入。

### Word 輸出不含 references
`company_info` / `person_info` 的 Word 文件**不含**內文引用標記（`[N]`）和「參考來源」section。來源資訊只存於 `.log` sidecar，不出現在文件裡。`WordBuilder.add_references()` 方法仍存在於 formatter，但這兩個 agent 不呼叫它。

### podcast 的 planner 特殊規則
`podcast` 屬 `_MANUAL_ONLY_TYPES`，Haiku 不自動分類。必須 `--type podcast`。`parse_tasks()` early return：raw 原文原封不動傳給 agent，不被 Haiku 改寫。topic/questions 解析在 agent 內的 `parse_instruction` node（Haiku）執行。router 直接傳 `task_instruction=raw`，不再解析 JSON。

### podcast 的 domain 過濾與白名單
**兩層過濾**：
1. `_BLOCKED_DOMAINS`：完全封 — 社群 / 影音 / 低品質站。包含 Facebook、Twitter/X、Instagram、TikTok、Reddit、Weibo、微信、Threads 以及 **YouTube、LinkedIn**（podcast 任務只要文字稿，影音 / 社交不夠正式）
2. `_NEWS_WHITELIST`：~38 站新聞白名單，分四層 — 台灣主流（cna / ctee / udn / ltn / chinatimes / ettoday / bnext / 商周 / 財訊 / 天下 等）/ 台灣產業專業（digitimes / ithome / techorange / inside / 36kr）/ 國際中文（BBC / 紐時中文 / RFA / VOA / DW / 財新 / 21 經濟 等）/ 國際英文（reuters / bloomberg / ft / nytimes / wsj / nikkei / techcrunch / scmp 等）

**過濾流程**：
- url 在 `_BLOCKED_DOMAINS` → skip
- 字數 < `_MIN_ARTICLE_CHARS=50` → skip（只擋明顯 snippet stub）
- url 在 `_NEWS_WHITELIST` → 接收 + 標 verified
- url 不在白名單也不在 blocked → 接收但 `.log` 標 `[unverified_source]`（給校稿用）

新增白名單站時，加進對應分類即可，不需改邏輯。

### confirm() 的範圍限制
`planner.confirm()` 展示的是 Haiku 解析出的 `task.instruction`，讓使用者在執行前確認或修改。**Tavily 搜尋 queries 是在 confirm 之後、agent Node 1 內部才生成**，使用者看不到。若 query 生成跑偏（如研究對象被誤解為產業生態），只能在 confirm 階段透過修改 instruction 間接影響。

### confirm() 的 merge 指令
使用者輸入 `m a,b[,c]`（如 `m 1,3` 或 `m 1,3,5`），planner 把指定編號的多個 PlanTask 透過 Haiku 合併成一條，agent_type 採多數決（平手保留第一個任務的 type 維持順序意圖）。合併結果插回最低 index 位置，其餘 pop 掉。用於救「同主題被 Haiku 誤拆」的情境（補強 planner 內建合併規則的盲點）。

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
| Q1 + Q2 | 任務「明確需要」該公司的市場交易資料（股價/估值/財報數字） | `fetch_financial_data` | yfinance |
| Q3 | 需要產業 / 地區公司清單 | `fetch_sector_data` | FinanceDatabase |

**Q1 收緊條件（wave 2）**：明列 Y 觸發詞（股價 / 市值 / PE / EV/EBITDA / 股息 / 最新財報數字 / 機構持股 / Yahoo 新聞）、N 條件（純業務面研究即使帶 ticker 也 N）、保守原則（不確定 → N）。意圖：避免每個帶公司名的任務都觸發財務層。

**Multi-ticker 結構（issue #13）**：`check_financial_need` 輸出 `tickers: list[str]`（最多 3 個，主角優先）+ `company_name: str`（fallback）兩個互斥欄位，取代舊的單一 `company_name`：
- Haiku 能直接判定 ticker → 填 `tickers`（純字串，dedup + uppercase + cap 3），`company_name=""`
- Haiku 不確定 → `tickers=[]`，`company_name` 填乾淨單一公司名走 `resolve_ticker`
- `fetch_financial_data` 先驗證 direct tickers 通過 `_is_valid_ticker_format`；通過的直接 `fetch_all` 抓資料、bypass Haiku #2；都沒過才走 company_name fallback path
- 適用情境：M&A 雙方都列、Apple/Tesla 等熟公司省一次 Haiku 呼叫、`GameStop (GME)` 這類括號干擾下游的 case 也直接收掉

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

**`financial_data` state 結構（multi-ticker）**：
```python
{
    "GME":  {"stock_price": {...}, "financials": {...}, ...},    # tool_id keys
    "EBAY": {"stock_price": {...}, ...},
    "_resolve_failed": ["..."],                                  # optional
}
# or, when no ticker resolves at all:
{"_ticker_error": "...", "_resolve_failed": [...]}
```
Top-level keys 是 ticker（uppercase），meta keys 以 `_` 開頭。`generate_report` 對每個非 `_` 開頭的 key 注入一個 `[結構化財務資料 — TICKER（來自 yfinance）]` block；`logger` 每個 ticker render 一個 `--- Financial Data (TICKER | yfinance: ...) ---` 區塊。

**synth prompt rule 6 為 multi-ticker 強化**：引用 yfinance 數字時必須指明是哪一家公司（例：「GME 市值 103.9 億美元」），避免混淆來源。

Financial / sector data 以結構化 JSON 注入 `generate_report` context；財務數字優先採用 yfinance，Tavily 數字僅作背景參考。所有 fetched data 同時寫入 `.log` sidecar。

**Ticker 解析（`resolve_ticker(strict=True)` 為新預設）**：

`strict=True`（預設，給 `fetch_financial_data` 用），三段順序：
1. **Inline ticker prefilter**（issue #17）— 用 `_TICKER_INLINE_RE` 在 `company_name + task_context` 字面找明確 ticker pattern（如 `601138.SH`、`2317.TW`），找到就直接 return，bypass Haiku。專治 instruction 字面已給 ticker 但 Haiku #2 hallucinate 成別家公司的 case
2. **Haiku normalizer**（`_haiku_normalize_ticker(strict=True)`）— Haiku 必須 `confidence=high` 且 ticker 通過 `_VALID_TICKER_RE`（US ≤5 字母 / `.TW/.TWO/.HK/.SZ/.SS/.SH/.T/.KS/.L/.TO/.AX/.PA/.DE` 等市場後綴）；medium 直接擋掉
3. **Cross-check**：若 inline prefilter 找到的 ticker 跟 Haiku 給的不同，採用 inline 的（防 Haiku 寧可亂猜也不 return null）

不走 yf.Search / FinanceDatabase fuzzy fallback — 寧可跳過財務層，也不餵 yfinance 非法 symbol（如 `industry='semiconductor company'`）。

**`.SH` → `.SS` canonicalization**：上交所 ticker 在 Wind / 同花順 / 新浪財經 / CY 口述用 `.SH`，但 yfinance 只認 `.SS`（用 `.SH` 會 404）。`_canonicalize_ticker()` 在 `resolve_ticker` / `fetch_all` / agent 的 direct ticker 收集處統一轉換。`_VALID_TICKER_RE` 接受兩種輸入。

`strict=False`（legacy 路徑，可給未來 discovery / sector 用）：
- 三段 fallback：Haiku（high+medium）→ yf.Search → FinanceDatabase

**`as_of` / `period_end` 欄位（wave 1）**：
- `fetch_stock_price` payload 含 `as_of` = last bar 日期（YYYY-MM-DD，不是 fetch 時間）
- `fetch_financials` 含 `period_end` dict（`income_stmt_latest_q` / `balance_sheet_latest_q` / `cashflow_latest_q` 各自的期末日）
- 其餘 fetcher 含 `as_of` = Asia/Taipei fetch 時間
- `generate_report` prompt 強制：引用 yfinance 數字必附資料日期

**FDB enum cache（`get_fdb_enum()`）**：一次性載入 FinanceDatabase 的 sector / industry_group / industry / country / exchange enum，cache 到 `utils/_fdb_enum.json`（committed for fresh-checkout convenience）。`sector_scan_agent` 用這個 cache 把 enum 列進 prompt，讓 Haiku 只能逐字選用，杜絕非法 industry 值。需要 refresh 時刪掉 JSON 即可。

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
