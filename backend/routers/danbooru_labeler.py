import asyncio
import io
import json
import logging
import os
import zipfile
from pathlib import Path
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import state
from config import CANDIDATES_DB_PATH, DANBOORU_LIKES_DIR
from database import get_danbooru_client, get_danbooru_labels_db

logger = logging.getLogger(__name__)

router = APIRouter()


class DanbooruLabelRequest(BaseModel):
    verdict: str  # liked, disliked, skipped
    tags: list[str] = []
    ext: str = ""
    score: int = 0
    rating: str = ""
    danbooru_tags: str = ""  # JSON string of original danbooru tags


@router.get("/api/danbooru/labeler/next")
async def danbooru_labeler_next(
    rating: Optional[str] = Query(None),
    min_score: Optional[int] = Query(None),
    media: Optional[str] = Query(None),
):
    """Get the next unlabeled danbooru image for review."""
    dldb = await get_danbooru_labels_db()

    # Build DanbooruFinder search params
    params: dict = {"order_by": "random", "per_page": "20"}
    if rating:
        params["rating"] = rating
    if min_score is not None:
        params["min_score"] = str(min_score)

    client = get_danbooru_client()
    try:
        resp = await client.get("/search", params=params)
        data = resp.json()
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"DanbooruFinder error: {e}")

    results = data.get("results", [])
    pagination = data.get("pagination", {})

    # Check only the candidate IDs against labels (not ALL labeled IDs)
    candidate_ids = [item["id"] for item in results]
    if candidate_ids:
        placeholders = ",".join("?" * len(candidate_ids))
        async with dldb.execute(f"SELECT image_id FROM labels WHERE image_id IN ({placeholders})", candidate_ids) as c:
            labeled_ids = {r[0] for r in await c.fetchall()}
    else:
        labeled_ids = set()

    # Filter out already labeled
    for item in results:
        if item["id"] not in labeled_ids:
            is_video = item.get("ext", "") in ("mp4", "webm", "zip")
            if media == "image" and is_video:
                continue
            if media == "video" and not is_video:
                continue
            return {
                "image": {
                    "id": item["id"],
                    "ext": item.get("ext", "jpg"),
                    "score": item.get("score", 0),
                    "rating": item.get("rating", ""),
                    "created_at": item.get("created_at", ""),
                    "file_size": item.get("file_size", 0),
                    "tags": item.get("tags", ""),
                    "tag_categories": item.get("tag_categories", {}),
                    "is_video": is_video,
                    "thumb_url": f"/api/danbooru/thumbnail/{item['id']}.{item.get('ext', 'jpg')}",
                    "preview_url": f"/api/danbooru/preview/{item['id']}.{item.get('ext', 'jpg')}",
                    "video_url": f"/api/danbooru/video_preview/{item['id']}.{item.get('ext', 'jpg')}" if is_video else None,
                },
                "remaining": pagination.get("total", 0),
                "total_labeled": len(labeled_ids),
            }

    return {"image": None, "remaining": 0, "total_labeled": len(labeled_ids)}


@router.post("/api/danbooru/labeler/{image_id}")
async def danbooru_label_image(image_id: int, req: DanbooruLabelRequest):
    """Label a danbooru image as liked/disliked/skipped."""
    if req.verdict not in ("liked", "disliked", "skipped"):
        raise HTTPException(status_code=400, detail="verdict must be liked, disliked, or skipped")

    dldb = await get_danbooru_labels_db()
    await dldb.execute(
        """INSERT INTO labels (image_id, verdict, ext, score, rating, tags, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
           ON CONFLICT(image_id) DO UPDATE SET
             verdict=excluded.verdict, ext=excluded.ext, score=excluded.score,
             rating=excluded.rating, tags=excluded.tags, updated_at=CURRENT_TIMESTAMP""",
        [image_id, req.verdict, req.ext, req.score, req.rating, req.danbooru_tags],
    )

    if req.tags:
        clean_tags = [(image_id, t.strip()) for t in req.tags if t.strip()]
        if clean_tags:
            await dldb.executemany(
                "INSERT OR IGNORE INTO tags (image_id, tag) VALUES (?, ?)", clean_tags
            )

    await dldb.commit()

    # Auto-download liked images / remove if verdict changed away from liked
    if req.verdict == "liked" and req.ext:
        _task = asyncio.create_task(_download_danbooru_liked(image_id, req.ext))
        state._background_tasks.add(_task)
        _task.add_done_callback(state._background_tasks.discard)
    else:
        _task = asyncio.create_task(_remove_danbooru_liked(image_id))
        state._background_tasks.add(_task)
        _task.add_done_callback(state._background_tasks.discard)

    return {"ok": True}


