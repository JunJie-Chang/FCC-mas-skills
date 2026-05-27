# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview
FCC Partners 實習生日常工作流程自動化系統。

CY（老闆）口述指令 → Claude Code session 內讀 skill → 執行（搜尋 / 抓財務 / 翻譯 / 整理）→ Word / PowerPoint 輸出。

**架構演進**：2026 年 5 月之前是 LangGraph + FastAPI 多 agent 系統；之後重構成 Claude Code Skills（純本機、無 API 後端、單人 Claude Code 使用）。重構紀錄見 `/Users/junjie/.claude/plans/skills-api-skills-person-info-company-i-federated-aurora.md`。

## Environment
- **Python**：system Python 3.13 (`/Library/Frameworks/Python.framework/Versions/3.13`)
- `.env`：只需 `OPENAI_API_KEY`（STT + DALL-E 用）。`ANTHROPIC_API_KEY` 不再需要（Claude 在 Claude Code session 內執行）。`TAVILY_API_KEY` 不再需要（skill 直接呼叫 `tavily-*` skill 或 WebSearch 工具）。
- 所有 `load_dotenv()` 必須用 `override=True`，否則 shell 中已有空字串的 env var 會擋住 `.env` 的值
- **系統依賴**：`ffmpeg` / `ffprobe`（STT 對 >4 分鐘音檔切片用，見 `utils/stt.py`）；未安裝時長音檔轉錄會失敗（`brew install ffmpeg`）

## Skills（7 個）

放在 `.claude/skills/`（per-project，與 repo 一起 commit）。使用者在 Claude Code session 內輸入請求，Claude 依 description 自動觸發對應 skill，或使用者顯式輸入 `/<skill-name>`。

| Skill | 用途 | Trigger 範例 |
|---|---|---|
| `fcc-company-info` | 公司／機構研究 | 「查 Tesla」「Apple 跟 Foxconn 合作」「NVIDIA deep dive」 |
| `fcc-person-info` | 人物背景調查 | 「查蔡力行」「Jensen Huang 學經歷」 |
| `fcc-translation` | 外文翻譯成繁體中文 | 「翻這篇英文」「這張截圖幫我翻」「這個 URL 翻一下」 |
| `fcc-dictation` | 會議口述整理成會議紀錄 | 「整理這場會議」「會議 minutes」 |
| `fcc-verbal-cleanup` | 口述清稿（去廢話、留原意） | 「清稿」「把這段廢話清掉」「整理一封信」 |
| `fcc-podcast` | Podcast 研究蒐集翻譯多篇文章 | 「整理 K-pop podcast 研究」 |
| `fcc-speech-ppt` | 演講 PPT 生成 | 「把這段演講做成 PPT」 |
| `fcc-shared` | 共通規則 reference（不獨立觸發） | — |

每個 skill 的 SKILL.md 都列出 trigger 範例 + 不適合的情境（指向其他 skill）。`fcc-shared` 集中存放所有 skill 共用的寫作禁忌、Word 格式規範、檔名規範、中文數字單位規則、時間錨點。

## 保留的 Python 工具

Skills 透過 Bash 呼叫這些 helper。**不要在 skill 內重新實作這些邏輯**。

| 路徑 | 用途 |
|---|---|
| `scripts/build_docx_cli.py` | JSON spec → `.docx`（內部用 WordBuilder）。`python3.13 scripts/build_docx_cli.py --spec /tmp/spec.json` |
| `scripts/build_pptx_cli.py` | JSON spec → `.pptx`（含 DALL-E 圖片可選）。Self-contained，沒依賴 deprecated agent file |
| `formatters/word_formatter.py` | WordBuilder — 統一 Word 格式（A4、微軟正黑體 14pt、Private & Confidential 頁眉、頁碼、Table Grid 表格） |
| `utils/file_naming.py` | `general(task_name, intern_name, task_date, ext='docx')` → `YYYY.MM.DD_TaskName_Intern.docx` |
| `utils/unit_convert.py` | 中文金額確定性轉換（億 / 兆 / 萬）。Self-test：`python3.13 utils/unit_convert.py`（28 cases，需全過） |
| `utils/financial_tools.py` | yfinance + FinanceDatabase fetchers。`fetch_all(ticker, tools=[...])` 是主要進入點。**Skill 自己解 ticker 後傳入**；本模組不再用 Haiku normalizer |
| `utils/stt.py` | OpenAI gpt-4o-transcribe（中文同音字辨識優於 whisper-1） |
| `assets/ppt_chrome_template.pptx` | PPT chrome（深藍漸層、底線、logo、頁碼 placeholder）。`build_pptx_cli.py` 自動 inherit |

## 智能複查（migration 的核心勝利點）

