#!/usr/bin/env bash
#
# install.sh — FCC-mas skill set installer (Mac / Linux / WSL2)
#
# One-liner install:
#   curl -fsSL https://raw.githubusercontent.com/JunJie-Chang/FCC-mas-skills/main/install.sh | bash
#
# What this does:
#   1. Checks for required tools (git, python3 ≥ 3.10, ffmpeg, claude)
#   2. Clones the repo to ~/.fcc-mas/ (or git pull if already exists)
#   3. Installs Python dependencies into the user's site-packages
#   4. Symlinks .claude/skills/fcc-* into ~/.claude/skills/ (user-global)
#   5. Prompts for OPENAI_API_KEY and writes ~/.fcc-mas/.env
#   6. Sets FCC_MAS_HOME in your shell rc (~/.zshrc / ~/.bashrc)
#   7. Runs a smoke test (builds a sample .docx)
#
# Re-running is safe — script is idempotent (git pull instead of clone, etc.)

set -euo pipefail

REPO_URL="https://github.com/JunJie-Chang/FCC-mas-skills.git"
INSTALL_DIR="$HOME/.fcc-mas"
SKILLS_DST="$HOME/.claude/skills"

# Colors
if [[ -t 1 ]]; then
  RED=$'\033[31m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'; BLUE=$'\033[34m'; BOLD=$'\033[1m'; NC=$'\033[0m'
else
  RED=""; GREEN=""; YELLOW=""; BLUE=""; BOLD=""; NC=""
fi

say()    { printf "%s==>%s %s\n" "$BLUE" "$NC" "$1"; }
ok()     { printf "%s ✓%s  %s\n" "$GREEN" "$NC" "$1"; }
warn()   { printf "%s ⚠%s  %s\n" "$YELLOW" "$NC" "$1"; }
fail()   { printf "%s ✗%s  %s\n" "$RED" "$NC" "$1" >&2; exit 1; }
header() {
  printf "\n%s%s━━━ %s ━━━%s\n\n" "$BOLD" "$BLUE" "$1" "$NC"
}

# ── 0. Detect OS / shell rc ─────────────────────────────────────────────────

case "$(uname -s)" in
  Darwin) OS="mac" ;;
  Linux)  OS="linux" ;;
  *)      fail "Unsupported OS: $(uname -s). Use Mac / Linux / WSL2." ;;
esac

case "${SHELL:-}" in
  */zsh)  SHELL_RC="$HOME/.zshrc";  SHELL_NAME="zsh"  ;;
  */bash) SHELL_RC="$HOME/.bashrc"; SHELL_NAME="bash" ;;
  *)      SHELL_RC="$HOME/.profile"; SHELL_NAME="sh"  ;;
esac

header "FCC-mas skill set installer"
echo "OS:          $OS"
echo "Shell RC:    $SHELL_RC ($SHELL_NAME)"
echo "Install to:  $INSTALL_DIR"
echo ""

# ── 1. Check required tools ─────────────────────────────────────────────────

header "1. Checking required tools"

# git
if ! command -v git >/dev/null 2>&1; then
  fail "git not found. Install: $([[ $OS == mac ]] && echo 'brew install git' || echo 'apt install git')"
fi
ok "git: $(git --version | awk '{print $3}')"

# python3 (≥ 3.10; project tested on 3.13)
PY_BIN=""
for cand in python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$cand" >/dev/null 2>&1; then
    ver=$("$cand" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "")
    if [[ -n "$ver" ]]; then
      maj=$(echo "$ver" | cut -d. -f1)
      min=$(echo "$ver" | cut -d. -f2)
      if [[ "$maj" -ge 3 && "$min" -ge 10 ]]; then
        PY_BIN="$cand"
        PY_VER="$ver"
        break
      fi
    fi
  fi
done
if [[ -z "$PY_BIN" ]]; then
  if [[ $OS == mac ]]; then
    fail "Python 3.10+ not found. Install: brew install python@3.13"
  else
    fail "Python 3.10+ not found. Install: apt install python3.13"
  fi
fi
ok "python: $PY_BIN ($PY_VER)"

# ffmpeg (optional but recommended for STT > 4 min audio)
if command -v ffmpeg >/dev/null 2>&1; then
  ok "ffmpeg: $(ffmpeg -version 2>/dev/null | head -1 | awk '{print $3}')"
else
  warn "ffmpeg not found — needed for STT on audio > 4 min. Install: $([[ $OS == mac ]] && echo 'brew install ffmpeg' || echo 'apt install ffmpeg')"
fi

# claude (Claude Code)
if command -v claude >/dev/null 2>&1; then
  ok "claude (Claude Code) detected"
else
  warn "Claude Code CLI not found. Install at https://docs.anthropic.com/claude-code"
  warn "Skills will be installed but you need Claude Code to use them."
fi

# ── 2. Clone / pull repo ────────────────────────────────────────────────────

header "2. Fetching repo"