async def _download_danbooru_liked(image_id: int, ext: str):
    """Download original image from DanbooruFinder to local likes folder."""
    try:
        DANBOORU_LIKES_DIR.mkdir(parents=True, exist_ok=True)
        dest = DANBOORU_LIKES_DIR / f"{image_id}.{ext}"
        if dest.exists():
            return
        client = get_danbooru_client()
        resp = await client.get(f"/original/{image_id}.{ext}", follow_redirects=True, timeout=60.0)
        if resp.status_code == 200:
            await asyncio.to_thread(dest.write_bytes, resp.content)
        elif resp.status_code == 404:
            resp2 = await client.get(f"/preview/{image_id}.{ext}", timeout=30.0)
            if resp2.status_code == 200:
                await asyncio.to_thread(dest.write_bytes, resp2.content)
    except Exception as e:
        logger.warning("[danbooru_likes] Failed to download %d.%s: %s", image_id, ext, e)


async def _remove_danbooru_liked(image_id: int):
    """Remove a previously downloaded liked image (on unlabel or verdict change)."""
    try:
        if not DANBOORU_LIKES_DIR.exists():
            return
        for f in DANBOORU_LIKES_DIR.glob(f"{image_id}.*"):
            f.unlink()
    except Exception as e:
        logger.warning("[danbooru_likes] Failed to remove %d: %s", image_id, e)


@router.delete("/api/danbooru/labeler/{image_id}")
async def danbooru_unlabel_image(image_id: int):
    """Remove label for a danbooru image (undo)."""
    dldb = await get_danbooru_labels_db()
    # Remove local file if it was liked
    _task = asyncio.create_task(_remove_danbooru_liked(image_id))
    state._background_tasks.add(_task)
    _task.add_done_callback(state._background_tasks.discard)
    await dldb.execute("DELETE FROM labels WHERE image_id = ?", [image_id])
    await dldb.execute("DELETE FROM tags WHERE image_id = ?", [image_id])
    await dldb.commit()
    return {"ok": True}


