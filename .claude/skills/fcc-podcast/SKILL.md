---
name: fcc-podcast
description: 為 Podcast 研究蒐集相關新聞文章並翻譯成繁體中文，輸出 FCC Partners 格式 .docx。
  觸發時機：使用者明確要做「Podcast 研究」、「整理 podcast 相關資料」、
  「給我 K-pop 產業相關的最近新聞並翻譯」、有 topic + questions 清單的研究任務。
  流程：解析 topic + questions → 每題搜尋 → 全文抓取（trafilatura / tavily-extract）→
  逐篇翻譯 → 寫成多文章合輯 docx。Subdir 為 weekly。先讀 fcc-shared。
---

# fcc-podcast skill

Podcast 研究：對每個問題搜文章、抓全文、翻成中文，整本合輯輸出。
**寫作禁忌與輸出規範以 fcc-shared 為準**。

---

## Step 1 — 收集輸入

從使用者請求抽出：
- **topic**：Podcast 研究主題（一句話，例：「K-pop 產業國際化」「全球媒體產業 AI 應用」）
- **questions**：問題清單（3–8 條），例：
  - 「韓國娛樂公司近年海外擴張策略？」
  - 「BTS 解約事件對 HYBE 股價影響？」
  - 「歐美音樂市場對 K-pop 接受度？」
- **intern_name**：預設 `Justin`
- **task_date**：今天

若使用者只給原文指令（沒拆 topic/questions），先用 Claude 自己解析後**回頭跟使用者確認**這個拆解再往下跑。

---

## Step 2 — 每問題一條 query

對每個 question 生成一條搜尋 query。規則：

- 優先繁體中文：可加「繁體」「台灣」或關鍵詞中文化
- 查詢具體：包含主題關鍵詞 + 問題核心
- 一題一條，不要為單題開多條（除非真的搜不到）

範例：
| Question | Query |
|---|---|
| BTS 解約對 HYBE 股價影響？ | `HYBE 股價 BTS 解約 2024` |
| K-pop 對歐美市場滲透率？ | `K-pop 美國市場 銷售 占比` |

---

## Step 3 — 搜尋 + 全文抓取

對每條 query 用 **tavily-search** 或 WebSearch，取前 3–5 個結果。然後逐 URL 抓全文。

### Domain 過濾規則（**重要**）

**完全禁用的 domain**（社群 / 影音）— 即使搜到也直接跳過：
```
facebook.com, x.com (twitter), instagram.com, tiktok.com,
reddit.com, pinterest.com, tumblr.com, weibo.com,
mp.weixin.qq.com, threads.net, snapchat.com,
youtube.com, youtu.be, linkedin.com
```

**新聞白名單**（接收且標 `verified`）—
- 台灣主流：cna / ctee / udn / ltn / chinatimes / ettoday / bnext / 商周 / 財訊 / 天下 / 遠見 / 風傳媒 / moneydj / 鏡週刊
- 台灣產業：digitimes / ithome / techorange / inside / 36kr
- 國際中文：BBC / 紐時中文 / 華爾街日報中文 / RFA / VOA / DW / 財新 / 21 經濟 / 第一財經
- 國際英文：reuters / bloomberg / ft / nytimes / wsj / economist / nikkei / techcrunch / theverge / scmp / 明報 / hk01

**白名單外**：接收但在報告或 .log 加註標記，供使用者校稿時注意。

### 全文抓取三層 cascade

對通過 domain 過濾的 URL：
1. 首選 trafilatura（純文字、無 boilerplate） — 透過 `tavily-extract` skill 或 `"${FCC_MAS_PY:-python3}" -c "import trafilatura; ..."` 跑
2. 失敗 → tavily-extract markdown 模式
3. 失敗 → 用搜尋結果的 snippet

去除 navigation / 廣告（每個 source 可能不同 boilerplate）。文章 < 50 字 → skip（snippet stub）。

---

