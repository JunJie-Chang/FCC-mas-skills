"""
utils/planner.py — Shared task planner used by all agents.

Flow:
  raw instruction (text or STT output)
      ↓
  parse_tasks()   ← haiku breaks it into typed, structured task list
      ↓
  confirm()       ← CLI review: confirm / edit / delete each task
      ↓
  confirmed task list → router dispatches to correct agent

Each PlanTask carries an agent_type so the router knows where to send it.
Haiku auto-classifies each task; pass force_type to override (e.g. when
the agent CLI already knows what type it is).

CLI commands during confirm:
  y          — confirm all, start running
  n          — cancel everything
  [number]   — edit that task (label / instruction / agent_type)
  d[number]  — delete that task
  a          — add a new task manually
"""
import json
import os
import re

from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv(override=True)

import config


# ── Agent type registry ───────────────────────────────────────────────────────
# Keep in sync with router.py

AGENT_TYPES = {
    "company_info":    "公司/機構背景調查",
    "person_info":     "人物背景調查",
    "translation":     "文章或文件翻譯",
    "letter":          "口述信件整理（音檔）",
    "meeting":         "會議記錄整理（音檔）",
    "verbal_cleanup":  "口述清稿（去除廢話與開頭語）",
    "podcast":         "Podcast 研究題目搜尋",
    "speech_ppt":      "演講投影片（PPT）製作",
}

# Types excluded from Haiku auto-classification; must be specified via --type.
# These agents receive the raw transcript unchanged — Haiku must not rewrite it.
_MANUAL_ONLY_TYPES = {"verbal_cleanup", "speech_ppt", "podcast"}


# ── Task structure ────────────────────────────────────────────────────────────

class PlanTask:
    """
    A single confirmed task ready to be dispatched to an agent.

    Attributes:
        agent_type:  Which agent handles this task (key in AGENT_TYPES).
        label:       One-line human-readable description shown in CLI.
        instruction: Full instruction string passed to the agent.
    """
    def __init__(self, agent_type: str, label: str, instruction: str):
        self.agent_type  = agent_type
        self.label       = label
        self.instruction = instruction

    def __repr__(self):
        return f"PlanTask(type={self.agent_type!r}, label={self.label!r})"


# ── LLM parsing ───────────────────────────────────────────────────────────────

