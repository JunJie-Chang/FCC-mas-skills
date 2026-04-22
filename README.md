# FCC-mas

FCC Partners 實習生日常工作流程的 Multi-Agent System。

口述指令 → 語音轉文字 → 自動分類 → 執行 → Word 輸出

---

## 開始使用前

你需要準備以下三組 API Key，向 Justin 索取：

- `ANTHROPIC_API_KEY`
- `TAVILY_API_KEY`
- `OPENAI_API_KEY`

---

## 安裝步驟

**1. Clone 專案**

```bash
git clone https://github.com/JunJie-Chang/FCC-mas.git
cd FCC-mas
```

**2. 安裝套件**

```bash
pip3.13 install -r requirements.txt
```

**3. 建立 `.env` 檔案**

在專案根目錄新增一個 `.env` 檔，內容如下（填入你拿到的 key）：

```
ANTHROPIC_API_KEY=your_key
TAVILY_API_KEY=your_key
OPENAI_API_KEY=your_key
```

---

## 使用方式

所有指令都在專案資料夾內執行，`--intern` 填你自己的名字。

```bash
# 語音輸入（錄音檔）
python3.13 main.py --audio '/path/to/recording.m4a' --intern "你的名字"

# 文字輸入
python3.13 main.py --input "查 Tesla" --intern "你的名字"

# 翻譯（執行後貼上文章，輸入 END + Enter 結束）
python3.13 translate.py "Article Title" SourceName 2026-04-15 你的名字
```

輸出的 Word 檔會存在 `output/` 資料夾，並自動複製到 `~/Downloads`。

---

## 支援的任務類型

| 類型 | 說明 |
|---|---|
| `company_info` | 公司 / 機構研究 |
| `person_info` | 人物背景調查 |
| `translation` | 文章翻譯 |
| `letter` / `meeting` | 口述整理（信件 / 會議記錄） |
| `podcast` | Podcast 主題研究 |
| `speech_ppt` | 簡報研究 |

任務類型通常由系統自動判斷，不需要手動指定。

---

## 有問題找 Justin
