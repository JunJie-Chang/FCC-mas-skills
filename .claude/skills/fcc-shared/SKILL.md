---
name: fcc-shared
description: FCC Partners 研究報告共通規則 — 寫作禁忌、Word 格式規範、檔名規範、
  中文數字單位規則、時間錨點。Reference 用，不獨立觸發；由其他 fcc-* skill 引用。
---

# FCC Partners 共通規則

本檔由其他 `fcc-*` skill 引用。所有 FCC 報告共通的寫作禁忌、輸出規範、
單位換算規則集中在此。

## 寫作禁忌（所有報告適用）

### 絕對禁止
- **免責聲明**：禁出現「僅供參考」「請以官方為準」「資料可能有誤」「本報告不構成投資建議」等 hedge / disclaimer。
- **空洞修辭**：禁用「成長雙位數」「戰略佈局」「行業領先」「持續優化」「重要環節」
  「深耕」「賦能」「打造完整生態」等沒有具體資訊量的詞。必須給具體**數字 / 名稱 / 日期**。
- **沾邊事實撐 premise**：任務指令的某個前提找不到 evidence 時，必須明寫
  「任務指令所述『X』，本次搜尋資料無法驗證」；**不可**用沾邊 evidence 撐起
  （例：指令「政大校長介紹」，evidence 只有「某董事畢業於政大」→ 此 premise 必須標 unverified）。
- **括號標原文**：不在任何名詞後加括號標注英文 / 越南文 / 其他語言原文（除非 ticker / 縮寫第一次出現）。
- **提及任務指令**：報告內容中不提及任務指令的措辭、比喻或身份設定。

### 必須遵守
- **找不到資料明寫「資料不足」**：deliverable 沒搜到具體數值 / 名稱 / 日期 → 明寫資料不足，不用抽象詞替代。
- **yfinance 數字附日期**：股價附 `as_of`、財報附 `period_end`（例：「2026 Q1（截至 2026-03-31）」）。
- **可引用同公司多 ticker 時明指**：例「GME 市值 103.9 億美元」，不要單寫「市值 103.9 億美元」造成歧義。

## 中文數字單位規則（極關鍵）

中文「億」**不等於** 英文 `billion`，差 10 倍。

| 中文 | 英文 scale | 數值 |
|---|---|---|
| 萬 | ten_thousand | 1e4 |
| 億 | hundred_million | 1e8 |
| 兆 | trillion | 1e12 |
| — | thousand | 1e3 |
| — | million | 1e6 |
| — | billion | 1e9 |

換算：`$9.4 billion = 94 億美元`（不是 9.4 億美元）。`100 億美元 = $10 billion`。
中文「兆」對英文 `trillion`，不是 `quadrillion`。

寫報告時遇到要中文化的英文數字，**先換算到 base unit、再選最大適合的中文單位**。
不要直接「9.4 billion → 9.4 億」這種錯誤直譯。

## 時間錨點

研究時務必確認「最新」「最近一季」「去年」「年初至今」這類相對時間參考點。
今天的絕對日期可以從 environment context 拿到（例：2026-05-27），
用此計算 t / t-1 / t-2 (年)、最近一季 (例：2026 Q1 = 截至 2026-03-31)。

## Word 輸出（build_docx_cli.py spec）

所有報告用 `python3.13 scripts/build_docx_cli.py --spec <path>` 產出 .docx。

### Spec JSON shape

```json
{
  "title":       "報告標題",           // Para[0]，14pt Bold
  "task_date":   "YYYY-MM-DD",         // 預設今天
  "intern_name": "Justin",             // 或 ["Justin", "Neil"]
  "task_name":   "用於檔名的短名稱",   // 例如「Tesla 自動駕駛調查」
  "subdir":      "adhoc" | "daily" | "weekly",
  "sections": [ <block>, <block>, ... ]
}
```

### Block types

| type | 必填欄位 | 用途 |
|---|---|---|
| `heading` | text | 章節標題（14pt Bold） |
| `paragraph` | text；可選 references | 內文段落；可帶 [N] 引用 hyperlink |
| `bullet` | text；可選 references | 項目符號 |
| `blank` | （無） | 空行 |
| `table` | headers[], rows[][] | 表格（Table Grid 樣式，細黑線） |
| `red_heading` | text | 紅字粗體標題（podcast 用） |
| `red_heading_comment` | text, comment | 紅字標題 + Word 註解氣泡 |
| `podcast_title` | title, subtitle | 紅字 underline 主標 + 黑字副標（YYYY.MM.DD_intern_媒體_作者） |
| `bracket_heading` | text | 【標題】粗體（會議紀錄用） |
| `topic_heading` | text | 普通字重子標題 |
| `keyed_paragraph` | key, text | 「Key: text」格式 |
| `keyed_info` | key, text | 同上但無額外間距 |
| `references` | references[] | 「參考來源」section 與編號超連結 |

References format: `[{"num": 1, "title": "媒體名", "url": "https://..."}]`

### Subdir 規範

| Agent type | subdir |
|---|---|
| company_info, person_info, dictation, verbal_cleanup | `adhoc` |
| translation | `daily` |
| podcast, speech_ppt | `weekly` |

### 檔名

由 `build_docx_cli.py` 內部呼叫 `utils.file_naming.general()` 產生：
`YYYY.MM.DD_TaskName_InternName.docx`

多人 intern 用 list：`["Justin", "Neil"]` → `YYYY.MM.DD_TaskName_Justin, Neil.docx`

## Mode（short / medium）

- **short**（預設）：1–3 sections，bullets ≤6 條，paragraph ≤150 字，目標兩頁。
- **medium**：sections 數量不限，可延伸分析。

選 mode 看任務性質：CY 一句話的快速調查走 short；要做 deep dive / 規劃題走 medium。

## Output 路徑

`build_docx_cli.py` 印出絕對路徑（stdout）。同名 .docx 也會被 copy 到 `~/Downloads/`。
告知用戶兩個位置都有檔案。