@router.get("/api/danbooru/labeler/stats")
async def danbooru_labeler_stats():
    """Get danbooru labeling statistics."""
    dldb = await get_danbooru_labels_db()

    stats = {"total_images": 0, "liked": 0, "disliked": 0, "skipped": 0}

    # Get total from DanbooruFinder
    client = get_danbooru_client()
    try:
        resp = await client.get("/search", params={"per_page": "1"})
        data = resp.json()
        stats["total_images"] = data.get("pagination", {}).get("total", 0)
    except httpx.HTTPError:
        pass

    async with dldb.execute("SELECT verdict, COUNT(*) FROM labels GROUP BY verdict") as c:
        for r in await c.fetchall():
            stats[r[0]] = r[1]

    stats["total_labeled"] = stats["liked"] + stats["disliked"] + stats["skipped"]
    stats["remaining"] = stats["total_images"] - stats["total_labeled"]

    # Top user tags
    async with dldb.execute("SELECT tag, COUNT(*) as cnt FROM tags GROUP BY tag ORDER BY cnt DESC LIMIT 50") as c:
        stats["top_tags"] = [{"tag": r[0], "count": r[1]} for r in await c.fetchall()]

    # --- Rating distribution (all labeled) ---
    rating_dist: dict[str, dict[str, int]] = {}
    async with dldb.execute(
        "SELECT rating, verdict, COUNT(*) FROM labels WHERE rating IS NOT NULL GROUP BY rating, verdict"
    ) as c:
        for r in await c.fetchall():
            rat, verd, cnt = r[0], r[1], r[2]
            if rat not in rating_dist:
                rating_dist[rat] = {}
            rating_dist[rat][verd] = cnt
    stats["rating_distribution"] = rating_dist

    # --- Liked: rating breakdown ---
    liked_by_rating: dict[str, int] = {}
    async with dldb.execute(
        "SELECT rating, COUNT(*) FROM labels WHERE verdict = 'liked' AND rating IS NOT NULL GROUP BY rating"
    ) as c:
        for r in await c.fetchall():
            liked_by_rating[r[0]] = r[1]
    stats["liked_by_rating"] = dict(sorted(liked_by_rating.items(), key=lambda x: x[1], reverse=True))

    # --- Labeled by rating (liked+disliked) for like-rate ---
    labeled_by_rating: dict[str, int] = {}
    async with dldb.execute(
        "SELECT rating, COUNT(*) FROM labels WHERE verdict IN ('liked', 'disliked') AND rating IS NOT NULL GROUP BY rating"
    ) as c:
        for r in await c.fetchall():
            labeled_by_rating[r[0]] = r[1]
    stats["labeled_by_rating"] = labeled_by_rating

    # --- Top danbooru tags from liked images ---
    liked_tag_counts: dict[str, int] = {}
    async with dldb.execute(
        "SELECT tags FROM labels WHERE verdict = 'liked' AND tags IS NOT NULL AND tags != ''"
    ) as c:
        for r in await c.fetchall():
            # Tags may be space-separated or comma-separated
            raw = r[0].replace(",", " ")
            for tag in raw.split():
                tag = tag.strip().strip(",")
                if tag:
                    liked_tag_counts[tag] = liked_tag_counts.get(tag, 0) + 1
    top_liked = sorted(liked_tag_counts.items(), key=lambda x: x[1], reverse=True)[:30]
    stats["liked_top_danbooru_tags"] = [{"tag": t, "count": c} for t, c in top_liked]

    return stats


