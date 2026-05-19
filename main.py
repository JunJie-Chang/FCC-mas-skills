"""
main.py — CLI entry point for FCC MAS.

Usage examples:
  # Text input, agent auto-classified
  python main.py --input "查英維克（002837.SZ）業務結構，另外翻譯附件 article.txt" --intern "Justin"

  # Audio input (STT → planner → confirm → agents)
  python main.py --audio ./recordings/20260407.m4a --intern "Justin"

  # Force a specific agent type (skips auto-classification)
  python main.py --input "調查林志明，大倡國際" --type person_info --intern "Justin"

  # Specify output subfolder
  python main.py --input "..." --intern "Justin" --subdir daily
"""
import argparse
import sys
from datetime import date
from pathlib import Path

import config
from router import dispatch
from utils.planner import AGENT_TYPES, confirm, parse_tasks


def main():
    parser = argparse.ArgumentParser(
        description="FCC MAS — Multi-Agent System CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # ── Input ──────────────────────────────────────────────────────
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument(
        "--input", "-i",
        metavar="TEXT",
        help="Task instruction as text",
    )
    input_group.add_argument(
        "--audio", "-a",
        metavar="PATH",
        help="Audio file path; will be transcribed via Whisper before planning",
    )

    # ── Options ────────────────────────────────────────────────────
    parser.add_argument(
        "--type", "-t",
        choices=list(AGENT_TYPES.keys()),
        default=None,
        help="Force a specific agent type (skips auto-classification)",
    )
    parser.add_argument(
        "--intern",
        default=config.DEFAULT_INTERN_NAME,
        help=f"Intern name(s), comma-separated (default: {config.DEFAULT_INTERN_NAME})",
    )
    parser.add_argument(
        "--date",
        default=None,
        help="Task date YYYY-MM-DD (default: today)",
    )
    parser.add_argument(
        "--subdir",
        choices=["daily", "weekly", "adhoc"],
        default=None,
        help="Output subfolder under output/ (default: per-agent — translation→daily, podcast/speech_ppt→weekly, others→adhoc)",
    )
    parser.add_argument(
        "--mode", "-m",
        choices=["short", "medium"],
        default="short",
        help="Report mode: short=嚴格回覆需求約兩頁 | medium=完整延伸報告 (default: short)",
    )
    parser.add_argument(
        "--yes", "-y",
        action="store_true",
        help="Auto-confirm task list without interactive prompt",
    )

    args = parser.parse_args()

    # ── Intern name ────────────────────────────────────────────────
    intern = (
        [n.strip() for n in args.intern.split(",")]
        if "," in args.intern
        else args.intern
    )
    task_date = args.date or date.today().strftime("%Y-%m-%d")

    # ── Step 1: get raw instruction ────────────────────────────────
    if args.audio:
        audio_path = Path(args.audio)
        if not audio_path.exists():
            print(f"找不到音檔：{audio_path}")
            sys.exit(1)
        print(f"正在轉錄音檔：{audio_path.name} ...")
        from utils.stt import transcribe
        raw_instruction = transcribe(audio_path)
        print(f"\n── 轉錄結果 ──\n{raw_instruction}\n")

        # ── Step 1b: STT subject review (audio path only, skipped by --yes) ──
        # Surface proper-noun mentions so user can fix STT mishears BEFORE
        # parse_tasks. Cheaper and more accurate than trying to recover
        # from "資深客" / "工業負面" downstream.
        if not args.yes:
            from utils.subject_review import extract_subject_mentions, review_subjects
            print("正在偵測主體名稱...")
            mentions = extract_subject_mentions(raw_instruction)
            raw_instruction = review_subjects(raw_instruction, mentions)
    else:
        raw_instruction = args.input

    # ── Step 2: parse into task list ──────────────────────────────
    print("正在解析任務...")
    tasks = parse_tasks(raw_instruction, force_type=args.type)

    # ── Step 3: user confirms ─────────────────────────────────────
    if args.yes:
        from utils.planner import _print_tasks
        _print_tasks(tasks)
        print("  [--yes] 自動確認執行\n")
        confirmed = tasks
    else:
        confirmed = confirm(tasks)
    if not confirmed:
        sys.exit(0)

    # ── Step 4: dispatch each confirmed task ──────────────────────
    results = []
    for task in confirmed:
        print(f"\n▶  [{task.agent_type}] {task.label}")
        try:
            result = dispatch(
                task        = task,
                intern_name = intern,
                task_date   = task_date,
                subdir      = args.subdir,
                mode        = args.mode,
            )
            print(f"   Output : {result['output_path']}")
            print(f"   Log    : {result.get('log_path', '—')}")
            from utils.cost_tracker import tracker
            tracker.print_task_summary()
            results.append({"task": task, "result": result, "error": None})
        except NotImplementedError as e:
            print(f"   ⚠  尚未實作：{e}")
            results.append({"task": task, "result": None, "error": str(e)})
        except Exception as e:
            print(f"   ✗  執行失敗：{e}")
            from utils.cost_tracker import tracker
            tracker.print_task_summary()
            results.append({"task": task, "result": None, "error": str(e)})

    # ── Summary ───────────────────────────────────────────────────
    done  = [r for r in results if r["result"]]
    failed = [r for r in results if r["error"]]
    print(f"\n完成 {len(done)}/{len(results)} 個任務。", end="")
    if failed:
        print(f" （{len(failed)} 個失敗）")
    else:
        print()

    from utils.cost_tracker import tracker
    tracker.print_summary()


if __name__ == "__main__":
    main()