## Step 4 — 逐篇翻譯成繁體中文

每篇文章用 fcc-translation skill 的規則翻：
- 保留段落結構
- 專有名詞保留原文，人名譯音 +（原文）
- 數字換算注意 `billion ↔ 億` 的 10 倍 trap
- 不加 meta 註解

文章原文若已是繁體中文 → 不需翻譯，直接用原文。
簡體中文 → 轉繁體（保留專有名詞如「人工智慧」改「人工智慧」，「软件」改「軟體」等台灣用語）。

---

## Step 5 — 寫 build_docx spec

Podcast 報告的結構是「題目分組 + 每題下面多篇文章」。

```json
{
  "title": "Podcast 研究：<topic>",
  "task_date": "<YYYY-MM-DD>",
  "intern_name": "<intern>",
  "task_name": "<topic 簡短版>_Podcast",
  "subdir": "weekly",
  "sections": [
    {"type": "heading", "text": "問題 1：BTS 解約對 HYBE 股價影響"},
    {"type": "blank"},
    {"type": "podcast_title", "title": "HYBE 股價單日大跌 14%，BTS 解約傳聞發酵", "subtitle": "2024.09.15_Justin_中央社_張記者"},
    {"type": "paragraph", "text": "<翻譯第一段>"},
    {"type": "paragraph", "text": "<翻譯第二段>"},
    {"type": "blank"},
    {"type": "podcast_title", "title": "Bloomberg 分析師：BTS 不是 HYBE 唯一", "subtitle": "2024.09.18_Justin_Bloomberg_J. Smith"},
    {"type": "paragraph", "text": "<翻譯第一段>"},
    {"type": "blank"},

    {"type": "heading", "text": "問題 2：K-pop 美國市場滲透率"},
    {"type": "blank"},
    {"type": "podcast_title", "title": "<下一篇標題>", "subtitle": "<日期_intern_媒體_作者>"},
    ...
  ]
}
```

`podcast_title` 的 subtitle 格式（嚴格）：
```
YYYY.MM.DD_<intern>_<媒體簡稱>_<作者（如有）>
```
缺欄位用空字串接續省略（例：作者不明：`2024.09.18_Justin_Bloomberg`）。

```bash
"${FCC_MAS_PY:-python3}" "$FCC_MAS_HOME/scripts/build_docx_cli.py" --spec /tmp/<safe_name>_spec.json
```

---

## Step 6 — 智能複查

### 6.1 每題都有文章
每個 question 下方至少 1 篇文章；如果搜不到 → 在該問題 heading 下加一個 paragraph 寫「資料不足，本次搜尋未找到對應主題之白名單新聞來源」。

### 6.2 沒重複 URL
同一篇文章不要在兩個問題下都出現。一篇文章只出現一次，放在最相關的問題下。

### 6.3 Subtitle 格式齊整
每篇文章的副標都符合 `YYYY.MM.DD_intern_媒體_作者` 格式。媒體用簡稱（中央社、商周、Bloomberg、Reuters），不要寫全名。

### 6.4 翻譯品質
每篇文章的翻譯獨立檢查（單位、人名、段落數）— 套 fcc-translation 的複查 checklist。

### 6.5 白名單外標記
若有非白名單來源被收進來，在 .log 或文末 notes 標記，提醒使用者校對。

---

## 範例觸發

| 使用者輸入 | 行動 |
|---|---|
| 「整理 K-pop 產業 Podcast 研究：(1)... (2)... (3)...」 | 觸發；topic + questions 已給 |
| `--type podcast --topic "K-pop" --questions "q1; q2"` | 舊 CLI 路徑對應到此 skill |
| 「給我這幾個問題對應的最近新聞 + 翻譯」 | 觸發 |
| 「研究 Tesla」 | **不**觸發 —— 用 `fcc-company-info`（單一公司 deep dive） |
| 「翻譯這篇文章」 | **不**觸發 —— 用 `fcc-translation`（單篇） |
