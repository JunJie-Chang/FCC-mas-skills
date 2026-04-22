"""
utils/ocr.py — Extract text from images or PDFs using Claude Vision (Haiku).

Supported inputs:
    - .jpg / .jpeg / .png / .gif / .webp  → direct base64 encode
    - .pdf                                → each page converted to PNG, then OCR'd

Usage:
    from utils.ocr import extract_text
    body_text = extract_text("/path/to/screenshot.png")
"""
import base64
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=True)
load_dotenv(override=True)  # fallback for when cwd differs

_IMAGE_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                ".png": "image/png", ".gif": "image/gif", ".webp": "image/webp"}

_MAX_BYTES = 3_600_000  # ~3.6 MB raw → ~4.8 MB base64, safely under Claude's 5 MB limit


def _compress_image(image_bytes: bytes, media_type: str) -> tuple[bytes, str]:
    """Resize + recompress image if it exceeds _MAX_BYTES. Returns (bytes, media_type)."""
    if len(image_bytes) <= _MAX_BYTES:
        return image_bytes, media_type
    try:
        from PIL import Image
        import io
        img = Image.open(io.BytesIO(image_bytes))
        # Downscale until under limit
        quality = 85
        scale = 1.0
        while True:
            w = int(img.width * scale)
            h = int(img.height * scale)
            resized = img.resize((w, h), Image.LANCZOS)
            buf = io.BytesIO()
            resized.save(buf, format="JPEG", quality=quality)
            result = buf.getvalue()
            if len(result) <= _MAX_BYTES:
                print(f"  圖片壓縮：{len(image_bytes)//1024}KB → {len(result)//1024}KB")
                return result, "image/jpeg"
            if scale > 0.3:
                scale -= 0.15
            else:
                quality -= 10
            if quality < 30:
                raise ValueError("無法將圖片壓縮至 4MB 以下")
    except ImportError:
        raise ImportError("圖片超過 5MB，需要 Pillow 壓縮：pip install pillow")

_OCR_PROMPT = (
    "你是一個 OCR 工具。請將圖片中出現的所有文字，逐字逐句完整轉錄輸出，"
    "保留原文語言與段落結構，以空行分隔段落。"
    "不要評論內容、不要加任何解釋、不要拒絕、不要加前言或後記，只輸出文字本身。"
)


def _client():
    from anthropic import Anthropic
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise EnvironmentError("ANTHROPIC_API_KEY not set in .env")
    return Anthropic(api_key=api_key)


def _ocr_image_bytes(image_bytes: bytes, media_type: str) -> str:
    """Send one image to Claude Haiku and return extracted text."""
    image_bytes, media_type = _compress_image(image_bytes, media_type)
    client = _client()
    data = base64.standard_b64encode(image_bytes).decode("utf-8")

    message = client.messages.create(
        model=config.LLM_FAST,
        max_tokens=4096,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": media_type, "data": data},
                },
                {"type": "text", "text": _OCR_PROMPT},
            ],
        }],
    )

    from utils.cost_tracker import tracker
    tracker.record_claude(config.LLM_FAST, message.usage.input_tokens, message.usage.output_tokens)

    return next((b.text for b in message.content if hasattr(b, "text")), "").strip()


def _ocr_pdf(path: Path) -> str:
    """Convert each PDF page to PNG and OCR sequentially."""
    try:
        import fitz  # PyMuPDF
    except ImportError:
        raise ImportError(
            "需要 PyMuPDF 才能處理 PDF：pip install pymupdf"
        )

    doc = fitz.open(str(path))
    pages_text = []
    for page_num, page in enumerate(doc, start=1):
        print(f"  OCR 第 {page_num}/{len(doc)} 頁…")
        mat = fitz.Matrix(2.0, 2.0)  # 2x scale → 144 DPI for better accuracy
        pix = page.get_pixmap(matrix=mat)
        img_bytes = pix.tobytes("png")
        text = _ocr_image_bytes(img_bytes, "image/png")
        if text:
            pages_text.append(text)
    doc.close()

    return "\n\n".join(pages_text)


def extract_text(path: str) -> str:
    """
    Extract text from an image or PDF file using Claude Vision.

    Args:
        path: Absolute or relative path to .jpg/.png/.gif/.webp/.pdf

    Returns:
        Extracted text as a plain string.
    """
    p = Path(path).expanduser().resolve()
    if not p.exists():
        raise FileNotFoundError(f"找不到檔案：{path}")

    suffix = p.suffix.lower()

    if suffix == ".pdf":
        return _ocr_pdf(p)

    if suffix in _IMAGE_TYPES:
        media_type = _IMAGE_TYPES[suffix]
        return _ocr_image_bytes(p.read_bytes(), media_type)

    raise ValueError(f"不支援的檔案格式：{suffix}（支援：{', '.join(_IMAGE_TYPES)} .pdf）")
