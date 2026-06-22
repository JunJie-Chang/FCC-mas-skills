---
name: fcc-speech-ppt
description: 從 CY 的演講口述稿生成 FCC Partners 格式 .pptx（深藍漸層、標題 + 5 bullets + 右側 DALL-E 圖片）。
  觸發時機：使用者明確要「做演講 PPT」、「把這段演講轉成投影片」、提供 --audio 演講錄音、
  CY 給了一份逐頁口述稿。流程：（音檔 →）STT → Claude 解析為 slides_plan
  → 與 user 確認（**確認後才燒 DALL-E**）→ build_pptx_cli.py 產 .pptx +
  非結構化頁 echo notes 給操作者。subdir 為 weekly。先讀 fcc-shared 取得共通規則。
---

# fcc-speech-ppt skill

從口述生成 PPT。**寫作禁忌與輸出規範以 fcc-shared 為準**。

關鍵：**DALL-E 是燒錢操作，必須在 user 確認 slides_plan 後才執行**。

---

## Step 1 — 收集輸入

- **raw_transcript**：CY 的逐頁口述（直接貼 / `--audio <path>` STT 取得）
- **speech_topic**（可選）：演講題目；若 CY 沒明說，Claude 從 transcript 推斷
- **intern_name**：預設 `Justin`
- **task_date**：今天
- **generate_images**：預設 `true`（會跑 DALL-E）；若 user 說「不要圖」/「先看 layout」/「省錢測試」就改 `false`

### STT（若需要）

```bash
"${FCC_MAS_PY:-python3}" -c "
import sys
import os; sys.path.insert(0, os.environ.get('FCC_MAS_HOME', os.path.expanduser('~/.fcc-mas')))
from utils.stt import transcribe
print(transcribe('<audio_path>'))
"
```

轉錄完之後**先給 user 看一眼**，有錯字（特別是公司名、技術詞、人名）互動式修正後再 step 2。

---

## Step 2 — 解析 transcript 為 slides_plan

讀 transcript，**逐頁切**。CY 通常會說「第一頁」「下一頁」「然後接下來」這類分隔詞。

每一頁分類成兩種 type：

### structured（自動排版）
適用：CY 明確列出 bullets，或內容是條列式（≤ 5 條）。

```json
{
  "type": "structured",
  "title": "<頁面標題，10–18 字>",
  "bullets": ["bullet 1", "bullet 2", "...up to 5"]
}
```

### unstructured（操作者手動處理）
適用：CY 描述複雜版面（流程圖、組織架構、表格、地圖、產業生態示意圖）。
此頁**不自動生成 PPT slide**，notes 會 echo 給操作者。

```json
{
  "type": "unstructured",
  "title": "<頁面標題>",
  "notes": "<CY 描述的版面內容，原文照搬即可>"
}
```

### 分類規則
- ≤ 5 個簡單條列點 → structured
- 提到「示意圖」「流程圖」「組織圖」「對比表」「地圖」→ unstructured
- 兩種都沾邊（半結構化）→ 給 unstructured，讓操作者自己決定
- bullets 內容超過 5 條 → 拆成兩頁 structured；不要硬塞 6+ bullets

### Title 規則
- 簡潔、10–18 字
- 不要用「關於」「之介紹」「簡介」這種贅詞
- ❌「關於智慧製造的定義之說明」→ ✓「智慧製造的定義」

### Bullets 規則
- 每條 ≤ 30 字（PPT 不該擠滿字）
- **書面語**：CY 口述是「我覺得啊那個製造業現在最大的問題是」→ 改成「製造業當前最大瓶頸：人力短缺」
- 不要直接 paste 口述句子；提煉重點
- 不要在 bullet 末尾加標點

---

## Step 3 — 與 user 確認 slides_plan（**critical — DALL-E 前的關卡**）

把 slides_plan 印出來給 user 看，**每一頁**列：
- 頁碼 + type
- title
- bullets（如有）/ notes（如有）

