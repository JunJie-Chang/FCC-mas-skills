---
name: fcc-verbal-cleanup
description: 把 CY 的口述錄音清稿成乾淨的繁體中文書面稿，輸出 FCC Partners 格式 .docx。
  觸發時機：使用者明確要「清稿」「把這段錄音整理成書面稿」「去掉廢話」、
  「整理這段口述」（非會議用途）、「整理這封信」。
  與 dictation 的差別：dictation 抽出會議結構（出席者 / 行動項目）；
  verbal_cleanup 只清理廢話 + 整理段落，保留原意原內容。先讀 fcc-shared。
---

# fcc-verbal-cleanup skill

口述清稿，去廢話、保原意。**寫作禁忌與輸出規範以 fcc-shared 為準**。

---

## Step 1 — 收集輸入

- **raw_text**：口述內容（直接貼或從 `--audio` 來）
- **intern_name**：預設 `Justin`
- **task_date**：今天

若 `--audio <path>`：

```bash
python3.13 -c "
import sys
import os; sys.path.insert(0, os.environ.get('FCC_MAS_HOME', os.path.expanduser('~/.fcc-mas')))
from utils.stt import transcribe
print(transcribe('<audio_path>'))
"
```

---

## Step 2 — 清稿規則

### 必刪
- **開頭語**：「嗯好那個」「哈囉大家好」「好那個今天想說的是」「OK 那」「嗯哼」
- **語氣助詞**：「那個」「就是說」「嗯」「啊」「對」「對不對」「啦」「呢」
- **英文 filler**：「like」「you know」「I mean」「basically」「actually」「sort of」
- **重複話**：「我覺得我覺得」→「我覺得」；「然後然後然後」→「然後」
- **轉述廢話**：「我跟你講啦」「我跟你說喔」這種 phatic

### 必保
- **核心內容、資訊、語氣**：清稿不是改寫，原意 / 資訊量 / 語氣**完全保留**
- **說話者的觀點與判斷**：CY 說「我覺得這家公司很有問題」→ 譯文保留「我覺得這家公司很有問題」（不要改成「該公司有疑慮」這種第三人稱）
- **數字、人名、公司名、時間**：原樣保留

### 不准做的
- ❌ 不加 meta 註解（「以下為整理稿」「清稿完成」）
- ❌ 不在名詞後加括號標原文
- ❌ 不總結內容（這是 cleanup 不是 summarize）
- ❌ 不加沒有的觀點

### 語言
- 中文口述 → 繁體中文
- 英文口述 → 英文
- 中英混合 → 繁體中文為主，英文專有名詞保留

---

## Step 3 — 分段

讀完內容後判斷是否分段：

- **有明顯主題切換**（CY 從聊 A 公司轉到聊 B 公司）→ 加 `heading` 把每段命名
- **單一連續內容**（CY 講完整一個觀察 / 一封信草稿）→ 不加 heading，整篇就是一個 section 內的多個 paragraph

每個 paragraph 是完整一段，不要在一個字串內塞「\n\n」分隔（用多個 paragraph block）。

---

## Step 4 — 智能複查

### 4.1 沒漏資訊
原稿中的每個事實、數字、人名、判斷 → 清稿後都還在。

### 4.2 沒加觀點
清稿沒有加入原稿沒有的判斷或修飾詞（特別注意「優秀」「卓越」「重要」這種評價詞）。

### 4.3 廢話清乾淨
回頭看每段，前面有沒有殘留的「那個」「就是」「嗯」。

### 4.4 語氣自然
口語邏輯（先說 X 再說 Y 然後又繞回 X）→ 整理成更直線的書面語。

---

## Step 5 — 寫 build_docx spec

```json
{
  "title": "<主題簡短標籤，10 字以內，例：「Tesla 投資觀察」>",
  "task_date": "<YYYY-MM-DD>",
  "intern_name": "<intern>",
  "task_name": "<同 title>",
  "subdir": "adhoc",
  "sections": [
    {"type": "heading", "text": "<可選的小節標題>"},
    {"type": "paragraph", "text": "<清稿後第一段>"},
    {"type": "paragraph", "text": "<第二段>"},
    {"type": "heading", "text": "<下一小節（若有）>"},
    {"type": "paragraph", "text": "..."}
  ]
}
```

連續內容版：

```json
{
  "title": "<主題>",
  ...
  "sections": [
    {"type": "paragraph", "text": "<段一>"},
    {"type": "paragraph", "text": "<段二>"},
    {"type": "paragraph", "text": "<段三>"}
  ]
}
```

```bash
python3 "$FCC_MAS_HOME/scripts/build_docx_cli.py" --spec /tmp/<safe_name>_spec.json
```

---

## 範例觸發

| 使用者輸入 | 行動 |
|---|---|
| 「幫我清這段口述」+ 文字 / 錄音 | 觸發 |
| 「把這段廢話清掉」 | 觸發 |
| 「我口述一封信，幫我整理乾淨」 | 觸發；title 取信件主題 |
| 「整理會議紀錄」 | **不**觸發 —— 用 `fcc-dictation`（有結構） |
| 「翻成英文 / 中文」 | **不**觸發 —— 用 `fcc-translation` |
| 「總結一下重點」 | **不**觸發 —— verbal_cleanup 不做摘要 |
