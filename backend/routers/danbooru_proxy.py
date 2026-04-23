import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from database import get_danbooru_client

router = APIRouter()

CHUNK_SIZE = 65536


@router.get("/api/danbooru/search")
async def danbooru_search(request: Request):
    """Proxy DanbooruFinder /search endpoint."""
    client = get_danbooru_client()
    try:
        resp = await client.get("/search", params=dict(request.query_params))
        return resp.json()
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"DanbooruFinder error: {e}")


async def _stream_upstream(client: httpx.AsyncClient, url: str, default_media: str):
    """Stream an upstream response chunk-by-chunk instead of buffering entirely."""
    try:
        resp = await client.send(client.build_request("GET", url), stream=True)
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"DanbooruFinder error: {e}")

    if resp.status_code != 200:
        await resp.aclose()
        raise HTTPException(status_code=502, detail=f"Upstream error: {resp.status_code}")

    async def _iterate():
        try:
            async for chunk in resp.aiter_bytes(CHUNK_SIZE):
                yield chunk
        finally:
            await resp.aclose()

    return StreamingResponse(
        _iterate(),
        media_type=resp.headers.get("content-type", default_media),
        headers={"Cache-Control": "public, max-age=86400, immutable"},
    )


@router.get("/api/danbooru/preview/{image_id}.{ext}")
async def danbooru_preview(image_id: int, ext: str):
    """Proxy DanbooruFinder /preview/<id>.<ext> with streaming."""
    client = get_danbooru_client()
    return await _stream_upstream(client, f"/preview/{image_id}.{ext}", "image/jpeg")


@router.get("/api/danbooru/thumbnail/{image_id}.{ext}")
async def danbooru_thumbnail(image_id: int, ext: str):
    """Proxy DanbooruFinder /thumbnail/<id>.<ext> with streaming."""
    client = get_danbooru_client()
    return await _stream_upstream(client, f"/thumbnail/{image_id}.{ext}", "image/webp")


@router.get("/api/danbooru/video_preview/{image_id}.{ext}")
async def danbooru_video_preview(image_id: int, ext: str):
    """Proxy DanbooruFinder /video_preview/<id>.<ext> with streaming."""
    client = get_danbooru_client()
    return await _stream_upstream(client, f"/video_preview/{image_id}.{ext}", "video/mp4")
