import asyncio
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

import state
from config import CRAWLER_DIR
from utils import _range_file_response

VIDEO_EXTS = state.VIDEO_EXTS
THUMBS_DIR = state.THUMBS_DIR
_safe_under_crawler = state._safe_under_crawler
_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tiff", ".tif", ".avif"}
_ARCHIVE_EXTS = {".zip", ".rar", ".7z", ".gz", ".tar", ".bz2"}

router = APIRouter()


def _generate_thumb(source_path: Path, thumb_base: Path, thumb_width: int = 600) -> Path:
    """Generate a thumbnail synchronously (called in thread pool)."""
    from PIL import Image

    ext = source_path.suffix.lower()
    thumb_base.parent.mkdir(parents=True, exist_ok=True)

    with Image.open(source_path) as img:
        if img.width <= thumb_width:
            return source_path

        ratio = thumb_width / img.width
        new_h = int(img.height * ratio)
        thumb = img.resize((thumb_width, new_h), Image.LANCZOS)

        if ext == ".png" and img.mode == "RGBA":
            thumb.save(str(thumb_base), "PNG", optimize=True)
            return thumb_base
        else:
            if thumb.mode in ("RGBA", "P"):
                thumb = thumb.convert("RGB")
            save_path = thumb_base.with_suffix(".jpg")
            thumb.save(str(save_path), "JPEG", quality=85, optimize=True)
            return save_path


@router.get("/api/thumb/{file_path:path}")
async def serve_thumbnail(file_path: str, request: Request):
    """Serve cached thumbnail, generate in thread pool if missing."""
    source_path: Path | None = None
    from urllib.parse import quote

    for candidate in [file_path, quote(file_path, safe="/")]:
        full = CRAWLER_DIR / candidate
        if _safe_under_crawler(full) and full.exists():
            source_path = full
            break
    if source_path is None:
        raise HTTPException(status_code=404, detail="File not found")

    ext = source_path.suffix.lower()
    if ext in _ARCHIVE_EXTS or (ext not in _IMAGE_EXTS and ext not in VIDEO_EXTS):
        raise HTTPException(status_code=404, detail="Unsupported file type for thumbnail")

    # Videos: serve directly with range support
    if ext in VIDEO_EXTS:
        return _range_file_response(source_path, request)

    # Check cached thumbnail (try both original ext and .jpg)
    thumb_base = THUMBS_DIR / file_path
    for candidate_thumb in [thumb_base, thumb_base.with_suffix(".jpg")]:
        if candidate_thumb.exists():
            return FileResponse(
                candidate_thumb,
                headers={"Cache-Control": "public, max-age=86400, immutable"},
            )

    # Generate thumbnail in thread pool (non-blocking)
    try:
        loop = asyncio.get_running_loop()
        thumb_path = await loop.run_in_executor(state._image_executor, _generate_thumb, source_path, thumb_base)
        return FileResponse(
            thumb_path,
            headers={"Cache-Control": "public, max-age=86400, immutable"},
        )
    except Exception:
        if ext in _IMAGE_EXTS:
            return FileResponse(
                source_path,
                headers={"Cache-Control": "public, max-age=86400, immutable"},
            )
        raise HTTPException(status_code=404, detail="Thumbnail generation failed")