舊架構在 `extract_numbers` → `verify` → `generate_report` 跑 3 個獨立 Haiku call、互相不知道對方產出，而且 synthesizer Opus/Sonnet 經常返回壞 JSON 導致整個任務失敗。新架構把所有 LLM-driven step 都讓 Claude 在 skill 流程內執行，每個研究類 skill 都有「自我複查 checklist」一步：

1. 高風險數字（融資 / 估值 / 市值 / 員工數 / HQ）逐條 Tavily 再驗證
2. 中文「億」/「兆」對英文 scale 沒翻錯（億 ≠ billion，差 10 倍）
3. 任務指令的每個 premise / deliverable，evidence 真覆蓋還是沾邊撐？
4. 沒空洞修辭、沒免責聲明、沒提及任務指令

這步在過去等於「寫 prompt 教 Sonnet 自我反省」，效果不穩；現在由 Claude 在 skill 流程中**真的**重跑搜尋，跟剛剛使用者要求對 Taichung / TAIROA 報告做 fact-check 的工作流程一模一樣。

## CLI 入口已廢棄

舊：
- `main.py --audio ... --intern Justin`
- `translate.py "Title" Source date Justin`
- `python3.13 agents/company_info_agent.py --task ...`

**新（在 Claude Code session 內）**：
- 自然語言：「查 Tesla」「翻這篇」「整理會議紀錄」
- 顯式：`/fcc-company-info`、`/fcc-translation`、`/fcc-dictation` 等

舊 CLI 全部刪除。要批次跑類似 `run_tasks.sh` 那種多任務，在 Claude Code 內把任務清單貼上去即可。

## 寫作禁忌（在 `fcc-shared` 內，所有 skill 引用）

### 絕對禁止
- **免責聲明**（僅供參考 / 請以官方為準 / 資料可能有誤）
- **空洞修辭**（成長雙位數 / 戰略佈局 / 行業領先 / 持續優化 / 重要環節 / 賦能 / 深耕 / 打造完整生態）
- **沾邊事實撐 premise**（指令說「政大校長介紹」、evidence 只有「某董事畢業於政大」→ 不能寫成「partial confirmed」）
- **括號標原文**（中文名後不加英文 / 越南文括號，除非 ticker 縮寫第一次出現）
- **提及任務指令**（「您指示」「本任務」等）

### 必須遵守
- 找不到資料明寫「資料不足」
- yfinance 數字附 `as_of` / `period_end` 日期
- 引用同公司多 ticker 時明指哪家（「GME 市值 ...」而非「市值 ...」）

## 中文數字單位（關鍵 trap）

`$9.4 billion` = **94 億美元**（不是 9.4 億）。中文「億」對應 `hundred_million` (1e8)，不對應英文 `billion` (1e9)，差 10 倍。

完整對應表：
| 中文 | 英文 scale | 數值 |
|---|---|---|
| 萬 | ten_thousand | 1e4 |
| 億 | hundred_million | 1e8 |
| 兆 | trillion | 1e12 |

`utils/unit_convert.py` 提供確定性轉換 + 28 個 self-test case（包含 GameStop 9.4 billion 與中文「億」/「兆」/「萬」雙向回歸）。新增 scale / currency 時加 case。

## 時間錨點

研究時務必確認「最新」「最近一季」「去年」「年初至今」這類相對時間參考點。今天的絕對日期可從 Claude Code environment context 拿到，用此計算 t / t-1 / t-2 (年)、最近一季。

舊架構在 `config.time_context()` 注入到每個 prompt；新架構由 Claude 自己讀 environment 的 `currentDate` 處理。

## 輸出 / Subdir 規範

| Skill | subdir | 範例檔名 |
|---|---|---|
| company_info, person_info, dictation, verbal_cleanup | `output/adhoc/` | `2026.05.27_Tesla 調查_Justin.docx` |
| translation | `output/daily/` | `2026.05.27_Title_WSJ_Justin.docx` |
| podcast, speech_ppt | `output/weekly/` | `2026.05.27_K-pop_Justin.docx` / `.pptx` |

`build_docx_cli.py` / `build_pptx_cli.py` 自動把同檔複製到 `~/Downloads/`，除非 `FCC_DISABLE_DOWNLOADS_COPY=1`。

## Reference Files（範本）
路徑：`/Users/junjie/Library/CloudStorage/OneDrive-個人(2)/Internship/Works/`
- company_info：`2026.03.26_Nutrition Startup Huel_Justin.docx`
- person_info：`2026.04.02_林振宏_Justin.docx`
- podcast：`2026.03.25_K-pop_Podcast.docx`
- speech_ppt：`2026.04.09_台中智慧製造演講.pptx`（也是 `assets/ppt_chrome_template.pptx` 的來源）
