"""
translate.py — 快速入口，body 從 stdin 讀入，或從圖片/PDF OCR。

用法：
    /usr/local/bin/python3.13 translate.py "Title" Source PubDate [Intern]
    /usr/local/bin/python3.13 translate.py "Title" Source PubDate [Intern] --image /path/to/screenshot.png
    /usr/local/bin/python3.13 translate.py "Title" Source PubDate [Intern] --pdf   /path/to/article.pdf

    PubDate = 新聞出版日期 YYYY-MM-DD（出現在 meta 第一行）
    Intern  = 選填，預設用 config 值

範例：
    /usr/local/bin/python3.13 translate.py "Trump's Iran Policy" NYT 2026-04-15 Justin
    然後貼文章，輸入 END + Enter 結束

    /usr/local/bin/python3.13 translate.py "Trump's Iran Policy" NYT 2026-04-15 Justin --image ~/Desktop/article.png
"""
import sys
from pathlib import Path
from datetime import date

sys.path.insert(0, str(Path(__file__).resolve().parent))

from agents.translation_agent import run


def _parse_args():
    """Parse positional + optional --image / --pdf args without argparse."""
    argv = sys.argv[1:]
    image_path = None
    pdf_path = None

    # Strip --image / --pdf flags and their values
    clean = []
    i = 0
    while i < len(argv):
        if argv[i] == "--image" and i + 1 < len(argv):
            image_path = argv[i + 1]; i += 2
        elif argv[i] == "--pdf" and i + 1 < len(argv):
            pdf_path = argv[i + 1]; i += 2
        else:
            clean.append(argv[i]); i += 1

    if len(clean) < 3:
        print('用法: python translate.py "Title" Source PubDate(YYYY-MM-DD) [Intern] [--image PATH | --pdf PATH]')
        sys.exit(1)

    return clean[0], clean[1], clean[2], (clean[3] if len(clean) >= 4 else None), image_path, pdf_path


def main():
    title, source, pub_date, intern, image_path, pdf_path = _parse_args()

    if intern and "," in intern:
        intern = [n.strip() for n in intern.split(",") if n.strip()]

    # ── OCR path ──────────────────────────────────────────────────────────────
    if image_path or pdf_path:
        file_path = image_path or pdf_path
        print(f"OCR 中：{file_path}")
        from utils.ocr import extract_text
        body = extract_text(file_path)
        if not body:
            print("錯誤：OCR 結果為空，請確認圖片內有文字")
            sys.exit(1)
        print(f"  OCR 完成，擷取 {len(body)} 字元")

    # ── stdin path ────────────────────────────────────────────────────────────
    elif sys.stdin.isatty():
        print("━" * 44)
        print(" 貼入文章內文，完成後輸入 END 並按 Enter")
        print("━" * 44)
        lines = []
        while True:
            try:
                line = input("> ")
            except EOFError:
                break
            if line.strip() == "END":
                break
            lines.append(line)
        body = "\n".join(lines).strip()
    else:
        body = sys.stdin.read().strip()

    if not body:
        print("錯誤：body 為空")
        sys.exit(1)

    task_date = date.today().strftime("%Y-%m-%d")
    print(f"翻譯中：{title} [{source}]")
    result = run(
        title=title,
        source=source,
        body_text=body,
        intern_name=intern,
        pub_date=pub_date,
        task_date=task_date,
    )
    print(f"  Output: {result['output_path']}")
    print(f"  Log:    {result['log_path']}")

    from utils.cost_tracker import tracker
    tracker.print_task_summary()


if __name__ == "__main__":
    main()
