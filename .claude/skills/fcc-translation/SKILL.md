---
name: fcc-translation
description: 將外文文章（英文 / 日文 / 越南文等）翻譯成繁體中文，輸出 FCC Partners 格式 .docx。
  觸發時機：使用者貼一篇文章要翻、附 --image 或 --pdf 截圖要 OCR + 翻、給 URL 要抓內文後翻。
  逐段翻譯，保留段落結構；專有名詞保留原文；人名譯音加括號；不加任何 meta 註解。
  Subdir 為 daily。先讀 fcc-shared 取得共通規則。
---

# fcc-translation skill

逐段翻譯外文文章成繁體中文，輸出 docx。**寫作禁忌與輸出規範以 fcc-shared 為準**。

---

## Step 1 — 收集輸入

從使用者請求抽出：
- **title**：文章原文標題（必須）
- **source**：媒體名稱（例：WSJ、FT、Reuters、Nikkei、CNA）
- **body_text**：文章內文 — 三種來源：
  - 使用者直接貼純文字
  - 圖片 / PDF（iPhone AirDrop 截圖、報紙拍照）→ 用 Read tool 讀圖（Claude 原生支援，不需呼叫 OCR script）
  - URL → 用 tavily-extract 或 WebFetch 抓內文
- **pub_date**：原文發佈日期（YYYY-MM-DD；不確定就略過、用空字串）
- **intern_name**：預設 `Justin`，多人可用 list
- **task_date**：今天

---

## Step 2 — 翻譯（先試加速路徑，失敗才降級）

翻譯有兩條路徑。**先試加速路徑**；只有它回報沒 key（或失敗）才走降級路徑逐段翻。

### 加速路徑（有 ANTHROPIC_API_KEY 時，省 token）

把 body_text 寫到 `/tmp/<safe_name>_body.txt`，呼叫：

```bash
python3 "$FCC_MAS_HOME/scripts/translate_cli.py" \
    --title "<原文 title>" --source "<source>" \
    --body-file /tmp/<safe_name>_body.txt \
    --pub-date "<YYYY-MM-DD 或省略>" --date "<task_date>" --intern "<intern>"
```

腳本會一次 Haiku 呼叫翻完、直接產出 docx。依 exit code 決定：

- **exit 0** → 完成。stdout 就是 .docx 路徑，回報給使用者。**跳過 Step 3、Step 4**（腳本已產檔）。
- **exit 3** → 未設 ANTHROPIC_API_KEY。對使用者明講一句：「未偵測到 ANTHROPIC_API_KEY，改用 session 內翻譯（較耗 token）」，然後走下面的【降級路徑】+ Step 3 + Step 4。
- **其他非 0** → 腳本失敗（例：Haiku 回傳壞 JSON）。提一句腳本失敗，同樣改走【降級路徑】。

> 加速路徑不處理 OCR / URL：圖片、PDF、網址的內文擷取仍由你在 session 內用 Read tool / WebFetch 完成（見下方「圖片 / PDF 處理」），擷取出純文字後再餵給腳本。

### 降級路徑（無 key 或腳本失敗時）

逐段翻譯成繁體中文。規則：

- **保留段落結構**：原文一段、譯文一段，不合併也不拆開
- **語氣自然**：符合繁體中文書面語習慣，不要逐字直譯
- **專有名詞處理**：
  - 公司 / 機構名：保留英文（例：Tesla、Apple、Nikkei），不加括號中譯
  - 人名第一次出現：譯音 +（原文），如「川普（Trump）」「黃仁勳（Jensen Huang）」；後續只用譯名
  - 地名：用通用中譯（紐約 / 倫敦 / 矽谷），不熟的小地名保留原文
  - 技術名詞 / 產品名：保留原文（例：iPhone、ChatGPT、Cursor、AGI）
- **數字單位**：照 fcc-shared 規則 — `$9.4 billion` → 「94 億美元」，不是「9.4 億」
- **不加 meta 註解**：不寫「譯註」、不在內文加任何「（譯者註）」之類的東西
- **保留原文資訊量**：不省略段落，不總結，不重排

例外：
- 原文括號內的英文公司名 → 保留括號裡的英文（例：「Apple (AAPL)」→「Apple（AAPL）」）
- 原文已有的譯名（例：「華為（Huawei）」）→ 沿用

---

## Step 3 — 智能複查（降級路徑才需要）

> 走加速路徑（translate_cli.py exit 0）時跳過本步——Haiku prompt 內已含自檢。

寫完逐段翻譯後逐條過：

### 3.1 段落一一對應
原文 N 段 → 譯文 N 段。少一段就漏譯了；多一段就拆過頭。

### 3.2 數字 sanity check
每個原文數字（金額、百分比、年份、人數）→ 譯文有對應且**單位正確**。
特別注意 `billion ↔ 億` 的 10 倍 trap。

### 3.3 人名第一次出現有附原文
中文化人名第一次出現要有 `譯名（原文）`，後續可省略。

### 3.4 沒翻錯關鍵字
專有名詞看起來像翻錯（例：把 `Apple Watch` 翻成「蘋果手錶」）→ 改回原文。

### 3.5 沒加 meta 註解
譯文裡不應該出現「譯者註」「以下省略」「以下為翻譯」這種字眼。

---

## Step 4 — 寫 build_docx spec（降級路徑才需要）

Translation 的 meta_text 是**兩行**特殊格式：

```
<pub_date>_<source>
<task_date>_<intern_name>
```

例：
```
2026-05-15_FT
2026-05-27_Justin
```

組 JSON spec：

```json
{
  "title": "<原文 title>",
  "meta_text": "<pub_date>_<source>\n<task_date>_<intern>",
  "intern_name": "<intern>",
  "task_date": "<YYYY-MM-DD>",
  "task_name": "<title>_<source>",
  "subdir": "daily",
  "sections": [
    {"type": "blank"},
    {"type": "paragraph", "text": "<第一段譯文>"},
    {"type": "paragraph", "text": "<第二段譯文>"},
    ...
  ]
}
```

**重要**：
- 用 `meta_text` 欄位提供雙行 header（不是 task_date / intern_name 自動生成的單行）
- 第一個 section 用 `blank` 隔開 header 跟內文
- 每段譯文一個 `paragraph` block；不要把多段塞同一個 block 用 `\n\n` 連接

寫到 `/tmp/<safe_name>_spec.json`，然後：

```bash
python3 "$FCC_MAS_HOME/scripts/build_docx_cli.py" --spec /tmp/<safe_name>_spec.json
```

---

## 圖片 / PDF 處理

使用者附圖（`--image foo.jpg`）或 PDF（`--pdf foo.pdf`）時：

- **圖片**：直接用 Read tool 讀，Claude 多模態原生看圖 → 抽文字 → 翻譯
- **PDF**：用 Read tool 讀（內建支援 PDF），或 `pdftotext` 預處理後再翻

---

## 範例觸發

| 使用者輸入 | 行動 |
|---|---|
| 「翻這篇文章：...（貼英文）」+ 提供 title / source / date | 觸發 |
| `python3.13 translate.py "Title" Source 2026-04-15 Justin` | 舊 CLI 路徑，遷移期可以對應到此 skill |
| 「這張截圖幫我翻」+ AirDrop 圖片 | 觸發；用 Read 讀圖 |
| 「這個 URL 的文章翻一下：https://...」 | 觸發；先 tavily-extract / WebFetch 拿內文 |
| 「整理一下這篇文章重點」 | **不**觸發本 skill —— 走 verbal_cleanup 或 dictation |
