"""
web/api/routes/uploads.py — Audio file uploads for STT-driven jobs.

Multipart endpoint with a 100 MB cap and an explicit extension allow-list
(STT requires ffmpeg-readable audio; common screen-recording / podcast
formats covered). Files land at:

    web/api/uploads/<user_id>/<uuid>.<ext>

Stored in DB as an Upload row (id, filename, path, size_bytes, mime).
Jobs reference uploads by id via `extra.upload_id` — the path never
crosses the HTTP boundary, so a malicious client can't make a job
read /etc/passwd.

Phase 5 covers ingest only. Cleanup of stale uploads (>30 days) is
Phase 7's housekeeping work.
"""

import logging
import mimetypes
import shutil
import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from web.api.config import settings
from web.api.db import get_session
from web.api.models import Upload
from web.api.schemas import UploadResponse

log = logging.getLogger("routes.uploads")
router = APIRouter(prefix="/uploads", tags=["uploads"])

# Audio formats STT (utils/stt.py via gpt-4o-transcribe) can handle.
# ffmpeg slices anything >4 min so as long as ffmpeg can read it, we
# accept. Conservative list — extending is one line.
_ALLOWED_AUDIO_EXTS = {
    ".m4a", ".mp3", ".wav", ".aiff", ".aif",
    ".webm", ".ogg", ".oga", ".opus", ".flac",
}
_MAX_BYTES = 100 * 1024 * 1024   # 100 MB

_REPO_ROOT = Path(__file__).resolve().parents[3]
_UPLOAD_ROOT = _REPO_ROOT / "web" / "api" / "uploads"


def _ext_or_none(filename: str) -> str | None:
    """Lowercased extension if present, else None. Multi-dot names take
    just the last segment so `report.tar.m4a` → `.m4a`."""
    if "." not in filename:
        return None
    return "." + filename.rsplit(".", 1)[-1].lower()


@router.post("/audio", response_model=UploadResponse, status_code=201)
async def upload_audio(
    file: Annotated[UploadFile, File(description="Audio file for STT")],
    db: Session = Depends(get_session),
) -> Upload:
    """
    Accept an audio upload, persist it, return the Upload row.

    The file is streamed to disk in chunks rather than loaded into
    memory — handles 100 MB files without RAM pressure.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="filename required")

    ext = _ext_or_none(file.filename)
    if ext is None or ext not in _ALLOWED_AUDIO_EXTS:
        raise HTTPException(
            status_code=415,
            detail=f"unsupported audio format {ext!r}; allowed: {sorted(_ALLOWED_AUDIO_EXTS)}",
        )

    # Phase 1+ : single user, "local" placeholder. Phase 7 wires real
    # auth identity here.
    user_id = "local"
    user_dir = _UPLOAD_ROOT / user_id
    user_dir.mkdir(parents=True, exist_ok=True)

    upload_id = uuid.uuid4().hex
    target = user_dir / f"{upload_id}{ext}"

    # Stream copy with a running size guard so we can refuse oversize
    # uploads partway through (UploadFile.size is set only after the
    # body's fully buffered, and we don't want to buffer 100 MB).
    bytes_written = 0
    chunk_size = 1024 * 1024  # 1 MB
    try:
        with target.open("wb") as fh:
            while True:
                chunk = await file.read(chunk_size)
                if not chunk:
                    break
                bytes_written += len(chunk)
                if bytes_written > _MAX_BYTES:
                    fh.close()
                    target.unlink(missing_ok=True)
                    raise HTTPException(
                        status_code=413,
                        detail=f"upload exceeds {_MAX_BYTES // (1024*1024)} MB cap",
                    )
                fh.write(chunk)
    except HTTPException:
        raise
    except Exception as exc:
        log.exception("upload failed for %s", file.filename)
        target.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"upload failed: {exc}") from exc

    mime = file.content_type or mimetypes.guess_type(file.filename)[0] or "application/octet-stream"

    row = Upload(
        id         = upload_id,
        user_id    = user_id,
        filename   = file.filename,
        path       = str(target),
        size_bytes = bytes_written,
        mime       = mime,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    log.info("upload %s: %s (%d bytes)", upload_id, file.filename, bytes_written)
    return row


@router.get("/{upload_id}", response_model=UploadResponse)
def get_upload(upload_id: str, db: Session = Depends(get_session)) -> Upload:
    row = db.get(Upload, upload_id)
    if row is None:
        raise HTTPException(status_code=404, detail="upload not found")
    return row
