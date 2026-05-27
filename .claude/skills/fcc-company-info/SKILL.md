---
name: fcc-company-info
description: 對公司、機構、品牌或產業競品做深度研究，輸出 FCC Partners 格式 .docx。
  觸發時機：使用者要「查/調查/研究 {公司名}」、做 deep-dive、併購對象盡調、
  競品比較、IPO 分析、董事或股東結構研究。流程：拆研究問題 → Tavily 搜尋 →
  yfinance 抓財務（如需） → 寫 draft → **智能複查**（高風險數字逐條 fact-check） →
  build_docx_cli.py 產 docx。先讀 fcc-shared 取得共通規則。
---

# fcc-company-info skill

對公司或機構做深度研究的報告 skill。**寫作禁忌與輸出規範以 `.claude/skills/fcc-shared/SKILL.md` 為準**，本檔只列流程。

---

## Step 1 — 收集輸入

從使用者請求中抽出：
- **研究主題**：公司全名（+ ticker 若有），或機構名
- **intern_name**：預設 `Justin`；多人用 list（明問或從訊息抽）
- **task_date**：預設今天（從 environment 拿）
- **mode**：`short`（預設，兩頁）或 `medium`（深入分析）

模糊處（例：「查 Tesla」沒指明短或長）→ 預設 short，跑下去之前再 confirm。

---

## Step 2 — 拆解研究問題

依任務性質列 3–6 個 todo，覆蓋至少：
- **公司基本資料**：成立年、總部、業務、主要產品
- **財務與股權**：營收、市值、主要股東或母公司
- **產業位置**：競爭對手、市占、差異化
- **近期動態**：最近 12 個月併購、籌資、訴訟、人事
- **任務指令的具體 deliverable**（例：「研究越南廠」→ 廠址、產能、投資額、員工數）

拆 todo 時，**每個具體資訊點獨立一條**（不要「基本資料」這種大類別）。

---

## Step 3 — Tavily 搜尋

對每個 todo 用 WebSearch 或 `tavily-search` skill 找一手來源。每條 query 應該具體：

- ❌ 「Tesla 公司概況」
- ✓ 「Tesla 2025 年營收 季度 SEC 10-Q」
- ✓ 「Tesla Shanghai Gigafactory 員工數 2026」

優先：公司官網、SEC filings、年報、Reuters、Bloomberg、FT、Nikkei、CNA、UDN、CTEE。避免：社群、影音、低品質 SEO 站。

收集 evidence 時保留 URL，後面 reference section 會用。

---

## Step 4 — 財務資料（如需要）

判斷是否需要 yfinance：
- ✓ 需要：股價 / 市值 / PE / EV/EBITDA / 機構持股 / 最新財報數字
- ✗ 不需要：純業務面研究、未上市公司、純規劃建議題

若需要，呼叫：

```bash
python3.13 -c "
import sys, json
import os; sys.path.insert(0, os.environ.get('FCC_MAS_HOME', os.path.expanduser('~/.fcc-mas')))
from utils.financial_tools import fetch_all
print(json.dumps(fetch_all('TSLA', tools=['stock_price','financials','key_metrics','holders','news']), default=str, ensure_ascii=False))
"
```

可一次抓多個 ticker（M&A 雙方、控股結構）。**注意**：
- 上交所 ticker 用 `.SS`（不是 `.SH`），yfinance 才認
- 上櫃用 `.TWO`，上市用 `.TW`
- 引用數字時必附 `as_of` / `period_end` 日期

yfinance 抓不到（私人公司、剛 IPO 等）→ 從 Tavily 找的新聞數字代替，明標來源。

---

## Step 5 — 寫 draft

依 mode 決定深度：
- **short**：1–3 sections，bullets ≤6 條，paragraph ≤150 字
- **medium**：sections 不限，可延伸分析

每個 section 選最合適的 type — bullets / paragraph / table。**讀 fcc-shared 的寫作禁忌再下筆**（空洞修辭、免責聲明、沾邊 premise 都禁止）。

---

## Step 6 — 智能複查（**critical step**，這是 skill 化的核心價值）