@router.get("/api/danbooru/labeler/history")
async def danbooru_labeler_history(
    verdict: Optional[str] = Query(None, pattern="^(liked|disliked|skipped)$"),
    tag: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(60, ge=1, le=200),
):
    """Get danbooru labeled images history."""
    dldb = await get_danbooru_labels_db()

    conditions = ["1=1"]
    params: list = []

    if verdict:
        conditions.append("l.verdict = ?")
        params.append(verdict)

    if tag:
        conditions.append("l.image_id IN (SELECT image_id FROM tags WHERE tag = ?)")
        params.append(tag)

    where = " AND ".join(conditions)
    offset = (page - 1) * per_page

    async with dldb.execute(f"SELECT COUNT(*) FROM labels l WHERE {where}", params) as c:
        total = (await c.fetchone())[0]

    async with dldb.execute(
        f"""SELECT l.image_id, l.verdict, l.ext, l.score, l.rating, l.tags, l.updated_at
            FROM labels l WHERE {where} ORDER BY l.updated_at DESC LIMIT ? OFFSET ?""",
        params + [per_page, offset],
    ) as c:
        label_rows = await c.fetchall()

    if not label_rows:
        return {"images": [], "total": total, "page": page, "per_page": per_page, "pages": 0}

    image_ids = [r[0] for r in label_rows]

    # Fetch user tags
    placeholders = ",".join("?" * len(image_ids))
    async with dldb.execute(
        f"SELECT image_id, tag FROM tags WHERE image_id IN ({placeholders})",
        image_ids,
    ) as c:
        tag_rows = await c.fetchall()

    tags_map: dict[int, list[str]] = {}
    for r in tag_rows:
        tags_map.setdefault(r[0], []).append(r[1])

    # Fetch vision scores from candidates.db
    import aiosqlite as _aiosqlite
    vision_map: dict[int, float] = {}
    try:
        async with _aiosqlite.connect(str(CANDIDATES_DB_PATH)) as cdb:
            cdb.row_factory = _aiosqlite.Row
            async with cdb.execute(
                f"SELECT image_id, cnn_score FROM candidates WHERE image_id IN ({placeholders}) AND cnn_score IS NOT NULL",
                image_ids,
            ) as vc:
                async for vrow in vc:
                    vision_map[vrow[0]] = round(vrow[1], 4)
    except Exception:
        pass

    images = []
    for r in label_rows:
        img_id = r[0]
        ext = r[2] or "jpg"
        is_video = ext in ("mp4", "webm", "zip")
        danbooru_tags_raw = r[5]
        try:
            danbooru_tags = danbooru_tags_raw if danbooru_tags_raw else ""
        except Exception:
            danbooru_tags = ""

        images.append({
            "id": img_id,
            "ext": ext,
            "score": r[3] or 0,
            "rating": r[4] or "",
            "danbooru_tags": danbooru_tags,
            "is_video": is_video,
            "thumb_url": f"/api/danbooru/thumbnail/{img_id}.{ext}",
            "preview_url": f"/api/danbooru/preview/{img_id}.{ext}",
            "video_url": f"/api/danbooru/video_preview/{img_id}.{ext}" if is_video else None,
            "verdict": r[1],
            "updated_at": r[6],
            "tags": tags_map.get(img_id, []),
            "vision_score": vision_map.get(img_id),
        })

    return {
        "images": images,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page if total > 0 else 0,
    }


