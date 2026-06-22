# FCC-mas Skills

> FCC Partners 實習工作流程的 Claude Code skill set —— 公司研究、人物背景、翻譯、會議紀錄、口述清稿、Podcast 蒐集、演講 PPT，共 7 個 skill。輸出統一的 FCC Word / PPT 格式。

---

## 一行安裝

**Mac / Linux / WSL2**：

```bash
curl -fsSL https://raw.githubusercontent.com/JunJie-Chang/FCC-mas-skills/main/install.sh | bash
```

**Windows**：請先裝 [WSL2](https://learn.microsoft.com/zh-tw/windows/wsl/install)，在 WSL2 終端機中跑上面那行。

install 完之後重啟 terminal、開 Claude Code，就能用了。

---

## 你會得到什麼

7 個自動觸發的 Claude Code skill：

| 你打的話 | 自動觸發的 skill | 輸出 |
|---|---|---|
| 「查 Tesla」「研究 NVIDIA」 | `fcc-company-info` | 公司研究 .docx |
| 「查蔡力行」「Jensen Huang 的背景」 | `fcc-person-info` | 人物背景 .docx |
| 「翻這篇文章...」「這張截圖幫我翻」 | `fcc-translation` | 翻譯 .docx |
| 「整理會議紀錄」「會議 minutes」 | `fcc-dictation` | 會議紀錄 .docx |
| 「幫我清這段口述」「去掉廢話」 | `fcc-verbal-cleanup` | 清稿 .docx |
| 「整理 K-pop podcast 研究」 | `fcc-podcast` | 多文章合輯 .docx |
| 「把這段演講做成 PPT」 | `fcc-speech-ppt` | 演講 .pptx（含 DALL-E 圖） |

所有產出檔案會放在：
- `~/.fcc-mas/output/<adhoc|daily|weekly>/`
- 同時 copy 一份到 `~/Downloads/`

檔名規範：`YYYY.MM.DD_主題_實習生名.docx`

---

## 安裝前提

`install.sh` 會自動檢查與提示，你不需要事先準備。但若想了解：

| 工具 | 必要性 | 用途 | 沒裝怎辦 |
|---|---|---|---|
| Python 3.10+（建議 3.13） | **必要** | Word / PPT 生成 | Mac：`brew install python@3.13`；Linux：`apt install python3.13` |
| Git | **必要** | 拉 repo | Mac 內建；Linux：`apt install git` |
| ffmpeg | 建議 | STT 音檔切片（>4 分鐘音檔） | Mac：`brew install ffmpeg`；Linux：`apt install ffmpeg` |
| [Claude Code](https://docs.anthropic.com/claude-code) | **必要** | 跑 skills | 跟官網裝 |
| OpenAI API key | 部分功能用 | STT + DALL-E | 申請 [platform.openai.com](https://platform.openai.com/api-keys)，install 時會問你 |
| Anthropic API key | **選填** | 只用於 `fcc-translation` 翻譯加速 | 申請 [console.anthropic.com](https://console.anthropic.com/settings/keys)，自己編 `.env` |

**`ANTHROPIC_API_KEY` 只用於翻譯**：填了，`fcc-translation` 走獨立 Haiku 呼叫，速度快、token 成本低；**留空（或不設）則自動改用 Claude Code session 內翻譯，結果相同但很吃 token**。其餘 6 個 skill 都不需要這把 key —— 它們本來就在 Claude Code session 內跑，不另外叫 API。

---

## 安裝完做什麼

開 Claude Code（在任何資料夾都行）：

```bash
claude
```

然後直接打你想做的事：

```
> 查 Tesla
```

或顯式指定 skill：

```
> /fcc-company-info
```

Claude 會問你需要的細節（intern 名、研究深度等），然後跑流程：搜尋 → 抓財務 → 寫 draft → **智能複查**（高風險數字逐條 fact-check） → 產出 .docx。

---

## 範例：跑一個 company_info

```
你: 查 Anduril 最近一輪融資

Claude: 我要跑 fcc-company-info 對 Anduril 做研究。
        intern 名是？預設 Justin。

你: Justin

Claude: 開始拆解 todo：
        1. Anduril 基本資料
        2. 最近一輪融資金額、估值、領投人
        3. 既有業務與產品線
        ...
        [跑 Tavily 搜尋]
        [自我複查：對「Series F 15 億美元」再開一輪驗證]
        [產出 .docx]
        
        ✓ 完成：~/Downloads/2026.05.27_Anduril 融資調查_Justin.docx
```

---

## 更新

直接重跑 installer 就好：

```bash
curl -fsSL https://raw.githubusercontent.com/JunJie-Chang/FCC-mas-skills/main/install.sh | bash
```

會 `git pull` + 重新 `pip install`，不會覆寫你的 `.env`。

---

## 解除安裝

```bash
# 1. 刪 repo
rm -rf ~/.fcc-mas

# 2. 移除 skills symlink
rm ~/.claude/skills/fcc-{shared,company-info,person-info,translation,dictation,verbal-cleanup,podcast,speech-ppt}

# 3. 從 shell rc 刪掉 FCC_MAS_HOME / FCC_MAS_PY 兩行
# 編輯 ~/.zshrc 或 ~/.bashrc，刪掉 'export FCC_MAS_HOME=...' 與 'export FCC_MAS_PY=...'
```

---

## Troubleshooting

### 「`python3` not found」或版本太低
`install.sh` 會檢查。Mac 用 `brew install python@3.13`，Linux 用 distro 的 package manager。

### 安裝完 Claude Code 沒看到 skills
Skills 在新 session 啟動時掃描 `~/.claude/skills/`。**重啟 Claude Code** 後就會看到。

### 「ModuleNotFoundError: No module named 'docx'」
依賴裝在 `~/.fcc-mas/.venv` 這個 venv 裡。看 `/tmp/fcc-mas-pip.log`。常見原因：
- **`python3-venv` 沒裝**（Debian/Ubuntu/WSL）→ `sudo apt install python3-venv` 再重跑 installer。
- Python 版本 < 3.10。
- 在 Claude session 內手動抓財務資料時報這個錯 → 多半是 shell 還沒 source、`FCC_MAS_PY` 沒生效，導致 fallback 到系統 `python3`（沒這些套件）。`source ~/.zshrc`（或重啟 terminal）即可。

> 註：以前版本用 `pip install --user`，在 Debian/WSL 上會踩 PEP 668（externally-managed）和 odfpy build 失敗（`install_layout`）。改用 venv 後這些都不會再發生。

### STT 或 DALL-E 沒反應
缺 `OPENAI_API_KEY`。編輯 `~/.fcc-mas/.env` 加上 key（格式參考 `.env.example`）。

### 跑某個 skill 報 `FCC_MAS_HOME: unbound variable`
shell rc 還沒 source。`source ~/.zshrc`（或重啟 terminal）。

### 輸出 .docx 在 Windows 上開沒有字
微軟正黑體在 Windows 內建，Mac/Linux 可能 fallback 到「Noto Sans CJK TC」。若 PPT/DOCX 開起來空白，可能是字體 fallback 失敗 —— 在你的系統裝「Noto Sans CJK」即可。

---

## 系統架構

每個 skill 是一個 markdown 檔，放在 `~/.fcc-mas/.claude/skills/fcc-*/SKILL.md`。Claude 讀指示後執行：

```
你輸入「查 Tesla」
    ↓
Claude Code 比對 description 自動觸發 fcc-company-info
    ↓
Claude 照 SKILL.md 步驟跑：
    ├─ WebSearch / tavily-search 找一手資料
    ├─ Bash 呼叫 $FCC_MAS_PY $FCC_MAS_HOME/utils/financial_tools.py（yfinance）
    ├─ 自我複查（高風險數字 fact-check）
    └─ Bash 呼叫 $FCC_MAS_PY $FCC_MAS_HOME/scripts/build_docx_cli.py（產 .docx）
```

所有 LLM 呼叫都是 Claude Code session 自己的 Claude（無外部 Anthropic API call），可即時自我複查。Python helpers 只做確定性工作（檔案 I/O、HTTP 抓資料、Word / PPT 渲染）。

詳細架構演進記錄見 [CLAUDE.md](./CLAUDE.md)。

---

## 反饋與問題

- 開 issue：https://github.com/JunJie-Chang/FCC-mas-skills/issues
- 或找 Justin
