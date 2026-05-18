"""Serve transcoded ugoira animated WebPs.

GET /api/animation/{file_path:path}

- Resolves ``file_path`` under CRAWLER_DIR (same dual-candidate pattern used by
  the ``/images`` route).
- 404s if the path is not a ugoira zip (no ``animation.json``).
- Otherwise returns the cached animated WebP, transcoding on demand.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

import state
from services import ugoira_service

router = APIRouter()


@router.get("/api/animation/{file_path:path}")
async def serve_animation(file_path: str) -> FileResponse:
    source_path = state._resolve_under_crawler(file_path)
    if source_path is None:
        raise HTTPException(status_code=404, detail="File not found")

    if not ugoira_service.is_ugoira_zip(source_path):
        raise HTTPException(status_code=404, detail="Not a ugoira archive")

    try:
        webp_path = await ugoira_service.get_or_create_webp(source_path, file_path)
    except Exception as e:  # transcode failure
        raise HTTPException(status_code=500, detail=f"Transcode failed: {e}") from e

    return FileResponse(
        webp_path,
        media_type="image/webp",
        headers={"Cache-Control": "public, max-age=86400"},
    )