if [[ -d "$INSTALL_DIR/.git" ]]; then
  say "Repo exists at $INSTALL_DIR — running git pull"
  (cd "$INSTALL_DIR" && git pull --ff-only)
  ok "Updated to latest"
elif [[ -d "$INSTALL_DIR" ]]; then
  fail "$INSTALL_DIR exists but is not a git checkout. Move/delete it and re-run."
else
  say "Cloning into $INSTALL_DIR"
  git clone --depth 1 "$REPO_URL" "$INSTALL_DIR"
  ok "Cloned"
fi

# ── 3. Install Python dependencies (into a dedicated venv) ──────────────────

header "3. Installing Python dependencies"

# Why a venv instead of `pip install --user`:
#   • Debian/Ubuntu/WSL system pythons are PEP 668 "externally-managed" — a
#     plain --user install errors out (or needs --break-system-packages).
#   • One transitive dep (odfpy, via financedatabase → pandas[excel]) ships no
#     wheel and must build from sdist. Under the Debian-patched system
#     setuptools that build dies with `AttributeError: install_layout`. A clean
#     venv with up-to-date pip/setuptools/wheel builds it without a hitch.
#   • Keeps the user's global/site packages (e.g. pandas) untouched.
# The skill CLIs auto-re-exec under this venv (see utils/venv_bootstrap.py), so
# nothing needs to be "activated" at runtime.

VENV_DIR="$INSTALL_DIR/.venv"
VENV_PY="$VENV_DIR/bin/python"

if [[ ! -x "$VENV_PY" ]]; then
  say "Creating virtualenv at $VENV_DIR"
  if ! "$PY_BIN" -m venv "$VENV_DIR" 2>/tmp/fcc-mas-pip.log; then
    cat /tmp/fcc-mas-pip.log
    fail "Could not create venv. Install the venv module: $([[ $OS == mac ]] && echo 'brew install python' || echo 'sudo apt install python3-venv')"
  fi
  ok "venv created"
else
  ok "venv already exists at $VENV_DIR"
fi

say "Upgrading pip / setuptools / wheel in venv"
if ! "$VENV_PY" -m pip install --quiet --upgrade pip setuptools wheel >/tmp/fcc-mas-pip.log 2>&1; then
  cat /tmp/fcc-mas-pip.log
  fail "Failed to bootstrap pip/setuptools/wheel — see log above"
fi

say "Installing requirements (this can take a few minutes)"
if "$VENV_PY" -m pip install --upgrade -r "$INSTALL_DIR/requirements.txt" >>/tmp/fcc-mas-pip.log 2>&1; then
  ok "Dependencies installed into $VENV_DIR (log: /tmp/fcc-mas-pip.log)"
else
  cat /tmp/fcc-mas-pip.log
  fail "pip install failed — see log above"
fi

# ── 4. Symlink skills into ~/.claude/skills/ ────────────────────────────────

header "4. Registering skills"

mkdir -p "$SKILLS_DST"
for skill_dir in "$INSTALL_DIR"/.claude/skills/fcc-*; do
  name=$(basename "$skill_dir")
  link="$SKILLS_DST/$name"
  if [[ -L "$link" ]] && [[ "$(readlink "$link")" == "$skill_dir" ]]; then
    ok "$name (already linked)"
  elif [[ -e "$link" ]]; then
    warn "$name exists at $link but is not the expected symlink — skipping. Remove it manually to re-link."
  else
    ln -s "$skill_dir" "$link"
    ok "$name → $link"
  fi
done

# ── 5. Prompt for OpenAI key ────────────────────────────────────────────────

header "5. Configuring OpenAI API key"

ENV_FILE="$INSTALL_DIR/.env"
# Match a real key (sk- followed by ≥10 key chars), NOT the .env.example
# placeholder "sk-..." — otherwise a skipped install leaves a placeholder
# that this check mistakes for a configured key and never re-prompts.
if [[ -f "$ENV_FILE" ]] && grep -qE "^OPENAI_API_KEY=sk-[A-Za-z0-9_-]{10,}" "$ENV_FILE" 2>/dev/null; then
  ok ".env already configured (existing OPENAI_API_KEY kept)"
else
  echo "Need an OpenAI key for:"
  echo "  • STT in fcc-dictation / fcc-verbal-cleanup / fcc-speech-ppt"
  echo "  • DALL-E in fcc-speech-ppt"
  echo "  Get one at: https://platform.openai.com/api-keys"
  echo ""
  echo "Press Enter to skip (you can edit $ENV_FILE later)."
  printf "%sOpenAI API key:%s " "$BOLD" "$NC"
  read -r OPENAI_KEY
  if [[ -n "$OPENAI_KEY" ]]; then
    {
      echo "# Written by install.sh on $(date)"
      echo "OPENAI_API_KEY=$OPENAI_KEY"
    } > "$ENV_FILE"
    chmod 600 "$ENV_FILE"
    ok ".env written ($(wc -c < "$ENV_FILE") bytes, mode 600)"
  else
    cp "$INSTALL_DIR/.env.example" "$ENV_FILE"
    chmod 600 "$ENV_FILE"
    warn "Skipped — .env copied from .env.example. STT/DALL-E will fail until you set OPENAI_API_KEY."
  fi
