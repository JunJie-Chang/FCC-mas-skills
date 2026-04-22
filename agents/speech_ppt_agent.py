"""
agents/speech_ppt_agent.py — Speech PPT generator using LangGraph.

Flow:
    generate_content → generate_images → build_ppt

Input:  speech topic / title (string, or list of slide titles)
Output: .pptx file — one slide per topic, each with:
    - Title at top (28pt)
    - 5 bullet points on left, each ≤10 Chinese chars (24pt bold)
    - AI-generated image on right (DALL-E 3)

Reference layout: Works/2026.04.09_台中智慧製造演講.pptx
  Slide size:   10.0 × 7.5 inches
  Title:        pos=(0.51, 0.40) size=(8.98, 0.93) 28pt
  Bullet area:  pos=(0.51, 1.49) size=(4.7, 4.31)  24pt bold
  Image:        pos=(5.45, 1.49) size=(4.2, 4.31)

Filename: YYYY.MM.DD_SpeechTopic_InternName.pptx
"""
import io
import json
import os
import sys
import tempfile
from datetime import date
from pathlib import Path
from typing import TypedDict, Union

from anthropic import Anthropic
from dotenv import load_dotenv
from langgraph.graph import END, StateGraph

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config
from utils.file_naming import general
from utils.logger import AgentLogger

load_dotenv(override=True)


# ── Layout constants (inches → EMU: 1in = 914400) ────────────────────────────

_IN = 914400  # EMU per inch

SLIDE_W  = int(10.0 * _IN)
SLIDE_H  = int(7.5  * _IN)

TITLE_L  = int(0.51 * _IN)
TITLE_T  = int(0.40 * _IN)
TITLE_W  = int(8.98 * _IN)
TITLE_H  = int(0.93 * _IN)
TITLE_PT = 28

BULLET_L = int(0.51 * _IN)
BULLET_T = int(1.49 * _IN)
BULLET_W = int(4.70 * _IN)
BULLET_H = int(4.31 * _IN)
BULLET_PT = 24

IMAGE_L  = int(5.45 * _IN)
IMAGE_T  = int(1.49 * _IN)
IMAGE_W  = int(4.20 * _IN)
IMAGE_H  = int(4.31 * _IN)

PAGENUM_L = int(4.23 * _IN)
PAGENUM_T = int(6.95 * _IN)
PAGENUM_W = int(1.54 * _IN)
PAGENUM_H = int(0.40 * _IN)


# ── State ─────────────────────────────────────────────────────────────────────

class SpeechPPTState(TypedDict):
    speech_topic: str              # overall speech subject (used for filename)
    slide_titles: list[str]        # one title per slide; if empty, derived from topic
    intern_name: Union[str, list[str]]
    task_date: str
    subdir: str
    generate_images: bool          # False = skip DALL-E (faster/cheaper)
    slides_data: list[dict]        # [{title, bullets:[str], image_path:str|None}]
    output_path: str
    log_path: str


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_anthropic() -> Anthropic:
    key = os.getenv("ANTHROPIC_API_KEY")
    if not key:
        raise EnvironmentError("ANTHROPIC_API_KEY not set in .env")
    return Anthropic(api_key=key)


def _get_openai():
    from openai import OpenAI
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        raise EnvironmentError("OPENAI_API_KEY not set in .env")
    return OpenAI(api_key=key)


def _parse_json(text: str):
    import re
    original = text
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    text = text.strip()
    match = re.search(r"(\{[\s\S]*\}|\[[\s\S]*\])", text)
    if match:
        text = match.group(1)
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        print(f"\n[DEBUG] JSON parse failed: {e}")
        print(f"[DEBUG] Raw response:\n{original[:2000]}")
        raise


def _intern_str(intern_name) -> str:
    if isinstance(intern_name, list):
        return ", ".join(intern_name)
    return intern_name or config.DEFAULT_INTERN_NAME


# ── Node 1: generate_content ──────────────────────────────────────────────────

