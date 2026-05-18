import asyncio
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

import state
from services import ugoira_service
from utils import _range_file_response

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
    source_path = state._resolve_under_crawler(file_path)
    if source_path is None:
        raise HTTPException(status_code=404, detail="File not found")

    ext = source_path.suffix.lower()
    is_ugoira = ext == ".zip" and ugoira_service.is_ugoira_zip(source_path)
    if (ext in _ARCHIVE_EXTS and not is_ugoira) or (
        ext not in _IMAGE_EXTS and ext not in state.VIDEO_EXTS and not is_ugoira
    ):
        raise HTTPException(status_code=404, detail="Unsupported file type for thumbnail")

    # Videos: serve directly with range support
    if ext in state.VIDEO_EXTS:
        return _range_file_response(source_path, request)

    # Check cached thumbnail (try both original ext and .jpg)
    thumb_base = state.THUMBS_DIR / file_path
    for candidate_thumb in [thumb_base, thumb_base.with_suffix(".jpg")]:
        if candidate_thumb.exists():
            return FileResponse(
                candidate_thumb,
                headers={"Cache-Control": "public, max-age=86400, immutable"},
            )

    # Generate thumbnail in thread pool (non-blocking)
    loop = asyncio.get_running_loop()
    try:
        if is_ugoira:
            thumb_path = await loop.run_in_executor(
                state._image_executor, ugoira_service.extract_first_frame_thumb, source_path, thumb_base
            )
        else:
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
