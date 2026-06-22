---
name: fcc-person-info
description: 對個人（高管、董事、創辦人、政商人物）做背景調查，輸出 FCC Partners 格式 .docx。
  觸發時機：使用者要「查/調查/研究 {人名}」、「了解一下 XX 的背景」、
  「XX 的學經歷」、董事會結構研究的某個董事 deep-dive。流程：拆問題 →
  Tavily 搜尋 → 寫 draft → **智能複查** → build_docx_cli.py 產 docx。
  不抓 yfinance（無上市公司股票數據）；其餘流程與 fcc-company-info 相同。
  先讀 fcc-shared 取得共通規則。
---

# fcc-person-info skill

對特定人物做背景調查的報告 skill。**寫作禁忌與輸出規範以
`.claude/skills/fcc-shared/SKILL.md` 為準**，本檔只列流程差異。

---

## Step 1 — 收集輸入

從使用者請求抽出：
- **人名**：全名（中文 + 英文如知道）
- **公司 / 機構 context**：哪家公司的誰（同名很多，CY 通常會講 context）
- **intern_name**：預設 `Justin`
- **task_date**：預設今天
- **mode**：`short`（預設）或 `medium`

---

## Step 2 — 拆解研究問題

依任務性質列 3–6 個 todo，覆蓋：
- **基本資料**：出生 / 年齡（如公開）、籍貫、現職位
- **學歷**：學校、科系、畢業年（避免猜年份；資料不確定就略過）
- **職涯軌跡**：每一段公司 + 職位 + 任期
- **代表事蹟 / 經營績效**（如商業界人士）
- **董事 / 顧問 / 政府職務**（兼任的）
- **媒體形象、爭議事件**（如有）
- **任務指令的具體 deliverable**（例：「他與 XX 的關係」「他在 XX 案中的角色」）

每個資訊點獨立 todo（不要「個人背景」這種大類別）。

---

## Step 3 — Tavily 搜尋

對每個 todo 用具體 query：

- ❌ 「蔡力行 介紹」
- ✓ 「蔡力行 聯發科 副董事長 任期」
- ✓ "Wei-Jen Lo MediaTek Vice Chairman appointed year"
- ✓ 「蔡力行 台積電 升任 執行長」

**中英雙語搜尋很重要**：台灣高管常有英文名，英文 source（Reuters / FT / Nikkei / SCMP）有時資訊更完整。

優先來源：公司官網 IR 頁、上市公司年報（找董事介紹）、Linkedin（小心 paywall）、Reuters / Bloomberg、CNA / 工商時報 / 經濟日報。

**注意**：同名同姓很常見，每個資訊點都要對得上 context（例如：哪個「林志明」？是上市公司董事還是教授？）。

---

## Step 4 — 寫 draft

依 mode 深度。**短人物背景的常用 section 結構**：

1. **個人基本資料**（keyed_paragraph 或 keyed_info）— 現職、年齡、籍貫
2. **學歷**（bullets）— 一行一段學經歷
3. **職涯軌跡**（table 或 bullets）— 公司 / 職位 / 任期
4. **代表事蹟**（bullets 或 paragraph）
5. **任務指令的特定問題**（依需要）

人物資料常找不到「明確數字」，避免硬填日期或年齡（年齡很容易錯一兩歲）。

---

## Step 5 — 智能複查（**critical step**）

逐條過 checklist：

### 5.1 身分辨識 sanity check
最重要的一條 —— 確定報告寫的是**對的那個人**。
- Cross-check 至少 2 個資訊點對齊（例：學校 + 公司、或公司 + 任期）
- 若 evidence 提到的人和搜尋目標的 context 對不上 → 該段直接刪除或標 unverified
- 同名人物的 evidence 不要混在一起

### 5.2 日期 fact-check
每個「任期」「畢業年」「出生年」對 evidence 再確認一次。
不確定的 → 改為「2010 年代初」這類模糊但**正確**的範圍，或直接省略。

### 5.3 學歷 fact-check
學歷是 CY 很在意的項目，但也最容易錯（碩士在哪、博士在哪）。
**僅在 evidence 明確提到**才寫上去，沒明說的不要從「他常在 OO 演講」推論他是 OO 校友。

### 5.4 Premise / Deliverable 覆蓋度
任務指令的每個前提逐條：找不到 evidence → 明寫「資料不足」，不沾邊撐起。
（典型踩雷：CY 說「他是 XX 校長介紹來的」，evidence 沒有 → 寫「任務指令所述『XX 校長介紹』，本次搜尋資料無法驗證」）

### 5.5 禁忌詞掃描
參照 fcc-shared 的禁忌詞清單。人物報告特別要避免：
- 「業界翹楚」「行業領袖」「德高望重」這類沒資訊量的形容
- 「人緣甚佳」「政商關係深厚」這類無法驗證的描述

### 5.6 任務指令未現身
不要在報告中提到「您詢問」「本任務」等措辭。

---

## Step 6 — 寫 build_docx spec & 產出

```json
{
  "title": "<人名>",
  "task_date": "<YYYY-MM-DD>",
  "intern_name": "<intern>",
  "task_name": "<人名>",
  "subdir": "adhoc",
  "sections": [ ... ]
}
```

寫到 `/tmp/<safe_name>_spec.json`，然後：

```bash
"${FCC_MAS_PY:-python3}" "$FCC_MAS_HOME/scripts/build_docx_cli.py" --spec /tmp/<safe_name>_spec.json
```

告知使用者輸出路徑（`output/adhoc/` 與 `~/Downloads/`）。

---

## 範例觸發

| 使用者輸入 | 行動 |
|---|---|
| 「查蔡力行」 | 觸發；context = 聯發科 / 台積電（從 CY 上下文判斷） |
| 「林志明的背景」 | 觸發；必先 disambiguate 是哪個林志明 |
| 「整理一下 NVIDIA Jensen Huang 的學經歷」 | 觸發；mode = short |
| 「TSMC 董事會結構」 | **不**觸發本 skill —— 用 `fcc-company-info` 做整體；單一董事 deep-dive 才用本 skill |
| 「查 Tesla 公司」 | **不**觸發本 skill —— 用 `fcc-company-info` |