fi

# ── 6. Add FCC_MAS_HOME / FCC_MAS_PY to shell rc ────────────────────────────

header "6. Setting FCC_MAS_HOME / FCC_MAS_PY in shell"

# FCC_MAS_HOME — repo root.  FCC_MAS_PY — the venv interpreter the skills run
# their CLIs with (docs use "${FCC_MAS_PY:-python3}"; the CLIs also self-heal
# via utils/venv_bootstrap, but the inline financial-data call in
# fcc-company-info needs FCC_MAS_PY to hit the venv directly).
EXPORT_HOME="export FCC_MAS_HOME=\"\$HOME/.fcc-mas\"   # FCC-mas skills"
EXPORT_PY="export FCC_MAS_PY=\"\$HOME/.fcc-mas/.venv/bin/python\"   # FCC-mas venv python"

if grep -Fq "FCC_MAS_HOME" "$SHELL_RC" 2>/dev/null; then
  ok "FCC_MAS_HOME already in $SHELL_RC"
else
  {
    echo ""
    echo "# Added by FCC-mas install.sh on $(date '+%Y-%m-%d')"
    echo "$EXPORT_HOME"
  } >> "$SHELL_RC"
  ok "Added FCC_MAS_HOME to $SHELL_RC"
fi

if grep -Fq "FCC_MAS_PY" "$SHELL_RC" 2>/dev/null; then
  ok "FCC_MAS_PY already in $SHELL_RC"
else
  echo "$EXPORT_PY" >> "$SHELL_RC"
  ok "Added FCC_MAS_PY to $SHELL_RC"
fi

# Export now for the smoke test
export FCC_MAS_HOME="$INSTALL_DIR"
export FCC_MAS_PY="$VENV_PY"

# ── 7. Smoke test ───────────────────────────────────────────────────────────

header "7. Smoke test"

TEST_SPEC=$(mktemp -t fcc-mas-smoketest-XXXXXX.json)
cat > "$TEST_SPEC" <<'JSON'
{
  "title": "FCC-mas 安裝驗證",
  "task_date": "2026-05-27",
  "intern_name": "Installer",
  "task_name": "install_smoke_test",
  "subdir": "adhoc",
  "sections": [
    {"type": "heading", "text": "✓ 安裝完成"},
    {"type": "paragraph", "text": "如果你能讀到這份 Word 檔，代表 fcc-mas skill set 已正確安裝。"},
    {"type": "bullet", "text": "Python 環境正確"},
    {"type": "bullet", "text": "python-docx / file_naming / WordBuilder 都能 import"},
    {"type": "bullet", "text": "格式（微軟正黑體、頁眉、頁碼、邊框）渲染正常"}
  ]
}
JSON

if OUTPUT=$("$VENV_PY" "$INSTALL_DIR/scripts/build_docx_cli.py" --spec "$TEST_SPEC" 2>&1); then
  rm -f "$TEST_SPEC"
  ok "Built test doc: $OUTPUT"
else
  rm -f "$TEST_SPEC"
  echo "$OUTPUT" >&2
  fail "Smoke test failed — see error above"
fi

# ── Done ────────────────────────────────────────────────────────────────────

header "Done"

cat <<EOF
${GREEN}${BOLD}✓ FCC-mas skill set 安裝完成${NC}

Installed location:  ${BOLD}$INSTALL_DIR${NC}
Skills registered:   ${BOLD}$SKILLS_DST/fcc-*${NC}
Env variable:        ${BOLD}FCC_MAS_HOME=$INSTALL_DIR${NC}  (added to $SHELL_RC)

${BOLD}下一步${NC}：

  1. 重啟 terminal（讓 FCC_MAS_HOME 生效）  或  ${BOLD}source $SHELL_RC${NC}
  2. 開新的 Claude Code session：${BOLD}claude${NC}
  3. 試試以下 trigger：

     ${BLUE}「查 Tesla」${NC}                  → fcc-company-info
     ${BLUE}「翻這篇文章：...」${NC}            → fcc-translation
     ${BLUE}「整理會議紀錄」${NC}                → fcc-dictation
     ${BLUE}「幫我清這段口述」${NC}              → fcc-verbal-cleanup
     ${BLUE}「研究 K-pop 產業 podcast」${NC}    → fcc-podcast
     ${BLUE}「把這段演講做成 PPT」${NC}          → fcc-speech-ppt

${BOLD}更新${NC}：未來重跑這個 installer 即可（git pull + 重新 pip install）：

  curl -fsSL https://raw.githubusercontent.com/JunJie-Chang/FCC-mas-skills/main/install.sh | bash

${BOLD}問題回報${NC}：找 Justin 或開 issue 在 https://github.com/JunJie-Chang/FCC-mas-skills/issues
EOF