寫完 draft 後**逐條過 checklist**，這取代舊架構的 `number_extract` + `premise_validate` + `verify` 三個 Haiku call：

### 6.1 數字 fact-check
列出 draft 中每個「融資金額 / 估值 / 市值 / 員工數 / 營收 / HQ 地點」claim。
對**高風險**項（特別是融資輪次、估值、上市地點）再開一輪 WebSearch / tavily-search 確認。
範例 query：「Figure AI Series B 2024 funding amount」「Anduril 2024 valuation」。
找到正確值就改 draft；找不到就標「資料不足」。

### 6.2 中文單位 sanity check
draft 中每個「X 億」「X 兆」回頭對 evidence 確認：原文是 `million` / `billion` / `trillion` 哪個？
換算對嗎？（例：原 `$9.4B` → 應寫「94 億美元」，不是「9.4 億」）

### 6.3 Premise / Deliverable 覆蓋度
回頭看任務指令的每個前提（premise）和每個 deliverable：
- evidence 真的證實了嗎？沒有 → 明寫「資料不足」
- 用沾邊事實撐起的 → 移除或改寫成「未驗證」

### 6.4 Ticker / 交易所
若提到 ticker，確認交易所後綴正確（`.SS` 上海、`.TW` 台股、`.HK` 港股、純字母 = 美股）。

### 6.5 禁忌詞掃描
draft grep 一遍：「成長雙位數」「戰略佈局」「行業領先」「持續優化」「重要環節」「打造完整生態」「賦能」「深耕」「僅供參考」「請以官方為準」… 任何中一個 → 改寫。

### 6.6 任務指令未現身
report 內文是否不小心提到指令措辭（「您指示」「本任務」「根據任務需求」）→ 改掉。

**任一項 fail 就改完再 ship**。不要把「資料不足」當警語塞最後一段，要寫在對應 section 裡。

---

## Step 7 — 寫 build_docx spec & 產出

組 JSON spec：

```json
{
  "title": "<報告標題>",
  "task_date": "<YYYY-MM-DD>",
  "intern_name": "<intern>",
  "task_name": "<檔名用短名稱，通常 = 公司名或主題>",
  "subdir": "adhoc",
  "sections": [ ... ]
}
```

寫到 `/tmp/<safe_name>_spec.json`，然後：

```bash
python3 "$FCC_MAS_HOME/scripts/build_docx_cli.py" --spec /tmp/<safe_name>_spec.json
```

CLI 印出絕對路徑。告知使用者：
- 主檔位置（`output/adhoc/...docx`）
- `~/Downloads/...docx` 也有一份

**Section 排序建議**（company_info）：
1. 公司基本資料（bullets 或 keyed_paragraph）
2. 財務與股權（table 或 bullets）
3. 產業位置與競爭（paragraph + 可選 table）
4. 近期動態（bullets，附 references）
5. 任務指令的特定 deliverable（依需要）

不一定全有。short mode 取最相關的 1–3 個 section 即可。

---

## 不要做的事

- ❌ 不要硬塞 JSON intermediate 給 Claude 自己解析（舊架構的 synthesizer 失敗模式）
- ❌ 不要呼叫已廢棄的 `agents/company_info_agent.py`、`utils/react_loop.py`、`utils/premise_validate.py` — 這些 module 在 Phase 5 會被砍
- ❌ 不要在 Word 內文塞 [N] citation marker（FCC 規範：references 與內文分離；references 只放 `references` section 或完全省略）
- ❌ 不要叫使用者「請以最新官方資訊為準」這種廢話

---

## 範例觸發

| 使用者輸入 | 行動 |
|---|---|
| 「查 Tesla」 | 觸發本 skill；mode = short，問 intern 名 |
| 「研究 Apple 與 Foxconn 的合作關係」 | 觸發；雙公司，可能要兩個 ticker 的 yfinance |
| 「我要做 NVIDIA 的 deep dive」 | 觸發；mode = medium |
| 「整理一下 Anduril 的最近一輪融資」 | 觸發；單一 deliverable，short |
| 「幫我看一下蔡力行的背景」 | **不**觸發本 skill —— 用 `fcc-person-info` |