def parse_tasks(
    raw_instruction: str,
    force_type: str = None,
) -> list[PlanTask]:
    """
    Use haiku to parse a raw instruction into a typed, structured task list.

    Args:
        raw_instruction: Free-text instruction (from user input or STT).
        force_type:      If set, override classification and assign this
                         agent_type to every task (used by individual agent
                         CLIs that already know their type).

    Returns:
        List of PlanTask objects (unconfirmed — pass to confirm() next).
    """
    # ── Bypass Haiku for "raw-copy" types（如 verbal_cleanup） ─────────────
    # _MANUAL_ONLY_TYPES 的語意是「原文照搬進 agent，不給 Haiku 改寫」。
    # 走 planner Haiku 會把 STT 原文濃縮成任務描述，下游 agent 拿到的就不是原文。
    if force_type in _MANUAL_ONLY_TYPES:
        preview = raw_instruction.strip().replace("\n", " ")[:30]
        if len(raw_instruction.strip()) > 30:
            preview += "..."
        return [PlanTask(force_type, f"[{force_type}] {preview}", raw_instruction)]

    client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    auto_types = {k: v for k, v in AGENT_TYPES.items() if k not in _MANUAL_ONLY_TYPES}
    agent_type_list = "\n".join(
        f'  "{k}": {v}' for k, v in auto_types.items()
    )

    force_note = (
        f'\n注意：所有任務的 agent_type 強制設為 "{force_type}"，不需要判斷。'
        if force_type else ""
    )

    prompt = f"""{config.time_context()}

你是任務規劃助理。把以下原始指令拆成一條一條的任務，並為每條任務分配正確的 agent_type。{force_note}

可用的 agent_type：
{agent_type_list}

原始指令：
{raw_instruction}

輸出規則：
- 回傳純 JSON 陣列，不要 markdown 包裝
- 每個元素有三個欄位：
  - "agent_type": 從上方清單選一個最符合的
  - "label": 簡短繁體中文標籤，顯示在 terminal 讓使用者確認
  - "instruction": 完整的執行指令，直接傳給 AI（必須包含所有關鍵識別符，如股票代碼、英文名）
- 若只有一個任務，也回傳長度為 1 的陣列

【合併規則 — 重要】
- 若多個敘述指向同一個研究對象（同一家公司、同一個人、同一個主題），必須合併成「一條任務」，把所有面向都寫進 instruction，不可拆開
- 只有「不同對象」才各自獨立一條
- 判斷標準：名稱相同 = 同對象；即使角度不同（業務/財務/競爭）也要合併
- ✓ 合併範例：「查英維克的業務，再看它的財務，還有競爭對手」→ 一條 company_info
- ✗ 拆開範例（錯誤）：「查英維克業務」+ 「查英維克財務」= 兩條（不可以）
- ✓ 拆開範例（正確）：「查英維克」+「查林志明」= 兩條（不同對象）

範例輸出：
[
  {{
    "agent_type": "company_info",
    "label": "英維克 (002837.SZ) — 業務、財務、競爭",
    "instruction": "調查英維克（Envicool, 深圳上市 002837.SZ），涵蓋業務結構、財務表現與競爭優勢"
  }},
  {{
    "agent_type": "translation",
    "label": "翻譯：Bloomberg 科技文章",
    "instruction": "翻譯附件文章，標題：AI Chip Race，來源：Bloomberg"
  }}
]
"""

    message = client.messages.create(
        model=config.LLM_FAST,
        max_tokens=16384,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = message.content[0].text.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    try:
        data = json.loads(raw.strip())
    except json.JSONDecodeError as e:
        if message.stop_reason == "max_tokens":
            raise RuntimeError(
                f"Planner Haiku 輸出被 max_tokens 截斷（{message.usage.output_tokens} tokens），"
                f"請降低任務數量或進一步提高 max_tokens。原始錯誤：{e}"
            ) from e
        raise

    return [
        PlanTask(
            agent_type  = force_type or t["agent_type"],
            label       = t["label"],
            instruction = t["instruction"],
        )
        for t in data
    ]


# ── CLI confirmation ───────────────────────────────────────────────────────────

_TYPE_WIDTH = max(len(k) for k in AGENT_TYPES) + 2   # for padding


def _print_tasks(tasks: list[PlanTask]) -> None:
    print()
    print("─" * 70)
    print("  預計執行任務：")
    print("─" * 70)
    for i, task in enumerate(tasks, 1):
        type_tag = f"[{task.agent_type}]".ljust(_TYPE_WIDTH + 2)
        print(f"  {i}.  {type_tag}  {task.label}")
        print(f"       ↳ {task.instruction}")
    print("─" * 70)
    print("  y=確認執行  n=取消  [數字]=修改  d[數字]=刪除  a=新增")
    print("─" * 70)


def confirm(tasks: list[PlanTask]) -> list[PlanTask] | None:
    """
    Present the task list in the terminal and wait for the user to
    confirm, edit, or cancel.

    Returns:
        Confirmed list of PlanTask, or None if the user cancelled.
    """
    tasks = list(tasks)

    while True:
        _print_tasks(tasks)
        raw = input("  > ").strip()

        # ── confirm ───────────────────────────────────────────────
        if raw.lower() == "y":
            if not tasks:
                print("  沒有任何任務，已取消。")
                return None
            print()
            return tasks

        # ── cancel ────────────────────────────────────────────────
        elif raw.lower() == "n":
            print("  已取消。")
            return None

        # ── add ───────────────────────────────────────────────────
        elif raw.lower() == "a":
            type_options = " / ".join(AGENT_TYPES.keys())
            agent_type = input(f"  agent_type ({type_options})：").strip()
            if agent_type not in AGENT_TYPES:
                print(f"  無效的 agent_type，略過。")
                continue
            label       = input("  任務標籤：").strip()
            instruction = input("  完整指令：").strip()
            if label and instruction:
                tasks.append(PlanTask(agent_type, label, instruction))
                print(f"  ✓ 已新增：[{agent_type}] {label}")
            else:
                print("  標籤和指令不能為空，略過。")

        # ── delete ────────────────────────────────────────────────
        elif re.fullmatch(r"d\d+", raw.lower()):
            idx = int(raw[1:]) - 1
            if 0 <= idx < len(tasks):
                removed = tasks.pop(idx)
                print(f"  ✓ 已刪除：[{removed.agent_type}] {removed.label}")
            else:
                print(f"  無效編號：{raw[1:]}")

        # ── edit ──────────────────────────────────────────────────
        elif re.fullmatch(r"\d+", raw):
            idx = int(raw) - 1
            if 0 <= idx < len(tasks):
                task = tasks[idx]
                print(f"  修改第 {idx+1} 條：[{task.agent_type}] {task.label}")
                type_options = " / ".join(AGENT_TYPES.keys())
                new_type  = input(f"  agent_type (Enter 保留 '{task.agent_type}')：").strip()
                new_label = input(f"  標籤 (Enter 保留)：").strip()
                new_instr = input(f"  指令 (Enter 保留)：").strip()
                if new_type and new_type in AGENT_TYPES:
                    task.agent_type = new_type
                elif new_type:
                    print(f"  無效的 agent_type，保留原值。")
                if new_label:
                    task.label = new_label
                if new_instr:
                    task.instruction = new_instr
                print(f"  ✓ 已更新。")
            else:
                print(f"  無效編號：{raw}")

        else:
            print("  請輸入 y / n / 數字 / d數字 / a")