@router.get("/api/danbooru/labeler/export")
async def danbooru_export_liked(
    verdict: str = Query("liked", pattern="^(liked|disliked|skipped)$"),
    tag: Optional[str] = Query(None),
    max_size: int = Query(1024, ge=0, le=4096, description="Max dimension in pixels"),
):
    """Export danbooru labeled images as a ZIP archive.

    Liked: read from local DANBOORU_LIKES_DIR (fast, no network).
    Disliked/skipped: fetch from DanbooruFinder API then resize.
    All images resized to max_size. ZIP streamed via temp file.
    """
    import tempfile

    dldb = await get_danbooru_labels_db()

    conditions = ["l.verdict = ?"]
    params: list = [verdict]
    if tag:
        conditions.append("l.image_id IN (SELECT image_id FROM tags WHERE tag = ?)")
        params.append(tag)
    where = " AND ".join(conditions)

    async with dldb.execute(
        f"SELECT image_id, ext, score, rating, tags FROM labels l WHERE {where}", params
    ) as c:
        rows = await c.fetchall()

    if not rows:
        raise HTTPException(status_code=404, detail="No images found for export")

    # Fetch user tags
    image_ids = [r[0] for r in rows]
    placeholders = ",".join("?" * len(image_ids))
    async with dldb.execute(
        f"SELECT image_id, tag FROM tags WHERE image_id IN ({placeholders})", image_ids
    ) as c:
        tag_rows = await c.fetchall()

    tags_map: dict[int, list[str]] = {}
    for r in tag_rows:
        tags_map.setdefault(r[0], []).append(r[1])

    local_dir = DANBOORU_LIKES_DIR if verdict == "liked" else None

    # Phase 1: resolve image sources -> list of (row_tuple, local_path_or_None)
    # For items without local files, batch-download from API
    items: list[tuple] = []  # (img_id, ext, score, rating, danbooru_tags, local_path_str|None)
    need_download: list[tuple[int, int, str]] = []  # (index_in_items, img_id, ext)

    for r in rows:
        img_id, ext = r[0], r[1] or "jpg"
        local_path = None
        if local_dir:
            lp = local_dir / f"{img_id}.{ext}"
            if lp.exists():
                local_path = str(lp)
        items.append((img_id, ext, r[2], r[3], r[4], local_path))
        if local_path is None:
            need_download.append((len(items) - 1, img_id, ext))

    # Phase 2: async download missing images (concurrency-limited)
    downloaded: dict[int, bytes] = {}  # index -> bytes
    if need_download:
        client = get_danbooru_client()
        sem = asyncio.Semaphore(10)

        async def _fetch(idx: int, img_id: int, ext: str):
            async with sem:
                try:
                    resp = await client.get(f"/preview/{img_id}.{ext}", timeout=30.0)
                    if resp.status_code == 200:
                        downloaded[idx] = resp.content  # noqa: F821
                except Exception:
                    pass

        await asyncio.gather(*[_fetch(i, iid, e) for i, iid, e in need_download])

    # Phase 3: build ZIP in thread (CPU-bound resize)
    tags_snap = dict(tags_map)
    items_snap = list(items)
    downloaded_snap = dict(downloaded)
    del downloaded  # free refs

    def _build_zip_sync() -> tuple[str, str, int, int]:
        from PIL import Image as _PIL
        _PIL.MAX_IMAGE_PIXELS = 100_000_000

        tmp_fd = tempfile.NamedTemporaryFile(delete=False, suffix=".zip", dir="/tmp")
        tmp_path = tmp_fd.name
        meta = []
        packed = skipped = 0

        with zipfile.ZipFile(tmp_fd, 'w', zipfile.ZIP_STORED) as zf:
            for idx, (img_id, ext, score, rating, dtags, local_p) in enumerate(items_snap):
                raw = None
                if local_p:
                    try:
                        raw = Path(local_p).read_bytes()
                    except OSError:
                        pass
                if raw is None:
                    raw = downloaded_snap.get(idx)
                if raw is None:
                    skipped += 1
                    continue

                # Resize
                if max_size == 0:
                    data = raw
                    out_ext = ext or "jpg"
                    del raw
                else:
                    try:
                        img = _PIL.open(io.BytesIO(raw))
                        if img.mode in ("RGBA", "P", "LA"):
                            out_fmt, out_ext = "PNG", "png"
                        else:
                            img = img.convert("RGB")
                            out_fmt, out_ext = "JPEG", "jpg"
                        w, h = img.size
                        if max(w, h) > max_size:
                            ratio = max_size / max(w, h)
                            img = img.resize((int(w * ratio), int(h * ratio)), _PIL.LANCZOS)
                        buf = io.BytesIO()
                        img.save(buf, format=out_fmt, quality=92)
                        data = buf.getvalue()
                        del img, buf, raw
                    except Exception:
                        data = raw
                        out_ext = ext
                    del raw

                filename = f"{img_id}.{out_ext}"
                zf.writestr(f"images/{filename}", data)
                del data
                meta.append({
                    "id": img_id, "ext": out_ext, "original_ext": ext,
                    "score": score, "rating": rating, "danbooru_tags": dtags,
                    "user_tags": tags_snap.get(img_id, []), "filename": filename,
                })
                packed += 1

            zf.writestr("metadata.json", json.dumps(meta, ensure_ascii=False, indent=2))

        tag_suffix = f"_{tag}" if tag else ""
        dl_name = f"danbooru_{verdict}{tag_suffix}_{packed}imgs.zip"
        return tmp_path, dl_name, packed, skipped

    loop = asyncio.get_running_loop()
    tmp_path, dl_filename, packed, skipped = await loop.run_in_executor(state._io_executor, _build_zip_sync)

    if packed == 0:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise HTTPException(status_code=404, detail="No image files could be loaded")

    if skipped > 0:
        logger.info("[danbooru_export] %s: packed %d, skipped %d", verdict, packed, skipped)

    async def _stream_and_cleanup():
        try:
            with open(tmp_path, "rb") as f:
                while chunk := f.read(1024 * 1024):
                    yield chunk
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    return StreamingResponse(
        _stream_and_cleanup(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{dl_filename}"'},
    )
