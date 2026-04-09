import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from database import get_danbooru_client

router = APIRouter()


@router.get("/api/danbooru/search")
async def danbooru_search(request: Request):
    """Proxy DanbooruFinder /search endpoint."""
    client = get_danbooru_client()
    try:
        resp = await client.get("/search", params=dict(request.query_params))
        return resp.json()
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"DanbooruFinder error: {e}")


@router.get("/api/danbooru/preview/{image_id}.{ext}")
async def danbooru_preview(image_id: int, ext: str):
    """Proxy DanbooruFinder /preview/<id>.<ext> with streaming."""
    client = get_danbooru_client()
    try:
        resp = await client.get(f"/preview/{image_id}.{ext}")
        if resp.status_code != 200:
            raise HTTPException(status_code=resp.status_code, detail="Upstream error")
        return StreamingResponse(
            iter([resp.content]),
            media_type=resp.headers.get("content-type", "image/jpeg"),
            headers={"Cache-Control": "public, max-age=86400, immutable"},
        )
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"DanbooruFinder error: {e}")


@router.get("/api/danbooru/thumbnail/{image_id}.{ext}")
async def danbooru_thumbnail(image_id: int, ext: str):
    """Proxy DanbooruFinder /thumbnail/<id>.<ext> with streaming."""
    client = get_danbooru_client()
    try:
        resp = await client.get(f"/thumbnail/{image_id}.{ext}")
        if resp.status_code != 200:
            raise HTTPException(status_code=resp.status_code, detail="Upstream error")
        return StreamingResponse(
            iter([resp.content]),
            media_type=resp.headers.get("content-type", "image/webp"),
            headers={"Cache-Control": "public, max-age=86400, immutable"},
        )
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"DanbooruFinder error: {e}")


@router.get("/api/danbooru/video_preview/{image_id}.{ext}")
async def danbooru_video_preview(image_id: int, ext: str):
    """Proxy DanbooruFinder /video_preview/<id>.<ext> with streaming."""
    client = get_danbooru_client()
    try:
        resp = await client.get(f"/video_preview/{image_id}.{ext}")
        if resp.status_code != 200:
            raise HTTPException(status_code=resp.status_code, detail="Upstream error")
        return StreamingResponse(
            iter([resp.content]),
            media_type=resp.headers.get("content-type", "video/mp4"),
            headers={"Cache-Control": "public, max-age=86400, immutable"},
        )
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"DanbooruFinder error: {e}")
