# FCC MAS System — Architecture Spec

## Purpose

為 FCC Partner 實習生日常工作流程建構的 Multi-Agent System。
這份文件是架構方向說明，每個 agent 的詳細實作細節會在個別 session 中提供範本後再定義。

---

## Tech Stack

- **Runtime**: Python 3.11+
- **Orchestration**: LangGraph
- **LLM**: Anthropic Claude (claude-opus-4-5 for complex, claude-haiku-4-5-20251001 for fast tasks)
- **STT**: OpenAI Whisper
- **Web Search**: Tavily API
- **File Output**: python-docx, python-pptx, reportlab
- **Storage**: Local filesystem，模擬 NAS 目錄結構

---

## Directory Structure

```
fcc_mas/
├── main.py
├── config.py
├── router.py
├── agents/
│   ├── company_info_agent.py
│   ├── person_info_agent.py
│   ├── translation_agent.py
│   ├── dictation_agent.py
│   └── podcast_agent.py
├── formatters/
│   ├── word_formatter.py
│   └── pdf_formatter.py
├── delivery/
│   └── email_draft.py
├── utils/
│   ├── file_naming.py
│   ├── stt.py
│   └── search.py
└── output/
    ├── daily/
    ├── weekly/
    └── adhoc/
```

---

## Agent Overview

### company_info_agent / person_info_agent

**核心概念：schema 不 hardcode，由任務指令動態決定。**

任務來源是 CY 的口述（STT 轉錄後輸入），或是直接文字指令。
Agent 的職責是：
1. 解析指令，理解「要查什麼」、「重點在哪裡」、「輸出幾個面向」
2. 用 Tavily 搜尋
3. 讓 Claude 根據指令內容自行判斷 output schema，填入內容
4. 輸出 Word 檔

> 詳細 prompt 設計和 schema 生成邏輯，等提供實際範本後再實作。

---

### translation_agent

**核心概念：輸入文字或檔案，輸出可印出的 PDF。**

- 支援輸入：純文字、.txt、.docx
- 輸出語言預設繁體中文
- 商業語域，保留英文專有名詞
- 輸出 PDF，格式符合辦公室印刷規範（字體、字號）

> 詳細 prompt 和格式規範，等提供範本後再定義。

---

### dictation_agent

**核心概念：錄音檔 → STT → Claude 整理 → Word 輸出。**

支援兩種 task_type：
- `letter`：口述信件，整理成正式商業信件
- `meeting`：會議記錄，整理成結構化會議紀錄

流程：
1. Whisper 轉錄音檔
2. 根據 task_type 用不同 prompt 讓 Claude 整理
3. 輸出 Word 檔

> 詳細 prompt 等提供錄音範例和對應成品後再定義。

---

### podcast_agent

**核心概念：給定問題清單 → 每題搜尋三篇原文 → 彙整成 Word。**

流程：
1. 輸入：N 個問題（文字清單）
2. 對每個問題用 Tavily 搜尋，取前三篇相關文章
3. 用 web fetch 取得每篇完整原文
4. 輸出 Word 檔，格式：
   - 每個問題為一個 section
   - 該 section 下列出三篇文章的標題、來源、日期、完整原文

不做摘要，直接 pull 原文。

> 格式細節等提供範本後確認。

---

### dictation_agent

**核心概念：錄音檔 → STT → Claude 整理 → Word 輸出。**

支援兩種 task_type：
- `letter`：口述信件
- `meeting`：會議記錄

> 詳細 prompt 等提供錄音範例和對應成品後再定義。

---

## Output Formatters

### word_formatter.py

所有 Word 輸出的統一入口。格式規範：
- 字體：微軟正黑體（fallback: Noto Sans CJK TC）
- 最小字體：14pt
- 標題加粗
- 行距：1.15

> 樣式細節等提供 .docx 範本後，用 python-docx 對照實作。

### pdf_formatter.py

翻譯輸出專用。A4，14pt CJK 字體，可直接送印。

---

## File Naming

統一由 `utils/file_naming.py` 處理。

```
一般任務：YYYY.MM.DD_TaskName_v{n}_InternName
演講稿：  {演講日期}演講_{修改日期}_{內容名稱}_v{n}_InternName
```

---

## Email Draft

`delivery/email_draft.py` 根據任務類型產生 email 草稿（主旨、收件人、CC、信件內文）。
CC 規則從 FCC 工作規範提取，不同任務 CC 不同對象。

---

## Router

`router.py` 接收 task dict，分流到對應 agent，回傳輸出檔案路徑。

```python
task = {
  "task_type": "company_info" | "person_info" | "translation" | "letter" | "meeting" | "podcast",
  "input": "...",          # 文字指令、原文、或音檔路徑
  "intern_name": "Justin",
  "priority": "high" | "normal"
}
```

---

## main.py — CLI Entry Point

```bash
python main.py --task company_info --input "調查 Tesla，重點放自動駕駛業務" --intern "Justin"
python main.py --task letter --audio ./recordings/20260407.m4a --intern "Justin"
python main.py --task translate --file ./input/article.txt --intern "Justin"
python main.py --task podcast --questions ./questions.txt --intern "Justin"
```

---

## config.py

```python
ANTHROPIC_API_KEY = ""
TAVILY_API_KEY = ""
OPENAI_API_KEY = ""

LLM_MAIN = "claude-opus-4-5"
LLM_FAST = "claude-haiku-4-5-20251001"

OUTPUT_DIR = "./output"
DEFAULT_INTERN_NAME = "Justin"
```

---

## Build Order

1. `utils/file_naming.py`
2. `utils/search.py`
3. `formatters/word_formatter.py`
4. `agents/company_info_agent.py` — 有實際範本可驗收（Huel 公司調查）
5. `agents/person_info_agent.py`
6. `formatters/pdf_formatter.py`
7. `agents/translation_agent.py`
8. `utils/stt.py` → `agents/dictation_agent.py`
9. `agents/podcast_agent.py`
10. `delivery/email_draft.py`
11. `router.py` + `main.py`

---

## Notes for Claude Code

- 每個 agent 的 prompt 設計和輸出 schema 不在此文件定義，會在個別 session 提供範本後再實作
- 先把骨架、目錄結構、formatter、utils 蓋好，agent 內部邏輯留 stub
- `company_info_agent` 有一份實際輸出範本（Huel 公司調查 Word 檔），是第一個驗收基準
- 遇到格式細節不確定的地方，留 TODO comment，不要自行假設