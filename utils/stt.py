"""
utils/stt.py — Speech-to-text via OpenAI Whisper API.

Tested on CY's m4a dictation recordings (Mandarin, ~11 min / 10MB).
Whisper-1 with language='zh' handles mixed Mandarin/English well.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(override=True)

_WHISPER_MODEL = "whisper-1"
_LANGUAGE = "zh"


def transcribe(audio_path: str | Path) -> str:
    """
    Transcribe an audio file to text using OpenAI Whisper API.

    Args:
        audio_path: Path to the audio file (.m4a, .mp3, .wav, .mp4, etc.)

    Returns:
        Transcribed text as a string.
    """
    from openai import OpenAI

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise EnvironmentError("OPENAI_API_KEY not set in .env")

    path = Path(audio_path)
    if not path.exists():
        raise FileNotFoundError(f"Audio file not found: {path}")

    client = OpenAI(api_key=api_key)
    with open(path, "rb") as f:
        result = client.audio.transcriptions.create(
            model=_WHISPER_MODEL,
            file=f,
            language=_LANGUAGE,
            response_format="verbose_json",
        )

    duration = getattr(result, "duration", 0.0) or 0.0
    from utils.cost_tracker import tracker
    tracker.record_whisper(duration)

    return result.text
