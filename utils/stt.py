"""
utils/stt.py — Speech-to-text via OpenAI gpt-4o-transcribe.

Tested on CY's m4a dictation recordings (Mandarin, ~6-11 min / 6-10MB).
gpt-4o-transcribe is an LLM-backed ASR model: it carries world knowledge,
so it disambiguates Mandarin homophones (company / person / institution
names) far better than the older whisper-1 acoustic model.

Long-audio caveat: gpt-4o-transcribe degenerates into a repetition loop
(e.g. "喂喂喂喂…") on single files beyond ~4-5 min. CY's dictations are
routinely 6-11 min, so files over `_SINGLE_CALL_LIMIT` are split into
`_CHUNK_SECONDS` segments with ffmpeg, transcribed separately, and joined.

gpt-4o-transcribe does not support response_format="verbose_json" and
does not return an audio duration; duration (for cost tracking) is probed
locally with ffprobe.

Script note: gpt-4o-transcribe returns Simplified Chinese for language='zh'.
CY works in Taiwan, so the final transcript is converted to Taiwan
Traditional Chinese (incl. local vocabulary) with OpenCC's s2twp.
"""
import os
import subprocess
import tempfile
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(override=True)

_STT_MODEL = "gpt-4o-transcribe"
_LANGUAGE = "zh"
_SINGLE_CALL_LIMIT = 240   # seconds; files at/under this go in one API call
_CHUNK_SECONDS = 180       # segment length for longer files (well under the ~4-5 min degeneration threshold)


def _probe_duration(path: Path) -> float:
    """Return audio duration in seconds via ffprobe; 0.0 if unavailable."""
    try:
        out = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True, text=True, timeout=30,
        )
        return float(out.stdout.strip())
    except (subprocess.SubprocessError, ValueError, FileNotFoundError):
        return 0.0


def _looks_degenerate(text: str) -> bool:
    """True if text is a repetition loop (one char dominating the output)."""
    t = text.strip()
    if len(t) < 20:
        return False
    return Counter(t).most_common(1)[0][1] / len(t) > 0.6


def _split_audio(path: Path, workdir: str) -> list[Path]:
    """Segment audio into _CHUNK_SECONDS mp3 chunks (16kHz mono) via ffmpeg."""
    pattern = str(Path(workdir) / "chunk_%03d.mp3")
    subprocess.run(
        [
            "ffmpeg", "-v", "error", "-i", str(path),
            "-f", "segment", "-segment_time", str(_CHUNK_SECONDS),
            "-ar", "16000", "-ac", "1", "-c:a", "libmp3lame", "-q:a", "5",
            pattern,
        ],
        check=True,
    )
    return sorted(Path(workdir).glob("chunk_*.mp3"))


def _to_traditional(text: str) -> str:
    """Convert Simplified Chinese transcript to Taiwan Traditional Chinese."""
    try:
        import opencc
    except ImportError:
        print("[stt] ⚠ 未安裝 opencc，略過繁簡轉換（pip install opencc）")
        return text
    return opencc.OpenCC("s2twp").convert(text)


def _transcribe_file(client, path: Path) -> str:
    """Single gpt-4o-transcribe call on one audio file."""
    with open(path, "rb") as f:
        result = client.audio.transcriptions.create(
            model=_STT_MODEL,
            file=f,
            language=_LANGUAGE,
            response_format="json",
        )
    return result.text


def transcribe(audio_path: str | Path) -> str:
    """
    Transcribe an audio file to text using OpenAI gpt-4o-transcribe.

    Files longer than ~4 min are chunked to avoid the model's long-audio
    repetition-loop failure mode.

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
    duration = _probe_duration(path)

    if duration and duration > _SINGLE_CALL_LIMIT:
        with tempfile.TemporaryDirectory() as workdir:
            chunks = _split_audio(path, workdir)
            parts: list[str] = []
            for i, chunk in enumerate(chunks):
                text = _transcribe_file(client, chunk)
                if _looks_degenerate(text):
                    print(f"[stt] ⚠ 第 {i + 1}/{len(chunks)} 段疑似退化迴圈，已略過")
                    continue
                parts.append(text.strip())
            transcript = "\n".join(p for p in parts if p)
    else:
        transcript = _transcribe_file(client, path)
        if _looks_degenerate(transcript):
            print("[stt] ⚠ 轉錄結果疑似退化迴圈，請確認音檔品質")

    from utils.cost_tracker import tracker
    tracker.record_whisper(duration)

    return _to_traditional(transcript)
