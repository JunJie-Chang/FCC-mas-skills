---
name: fcc-dictation
description: 把 CY 的會議錄音或會議口述整理成正式會議紀錄（meeting minutes），
  輸出 FCC Partners 格式 .docx。觸發時機：使用者要「整理會議紀錄」、
  「這次會議的 minutes」、「把這段錄音整理成正式紀錄」、提供 --audio 會議錄音檔。
  抽出 Date/Time、Venue、Attendees、Executive Summary、Discussion Points、Action Items
  六大區塊；標題用斜線日期（2026/05/27）。先讀 fcc-shared 取得共通規則。
---

# fcc-dictation skill

把會議口述整理成正式會議紀錄。**寫作禁忌與輸出規範以 fcc-shared 為準**。

---

## Step 1 — 收集輸入

從使用者請求抽出：
- **raw_text**：會議口述內容，三種來源：
  - 直接貼文字
  - `--audio <path>` 錄音檔 → 呼叫 STT helper（見下）
  - 從現場錄音轉檔
- **intern_name**：預設 `Justin`
- **task_date**：今天
- **override_attendees**（可選）：使用者明確指定的出席者清單，覆寫 LLM 解析結果。格式：
  - 簡單：`"Justin, Neil, CY"` → 統一掛在 `Attendees` 下
  - 分組：`"FCC｜CY, Justin; 客戶｜林總"` → 用全形｜分組
- **override_recorder**（可選）：明確指定記錄者；不指定就用 LLM 解析的或 intern_name

---

## Step 2 — STT（若需要）

若使用者給 `--audio <path>`：

```bash
"${FCC_MAS_PY:-python3}" -c "
import sys
import os; sys.path.insert(0, os.environ.get('FCC_MAS_HOME', os.path.expanduser('~/.fcc-mas')))
from utils.stt import transcribe
print(transcribe('<audio_path>'))
"
```

`utils/stt.py` 用 OpenAI gpt-4o-transcribe（>4 分鐘音檔自動 ffmpeg 切片）。
轉錄完之後**先給使用者看一眼**，若有明顯錯字（特別是公司名、人名），互動式修正後再進 step 3。

---

## Step 3 — 抽出六大區塊

讀完 raw text 後，整理成下列結構：

| 區塊 | 來源 | 對應 build_docx block |
|---|---|---|
| **Title** | LLM 抽 + 加日期前綴 | 構造為 `<YYYY/MM/DD> <會議名>會議紀錄` 放 title |
| **Date & Time** | 從口述中抽 | `keyed_info` |
| **Venue** | 從口述中抽 | `keyed_info` |
| **Attendees** | 從口述抽，或用 override | 多個 `keyed_info`（按組別） |
| **Recorder** | 從口述抽，或用 override，或預設為 intern | `keyed_info` |
| **Meeting Executive Summary** | 2–4 段摘要 | `bracket_heading` + 多個 `paragraph` |
| **Meeting Discussion Points** | 議題分組 | `bracket_heading` + 每組 `topic_heading` + `keyed_paragraph` 點數 |
| **Action Items** | 行動項目分負責方 | `bracket_heading` + 每組 `heading` + `keyed_paragraph` |

**規則**：
- 語言跟口述語言一致：中文口述 → 繁體中文紀錄；英文口述 → 英文紀錄
- 沒提到的欄位（Venue、Date/Time）**留空不要捏造** — 對應 keyed_info 直接省略，不要寫「未提及」這四個字
- Attendees 若資訊不足，至少寫一條 `Attendees: <CY 提到的人名>`
- Executive Summary 是「核心結論」，不是流水帳
- Discussion Points 按議題分（不是按時間軸）；每個議題下用「關鍵詞: 說明」格式
- Action Items 按負責方分組（例：FCC's Action Items / 客戶 Action Items）

---

## Step 4 — 智能複查

### 4.1 出席者沒掛錯人 / 沒漏人
口述中提到的人名都在 Attendees 裡（除非那是引用第三方）。

### 4.2 Action Items 有負責人
每條 action item 都明確說是誰要做。沒有負責人的不要列為 action item，改放 Discussion Points。

### 4.3 沒把 discussion 寫成 action
「會議中討論了 X」≠「某人需要做 X」。Discussion vs Action 要分清楚。

### 4.4 摘要不是流水帳
Executive Summary 應該是「會議達成什麼共識 / 做了什麼決定」，不是「討論了 A、然後討論了 B」。

### 4.5 中英夾雜語言一致
口述若是中英混合，會議紀錄統一以繁體中文為主，英文專有名詞保留即可。

---

## Step 5 — 寫 build_docx spec

Title 跟一般 docx 不同 — **日期內嵌在 title** 用斜線，且**不要走自動 meta line**（用空字串 task_date / intern_name）：

```json
{
  "title": "2026/05/27 Curiosity Lab 會議紀錄",
  "task_date": "2026-05-27",
  "intern_name": "",
  "meta_text": "",
  "task_name": "Curiosity Lab會議紀錄",
  "subdir": "adhoc",
  "sections": [
    {"type": "blank"},
    {"type": "keyed_info", "key": "Date & Time", "text": "Wednesday, May 27, 2026 | 14:00 – 15:30"},
    {"type": "keyed_info", "key": "Venue", "text": "FCC Partners 會議室"},
    {"type": "keyed_info", "key": "FCC", "text": "CY, Justin"},
    {"type": "keyed_info", "key": "Curiosity Lab", "text": "Dr. Chen, Ms. Wang"},
    {"type": "keyed_info", "key": "Recorder", "text": "Justin"},
    {"type": "blank"},

    {"type": "bracket_heading", "text": "Meeting Executive Summary"},
    {"type": "paragraph", "text": "..."},
    {"type": "paragraph", "text": "..."},

    {"type": "bracket_heading", "text": "Meeting Discussion Points"},
    {"type": "topic_heading", "text": "Strategic Positioning"},
    {"type": "keyed_paragraph", "key": "Market focus", "text": "..."},
    {"type": "keyed_paragraph", "key": "Differentiation", "text": "..."},

    {"type": "bracket_heading", "text": "Action Items"},
    {"type": "heading", "text": "FCC's Action Items:"},
    {"type": "keyed_paragraph", "key": "Draft IM", "text": "Justin to deliver by Fri."}
  ]
}
```

關鍵點：
- 用 `"intern_name": ""` 和 `"meta_text": ""` 跳過自動 meta line（會議紀錄日期內嵌在標題裡）
- task_name 不含日期前綴（CLI 會自動加 `YYYY.MM.DD_`）

```bash
"${FCC_MAS_PY:-python3}" "$FCC_MAS_HOME/scripts/build_docx_cli.py" --spec /tmp/<safe_name>_spec.json
```

---

## 範例觸發

| 使用者輸入 | 行動 |
|---|---|
| 「整理一下這場會議：...（貼口述）」 | 觸發 |
| `--audio meeting.m4a` | 觸發；先 STT |
| 「整理會議紀錄，CY 跟 Justin 出席，記錄者 Justin」 | 觸發；override_attendees / override_recorder |
| 「這封口述信幫我整理」 | **不**觸發本 skill —— 用 `fcc-verbal-cleanup` |
| 「把錄音轉成 PPT」 | **不**觸發 —— 用 `fcc-speech-ppt` |