def generate_content(state: SpeechPPTState) -> dict:
    """
    Given slide_titles (list) or speech_topic (str),
    produce 5 bullets (≤10 chars each) per slide.
    If slide_titles is empty, Claude first breaks the topic into slides.
    """
    client = _get_anthropic()

    titles = state.get("slide_titles") or []

    if not titles:
        # Step A: derive slide titles from speech topic
        plan_prompt = f"""你是一位演講稿規劃助理。根據以下演講主題，列出 5 至 8 個適合的投影片標題（每個標題為一張投影片）。
每個標題簡潔、清楚，不超過 15 個字。
回傳純 JSON 陣列，不要多餘說明。

演講主題：{state['speech_topic']}

範例格式：["智慧製造的定義", "機器人技術的影響", "台灣的競爭優勢"]
"""
        msg = client.messages.create(
            model=config.LLM_FAST,
            max_tokens=512,
            messages=[{"role": "user", "content": plan_prompt}],
        )
        from utils.cost_tracker import tracker
        tracker.record_claude(config.LLM_FAST, msg.usage.input_tokens, msg.usage.output_tokens)
        raw = next((b.text for b in msg.content if hasattr(b, "text")), "")
        titles = _parse_json(raw)

    # Step B: generate 5 bullets for every slide title
    bullets_prompt = f"""你是一位演講投影片撰寫助理。針對以下每個投影片標題，各生成 5 個重點條列（bullet points）。

規則：
- 每個 bullet **不超過 10 個中文字**（英文單字算 1 個字）
- 語言與標題一致（中文標題 → 繁體中文 bullet；英文標題 → 英文 bullet）
- 每個 bullet 必須獨立、具體、有資訊量
- 回傳純 JSON，格式如下：

[
  {{"title": "投影片標題1", "bullets": ["條列1", "條列2", "條列3", "條列4", "條列5"]}},
  {{"title": "投影片標題2", "bullets": [...]}}
]

投影片標題列表：
{json.dumps(titles, ensure_ascii=False)}
"""
    msg2 = client.messages.create(
        model=config.LLM_MAIN,
        max_tokens=2048,
        messages=[{"role": "user", "content": bullets_prompt}],
    )
    from utils.cost_tracker import tracker
    tracker.record_claude(config.LLM_MAIN, msg2.usage.input_tokens, msg2.usage.output_tokens)
    raw2 = next((b.text for b in msg2.content if hasattr(b, "text")), "")
    slides_raw = _parse_json(raw2)

    slides_data = [
        {"title": s["title"], "bullets": s["bullets"][:5], "image_path": None}
        for s in slides_raw
    ]

    return {"slides_data": slides_data, "slide_titles": titles}


# ── Node 2: generate_images ───────────────────────────────────────────────────

def generate_images(state: SpeechPPTState) -> dict:
    """Generate one DALL-E 3 image per slide, save to temp files."""
    if not state.get("generate_images", True):
        return {}   # skip

    client = _get_openai()
    slides = state["slides_data"]

    for i, slide in enumerate(slides):
        title = slide["title"]
        print(f"  DALL-E [{i+1}/{len(slides)}]: {title}")
        try:
            prompt = (
                f"Professional business presentation illustration for the topic: '{title}'. "
                "Clean, modern, corporate style. No text, no words, no letters. "
                "High quality photo or vector-style graphic suitable for a slide background image."
            )
            resp = client.images.generate(
                model="dall-e-3",
                prompt=prompt,
                size="1024x1024",
                quality="standard",
                n=1,
            )
            image_url = resp.data[0].url
            from utils.cost_tracker import tracker
            tracker.record_dalle(1)

            # Download to temp file
            import urllib.request
            tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
            urllib.request.urlretrieve(image_url, tmp.name)
            slide["image_path"] = tmp.name
        except Exception as e:
            print(f"  [WARN] Image generation failed for '{title}': {e}")
            slide["image_path"] = None

    return {"slides_data": slides}


# ── Node 3: build_ppt ─────────────────────────────────────────────────────────

def build_ppt(state: SpeechPPTState) -> dict:
    from pptx import Presentation
    from pptx.util import Pt, Emu
    from pptx.enum.text import PP_ALIGN
    from pptx.dml.color import RGBColor

    prs = Presentation()
    prs.slide_width  = Emu(SLIDE_W)
    prs.slide_height = Emu(SLIDE_H)

    blank_layout = prs.slide_layouts[6]  # blank

    slides_data = state["slides_data"]

    for slide_num, slide in enumerate(slides_data, start=1):
        sl = prs.slides.add_slide(blank_layout)

        # ── Title ──────────────────────────────────────────────────────────────
        title_box = sl.shapes.add_textbox(
            Emu(TITLE_L), Emu(TITLE_T), Emu(TITLE_W), Emu(TITLE_H)
        )
        tf = title_box.text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        run = p.add_run()
        run.text = slide["title"]
        run.font.size = Pt(TITLE_PT)
        run.font.bold = False
        run.font.color.rgb = RGBColor(0x00, 0x00, 0x00)

        # ── Bullets ────────────────────────────────────────────────────────────
        bullet_box = sl.shapes.add_textbox(
            Emu(BULLET_L), Emu(BULLET_T), Emu(BULLET_W), Emu(BULLET_H)
        )
        btf = bullet_box.text_frame
        btf.word_wrap = True

        for bi, bullet in enumerate(slide["bullets"][:5]):
            if bi == 0:
                bp = btf.paragraphs[0]
            else:
                bp = btf.add_paragraph()
            brun = bp.add_run()
            brun.text = bullet
            brun.font.size = Pt(BULLET_PT)
            brun.font.bold = True
            brun.font.color.rgb = RGBColor(0x00, 0x00, 0x00)

        # ── Image ──────────────────────────────────────────────────────────────
        img_path = slide.get("image_path")
        if img_path and Path(img_path).exists():
            sl.shapes.add_picture(
                img_path,
                Emu(IMAGE_L), Emu(IMAGE_T),
                Emu(IMAGE_W), Emu(IMAGE_H),
            )

        # ── Page number ────────────────────────────────────────────────────────
        pg_box = sl.shapes.add_textbox(
            Emu(PAGENUM_L), Emu(PAGENUM_T), Emu(PAGENUM_W), Emu(PAGENUM_H)
        )
        pp = pg_box.text_frame.paragraphs[0]
        pp.alignment = PP_ALIGN.CENTER
        pg_run = pp.add_run()
        pg_run.text = str(slide_num)
        pg_run.font.size = Pt(11)
        pg_run.font.color.rgb = RGBColor(0x40, 0x40, 0x40)

    # ── Save ───────────────────────────────────────────────────────────────────
    import shutil
    intern = state["intern_name"]
    task_date = state.get("task_date") or date.today().strftime("%Y-%m-%d")
    subdir = state.get("subdir", "adhoc")
    topic = state["speech_topic"]

    dot_date = task_date.replace("-", ".")
    filename = general(topic, intern, dot_date, ext="pptx")

    base = Path(config.OUTPUT_DIR) / subdir
    base.mkdir(parents=True, exist_ok=True)
    out_path = base / filename
    prs.save(str(out_path))

    dl_path = Path(config.DOWNLOADS_DIR) / filename
    shutil.copy2(out_path, dl_path)

    # Clean up temp image files
    for slide in slides_data:
        p = slide.get("image_path")
        if p and Path(p).exists():
            try:
                Path(p).unlink()
            except Exception:
                pass

    # Log
    logger = AgentLogger("speech_ppt_agent", f"Speech PPT: {topic}", intern)
    log_path = logger.save(out_path)

    return {"output_path": str(out_path), "log_path": str(log_path)}


