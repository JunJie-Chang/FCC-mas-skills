"""
translate.py — 快速入口，body 從 stdin 讀入。

用法：
    /usr/local/bin/python3.13 translate.py "Title" Source PubDate [Intern]

    PubDate = 新聞出版日期 YYYY-MM-DD（出現在 meta 第一行）
    Intern  = 選填，預設用 config 值

範例：
    /usr/local/bin/python3.13 translate.py "Trump's Iran Policy" NYT 2026-04-15 Justin
    然後貼文章，輸入 END + Enter 結束
"""
import sys
from pathlib import Path
from datetime import date

sys.path.insert(0, str(Path(__file__).resolve().parent))

from agents.translation_agent import run

def main():
    args = sys.argv[1:]
    if len(args) < 3:
        print('用法: python translate.py "Title" Source PubDate(YYYY-MM-DD) [Intern]')
        sys.exit(1)

    title    = args[0]
    source   = args[1]
    pub_date = args[2]
    intern   = args[3] if len(args) >= 4 else None

    if sys.stdin.isatty():
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

if __name__ == "__main__":
    main()