範例展示：
```
─── slides_plan (2026/05/27, Justin) ───────────────────
[1] structured  「智慧製造的定義」
    • 智慧製造的核心是資料驅動
    • 結合 AI、IoT 與自動化技術
    • 從生產線到供應鏈整合
    • 可量化的 KPI 是落地關鍵
    • 台灣中小企業是主戰場

[2] unstructured  「競爭格局示意圖」
    notes: 中央放台灣產業聚落，左右分上下游...

[3] structured  「政策建議」
    • 設立中部 AI 製造研究中心
    • 提供研發投資抵減 30%
    • 建構共享測試場域
─────────────────────────────────────────────────────
共 3 頁（structured 2 / unstructured 1）。
將為 2 張 structured 頁面生成 DALL-E 圖片（約 $0.04 × 2 = $0.08）。
確認執行？輸入 'y' 繼續；輸入修改指示或 'n' 取消。
```

互動處理：
- `y` / `yes` / `好` / `確認` → 進 step 4
- `n` / `no` / `取消` → END，不執行 DALL-E
- 任何其他內容 → 視為修改指示，調整 slides_plan 後再次確認

---

## Step 4 — 寫 spec & 呼叫 build_pptx_cli

```json
{
  "speech_topic": "<topic>",
  "task_date": "<YYYY-MM-DD>",
  "intern_name": "<intern>",
  "subdir": "weekly",
  "generate_images": true,
  "slides": [ <slide>, <slide>, ... ]
}
```

寫到 `/tmp/<safe_name>_pptx_spec.json`，然後：

```bash
"${FCC_MAS_PY:-python3}" "$FCC_MAS_HOME/scripts/build_pptx_cli.py" --spec /tmp/<safe_name>_pptx_spec.json
```

CLI 回傳 JSON：
```json
{
  "output_path": "...pptx",
  "unstructured_notes": [{"title": "...", "notes": "..."}]
}
```

---

## Step 5 — 把 unstructured notes 回給 user

`build_pptx_cli.py` 只生 structured 頁。unstructured 頁要用人工處理 — 從 CLI 輸出的 `unstructured_notes` 印出來：

```
──── 非結構化頁面 Notes（需操作者手動處理）────
[第 3 頁]「競爭格局示意圖」
中央放台灣產業聚落，左右分上下游：上游零組件、下游系統整合。
請操作者手動畫示意圖。
─────────────────────────────────────────────
```

告訴 user：
- PPT 主檔位置（`output/weekly/` + `~/Downloads/`）
- structured 頁面已自動排版完成
- unstructured 頁的位置（page X）與描述，需手動補上

---

## 智能複查（在 step 3 之前自我檢查）

在把 slides_plan 給 user 看之前，先過 checklist：

### 6.1 頁數合理
演講通常 8–15 頁。> 20 頁可能是切太細；< 5 頁可能漏 transcript 某段。

### 6.2 每頁 title 對應內容
title 不能跟 bullets 講不一樣的事情。

### 6.3 bullets 是書面語
不要殘留「啊」「那個」「我覺得」「OK」這類口語助詞。

### 6.4 結構化 vs 非結構化分類正確
「示意圖」「組織架構」「流程圖」「對比表」這類必須是 unstructured。

### 6.5 title 沒贅詞
沒有「關於」「之介紹」「簡介」這種廢話。

### 6.6 標題與內容語言一致
中文演講 → 全中文 PPT；英文演講 → 全英文。混合演講 → 看 CY 主導語言。

---

## 不要做的事

- ❌ 不要繞過 step 3 直接燒 DALL-E（每張 $0.04，意外重跑 10 頁 = $0.40）
- ❌ 不要塞 6+ bullets 到一頁
- ❌ 不要在 bullets 裡放完整句子（PPT 應該是 talking points，不是逐字稿）
- ❌ 不要呼叫 `agents/speech_ppt_agent.py`（Phase 5 將被刪除；統一用 `scripts/build_pptx_cli.py`）

---

## 範例觸發

| 使用者輸入 | 行動 |
|---|---|
| 「把這段演講做成 PPT：…（貼 transcript）」 | 觸發 |
| `--audio speech.m4a --type speech_ppt` | 舊 CLI 路徑對應到此 skill |
| 「我想做 8 頁的演講投影片，主題是台中智慧製造」 | 觸發；問 user 要不要提供 transcript 還是現場口述 |
| 「不要圖，純文字 PPT」 | 觸發；`generate_images=false` |
| 「整理會議紀錄」 | **不**觸發 —— 用 `fcc-dictation` |
| 「整理口述稿成書面」 | **不**觸發 —— 用 `fcc-verbal-cleanup` |