# ── Graph ─────────────────────────────────────────────────────────────────────

def build_graph():
    graph = StateGraph(SpeechPPTState)
    graph.add_node("generate_content", generate_content)
    graph.add_node("generate_images",  generate_images)
    graph.add_node("build_ppt",        build_ppt)

    graph.set_entry_point("generate_content")
    graph.add_edge("generate_content", "generate_images")
    graph.add_edge("generate_images",  "build_ppt")
    graph.add_edge("build_ppt",        END)

    return graph.compile()


# ── Public entry point ────────────────────────────────────────────────────────

def run(
    speech_topic: str,
    slide_titles: list[str] = None,
    intern_name: Union[str, list[str]] = None,
    task_date: str = None,
    subdir: str = "weekly",
    generate_images: bool = True,
    # router compat
    task_instruction: str = None,
) -> dict:
    """
    Generate a speech PPT.

    Args:
        speech_topic:   Overall topic (used for filename + slide planning).
        slide_titles:   Optional list of specific slide titles. If omitted,
                        Claude generates them from speech_topic.
        intern_name:    For file naming.
        task_date:      YYYY-MM-DD; defaults to today.
        subdir:         Output subfolder.
        generate_images: If False, skip DALL-E image generation (faster).

    Returns:
        dict with 'output_path' and 'log_path'.
    """
    if not speech_topic and task_instruction:
        speech_topic = task_instruction

    app = build_graph()

    final_state = app.invoke({
        "speech_topic":    speech_topic,
        "slide_titles":    slide_titles or [],
        "intern_name":     intern_name or config.DEFAULT_INTERN_NAME,
        "task_date":       task_date or date.today().strftime("%Y-%m-%d"),
        "subdir":          subdir,
        "generate_images": generate_images,
        "slides_data":     [],
        "output_path":     "",
        "log_path":        "",
    })

    return {
        "output_path": final_state["output_path"],
        "log_path":    final_state["log_path"],
    }


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Speech PPT generator")
    parser.add_argument("--topic",    required=True,
                        help="Overall speech topic (used for filename & slide planning)")
    parser.add_argument("--titles",   default=None,
                        help="Semicolon-separated slide titles, e.g. '智慧製造定義; 機器人技術; ...'")
    parser.add_argument("--intern",   default=None)
    parser.add_argument("--date",     default=None)
    parser.add_argument("--subdir",   default="weekly", choices=["daily", "weekly", "adhoc"])
    parser.add_argument("--no-images", dest="no_images", action="store_true",
                        help="Skip DALL-E image generation (faster, no image cost)")
    args = parser.parse_args()

    slide_titles = (
        [t.strip() for t in args.titles.split(";") if t.strip()]
        if args.titles else None
    )

    intern = (
        [n.strip() for n in args.intern.split(",")]
        if args.intern and "," in args.intern
        else args.intern
    )

    print(f"生成演講 PPT：{args.topic}")
    result = run(
        speech_topic=args.topic,
        slide_titles=slide_titles,
        intern_name=intern,
        task_date=args.date,
        subdir=args.subdir,
        generate_images=not args.no_images,
    )
    print(f"  Output: {result['output_path']}")
    print(f"  Log:    {result['log_path']}")
