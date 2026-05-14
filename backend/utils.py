"""Pure utility functions for the Sieve backend."""

import asyncio
import json
import logging
import mimetypes
import threading
import time
from functools import wraps
from pathlib import Path

from fastapi import Request
from fastapi.responses import FileResponse, StreamingResponse

import state
from config import CRAWLER_DIR

logger = logging.getLogger(__name__)

_novel_cache_lock = threading.Lock()


def ttl_cache(seconds: int = 30, maxsize: int = 64):
    """Simple TTL cache for async functions. Supports one cache slot per unique args tuple."""

    def decorator(fn):
        _cache: dict[tuple, tuple[float, object]] = {}
        _lock = asyncio.Lock()

        @wraps(fn)
        async def wrapper(*args, **kwargs):
            key = args + tuple(sorted(kwargs.items()))
            now = time.monotonic()
            async with _lock:
                if key in _cache:
                    ts, result = _cache[key]
                    if now - ts < seconds:
                        return result
            result = await fn(*args, **kwargs)
            async with _lock:
                _cache[key] = (now, result)
                if len(_cache) > maxsize:
                    expired = [k for k, (ts, _) in _cache.items() if now - ts >= seconds]
                    for k in expired:
                        del _cache[k]
            return result

        async def cache_clear():
            async with _lock:
                _cache.clear()

        wrapper.cache_clear = cache_clear
        return wrapper

    return decorator


async def _fetch_all_vision_scores(ldb, image_ids: list[int]) -> dict[int, dict[str, float]]:
    """Fetch vision scores from all models for given image IDs. Returns {image_id: {model_name: score}}."""
    if not image_ids:
        return {}
    placeholders = ",".join("?" * len(image_ids))
    result: dict[int, dict[str, float]] = {}
    async with ldb.execute(
        f"SELECT image_id, model_name, score FROM vision_scores WHERE image_id IN ({placeholders})",
        list(image_ids),
    ) as vc:
        async for row in vc:
            result.setdefault(row[0], {})[row[1]] = round(row[2], 4)
    return result


def _range_file_response(file_path: Path, request: Request) -> StreamingResponse | FileResponse:
    """Serve a file with HTTP Range support (needed for video playback)."""
    ext = file_path.suffix.lower()
    content_type = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
    file_size = file_path.stat().st_size

    range_header = request.headers.get("range")
    fallback_headers = {"Cache-Control": "public, max-age=86400, immutable"}
    if ext in state.VIDEO_EXTS:
        fallback_headers["Accept-Ranges"] = "bytes"
    if range_header and ext in state.VIDEO_EXTS:
        range_spec = range_header.strip().lower()
        if range_spec.startswith("bytes="):
            range_spec = range_spec[6:]
        try:
            parts = range_spec.split("-", 1)
            start = int(parts[0]) if parts[0] else 0
            end = int(parts[1]) if parts[1] else file_size - 1
        except (ValueError, IndexError):
            return FileResponse(file_path, headers=fallback_headers)
        if start < 0 or start >= file_size or end < start:
            return FileResponse(file_path, headers=fallback_headers)
        end = min(end, file_size - 1)
        length = end - start + 1

        def iter_range():
            CHUNK = 1024 * 1024
            with open(file_path, "rb") as f:
                f.seek(start)
                remaining = length
                while remaining > 0:
                    chunk = f.read(min(CHUNK, remaining))
                    if not chunk:
                        break
                    remaining -= len(chunk)
                    yield chunk

        return StreamingResponse(
            iter_range(),
            status_code=206,
            media_type=content_type,
            headers={
                "Content-Range": f"bytes {start}-{end}/{file_size}",
                "Content-Length": str(length),
                "Accept-Ranges": "bytes",
                "Cache-Control": "public, max-age=86400, immutable",
            },
        )

    headers = fallback_headers
    return FileResponse(file_path, headers=headers)


def _read_novel_meta(file_path: str, include_text: bool = False) -> dict:
    """Read novel metadata from JSON file on disk, with in-memory caching."""
    if not file_path:
        return {}

    cache_key = file_path
    now = time.monotonic()

    with _novel_cache_lock:
        if not include_text and cache_key in state._novel_meta_cache:
            ts, cached = state._novel_meta_cache[cache_key]
            if now - ts < state._NOVEL_CACHE_TTL:
                state._novel_meta_cache.move_to_end(cache_key)
                return cached

    full_path = CRAWLER_DIR / file_path
    if not full_path.exists():
        full_path = Path(file_path)
    if not full_path.exists():
        return {}
    try:
        with open(full_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        result = {
            "title": data.get("title", ""),
            "author": data.get("author", ""),
            "tags": data.get("tags", []),
            "text_length": data.get("text_length", len(data.get("text", ""))),
            "total_bookmarks": data.get("total_bookmarks", 0),
            "total_view": data.get("total_view", 0),
            "series_title": data.get("series_title"),
            "series_id": data.get("series_id"),
            "caption": data.get("caption", ""),
            "r18": data.get("r18", False),
        }
        if include_text:
            result["text"] = data.get("text", "")
        else:
            with _novel_cache_lock:
                if len(state._novel_meta_cache) >= state._NOVEL_CACHE_MAX:
                    state._novel_meta_cache.popitem(last=False)
                state._novel_meta_cache[cache_key] = (now, result)
        return result
    except Exception:
        logger.debug("Failed to read novel meta: %s", file_path, exc_info=True)
        return {}


def extract_date_from_path(file_path: str | None) -> str | None:
    """Extract a YYYY-MM-DD date component from a file path."""
    if not file_path:
        return None
    parts = file_path.split("/")
    for p in parts:
        if len(p) == 10 and p[4] == "-" and p[7] == "-":
            return p
    return None
