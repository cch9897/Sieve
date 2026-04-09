import asyncio
import io
import json
import os
import zipfile
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import state
from config import CRAWLER_DIR
from database import get_db, get_labels_db_async
from utils import _fetch_all_vision_scores

VIDEO_EXTS = state.VIDEO_EXTS
_video_exclude_sql, _video_exclude_params = state.video_filter_sql()
_video_include_parts = " OR ".join("file_path LIKE ?" for _ in sorted(VIDEO_EXTS))
_video_include_params = [f"%{ext}" for ext in sorted(VIDEO_EXTS)]

router = APIRouter()


class LabelRequest(BaseModel):
    verdict: str  # liked, disliked, skipped
    tags: list[str] = []


@router.get("/api/labeler/next")
async def labeler_next(
    source: Optional[str] = Query(None),
    media: Optional[str] = Query(None, pattern="^(image|video)$"),
):
    """Get the next unlabeled image for review."""
    db = await get_db()
    ldb = await get_labels_db_async()

    # Get all labeled image IDs
    async with ldb.execute("SELECT image_id FROM labels") as c:
        labeled_ids = {r[0] for r in await c.fetchall()}

    conditions = ["file_path IS NOT NULL"]
    params: list = []
    if source:
        conditions.append("source = ?")
        params.append(source)
    if media == "video":
        conditions.append(f"({_video_include_parts})")
        params.extend(_video_include_params)
    elif media == "image":
        conditions.append(_video_exclude_sql)
        params.extend(_video_exclude_params)

    if labeled_ids:
        for i in range(0, len(labeled_ids), 900):
            batch = list(labeled_ids)[i:i+900]
            placeholders = ",".join("?" * len(batch))
            conditions.append(f"id NOT IN ({placeholders})")
            params.extend(batch)

    where = " AND ".join(conditions)

    # Count remaining
    async with db.execute(f"SELECT COUNT(*) FROM images WHERE {where}", params) as c:
        remaining = (await c.fetchone())[0]

    if remaining == 0:
        return {"image": None, "remaining": 0, "total_labeled": len(labeled_ids)}

    # Get random unlabeled images, try up to 10 to find one with an existing file
    sql = f"SELECT id, source, source_id, file_path, url, created_at FROM images WHERE {where} ORDER BY RANDOM() LIMIT 10"
    async with db.execute(sql, params) as c:
        candidates = await c.fetchall()

    for row in candidates:
        fp = row["file_path"]
        full_path = CRAWLER_DIR / fp
        if not full_path.exists():
            # Auto-skip missing files
            continue

        ext = Path(fp).suffix.lower()
        parts = fp.split("/")

        # Look up vision scores (all models)
        scores: dict[str, float] = {}
        async with ldb.execute(
            "SELECT model_name, score FROM vision_scores WHERE image_id = ?", [row["id"]]
        ) as vc:
            async for vrow in vc:
                scores[vrow[0]] = round(vrow[1], 4)
        active_db_name = state._active_model_db_name() if state._active_model else ""
        vision_score = scores.get(active_db_name) if active_db_name else next(iter(scores.values()), None)

        return {
            "image": {
                "id": row["id"],
                "source": row["source"],
                "source_id": row["source_id"],
                "file_path": fp,
                "url": row["url"],
                "created_at": row["created_at"],
                "date": parts[1] if len(parts) >= 2 else None,
                "is_video": ext in VIDEO_EXTS,
                "thumb_url": f"/api/thumb/{fp}",
                "vision_score": vision_score,
                "vision_scores": scores,
            },
            "remaining": remaining,
            "total_labeled": len(labeled_ids),
        }

    return {"image": None, "remaining": 0, "total_labeled": len(labeled_ids)}


@router.post("/api/labeler/{image_id}")
async def label_image(image_id: int, req: LabelRequest):
    """Label an image as liked/disliked/skipped, optionally with tags."""
    if req.verdict not in ("liked", "disliked", "skipped"):
        raise HTTPException(status_code=400, detail="verdict must be liked, disliked, or skipped")

    ldb = await get_labels_db_async()
    await ldb.execute(
        """INSERT INTO labels (image_id, verdict, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)
           ON CONFLICT(image_id) DO UPDATE SET verdict=excluded.verdict, updated_at=CURRENT_TIMESTAMP""",
        [image_id, req.verdict],
    )

    # Handle tags
    if req.tags:
        for tag in req.tags:
            tag = tag.strip()
            if tag:
                await ldb.execute(
                    "INSERT OR IGNORE INTO tags (image_id, tag) VALUES (?, ?)",
                    [image_id, tag],
                )

    await ldb.commit()
    return {"ok": True}


@router.delete("/api/labeler/{image_id}")
async def unlabel_image(image_id: int):
    """Remove label and tags for an image (undo)."""
    ldb = await get_labels_db_async()
    await ldb.execute("DELETE FROM labels WHERE image_id = ?", [image_id])
    await ldb.execute("DELETE FROM tags WHERE image_id = ?", [image_id])
    await ldb.commit()
    return {"ok": True}


@router.get("/api/labeler/stats")
async def labeler_stats():
    """Get labeling statistics."""
    db = await get_db()
    ldb = await get_labels_db_async()

    async with db.execute("SELECT COUNT(*) FROM images WHERE file_path IS NOT NULL") as c:
        total_images = (await c.fetchone())[0]

    stats = {"total_images": total_images, "liked": 0, "disliked": 0, "skipped": 0}
    async with ldb.execute("SELECT verdict, COUNT(*) FROM labels GROUP BY verdict") as c:
        for r in await c.fetchall():
            stats[r[0]] = r[1]

    stats["total_labeled"] = stats["liked"] + stats["disliked"] + stats["skipped"]
    stats["remaining"] = total_images - stats["total_labeled"]

    # Top tags (manual)
    async with ldb.execute("SELECT tag, COUNT(*) as cnt FROM tags GROUP BY tag ORDER BY cnt DESC LIMIT 50") as c:
        stats["top_tags"] = [{"tag": r[0], "count": r[1]} for r in await c.fetchall()]

    # --- Liked images: auto-tag ranking & source distribution ---
    # Get liked image IDs
    async with ldb.execute("SELECT image_id FROM labels WHERE verdict = 'liked'") as c:
        liked_ids = [r[0] for r in await c.fetchall()]

    # Source distribution for liked images
    liked_by_source: dict[str, int] = {}
    if liked_ids:
        # Query in batches to avoid SQL variable limit
        for i in range(0, len(liked_ids), 500):
            batch = liked_ids[i:i+500]
            placeholders = ",".join("?" * len(batch))
            async with db.execute(
                f"SELECT source, COUNT(*) FROM images WHERE id IN ({placeholders}) GROUP BY source",
                batch,
            ) as c:
                for r in await c.fetchall():
                    liked_by_source[r[0]] = liked_by_source.get(r[0], 0) + r[1]
    stats["liked_by_source"] = dict(sorted(liked_by_source.items(), key=lambda x: x[1], reverse=True))

    # Total images per source (for like-rate calculation)
    async with db.execute(
        "SELECT source, COUNT(*) FROM images WHERE file_path IS NOT NULL GROUP BY source"
    ) as c:
        stats["total_by_source"] = {r[0]: r[1] for r in await c.fetchall()}

    # Labeled (liked+disliked) per source for like-rate denominator
    labeled_ids: list[int] = []
    async with ldb.execute("SELECT image_id FROM labels WHERE verdict IN ('liked', 'disliked')") as c:
        labeled_ids = [r[0] for r in await c.fetchall()]

    labeled_by_source: dict[str, int] = {}
    if labeled_ids:
        for i in range(0, len(labeled_ids), 500):
            batch = labeled_ids[i:i+500]
            placeholders = ",".join("?" * len(batch))
            async with db.execute(
                f"SELECT source, COUNT(*) FROM images WHERE id IN ({placeholders}) GROUP BY source",
                batch,
            ) as c:
                for r in await c.fetchall():
                    labeled_by_source[r[0]] = labeled_by_source.get(r[0], 0) + r[1]
    stats["labeled_by_source"] = labeled_by_source

    # Auto-tag ranking for liked images
    liked_auto_tags: dict[str, int] = {}
    if liked_ids:
        for i in range(0, len(liked_ids), 500):
            batch = liked_ids[i:i+500]
            placeholders = ",".join("?" * len(batch))
            async with ldb.execute(
                f"SELECT general_json FROM auto_tags WHERE top_tags != '_error' AND image_id IN ({placeholders})",
                batch,
            ) as c:
                import json as _json
                for r in await c.fetchall():
                    try:
                        tags_dict = _json.loads(r[0])
                        for tag in tags_dict:
                            liked_auto_tags[tag] = liked_auto_tags.get(tag, 0) + 1
                    except Exception:
                        pass
    top_liked_tags = sorted(liked_auto_tags.items(), key=lambda x: x[1], reverse=True)[:50]
    stats["liked_top_auto_tags"] = [{"tag": t, "count": c} for t, c in top_liked_tags]

    return stats


@router.get("/api/labeler/history")
async def labeler_history(
    verdict: Optional[str] = Query(None, pattern="^(liked|disliked|skipped)$"),
    tag: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(60, ge=1, le=200),
):
    """Get labeled images history with optional filters."""
    db = await get_db()
    ldb = await get_labels_db_async()

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

    async with ldb.execute(f"SELECT COUNT(*) FROM labels l WHERE {where}", params) as c:
        total = (await c.fetchone())[0]

    async with ldb.execute(
        f"SELECT l.image_id, l.verdict, l.updated_at FROM labels l WHERE {where} ORDER BY l.updated_at DESC LIMIT ? OFFSET ?",
        params + [per_page, offset],
    ) as c:
        label_rows = await c.fetchall()

    if not label_rows:
        return {"images": [], "total": total, "page": page, "per_page": per_page, "pages": 0}

    image_ids = [r[0] for r in label_rows]
    verdict_map = {r[0]: r[1] for r in label_rows}

    # Fetch image data from main DB
    placeholders = ",".join("?" * len(image_ids))
    async with db.execute(
        f"SELECT id, source, source_id, file_path, url, created_at FROM images WHERE id IN ({placeholders})",
        image_ids,
    ) as c:
        img_rows = await c.fetchall()

    img_map = {r["id"]: r for r in img_rows}

    # Fetch tags for these images
    async with ldb.execute(
        f"SELECT image_id, tag FROM tags WHERE image_id IN ({placeholders})",
        image_ids,
    ) as c:
        tag_rows = await c.fetchall()

    tags_map: dict[int, list[str]] = {}
    for r in tag_rows:
        tags_map.setdefault(r[0], []).append(r[1])

    # Fetch vision scores (active model)
    _vh_params = list(image_ids)
    all_scores_map = await _fetch_all_vision_scores(ldb, image_ids)
    active_db_name = state._active_model_db_name() if state._active_model else ""

    images = []
    for iid in image_ids:
        r = img_map.get(iid)
        if not r:
            continue
        fp = r["file_path"]
        ext = Path(fp).suffix.lower() if fp else ""
        parts = (fp or "").split("/")
        scores = all_scores_map.get(iid, {})
        images.append({
            "id": r["id"],
            "source": r["source"],
            "source_id": r["source_id"],
            "file_path": fp,
            "url": r["url"],
            "created_at": r["created_at"],
            "date": parts[1] if len(parts) >= 2 else None,
            "is_video": ext in VIDEO_EXTS,
            "thumb_url": f"/api/thumb/{fp}",
            "verdict": verdict_map.get(iid),
            "tags": tags_map.get(iid, []),
            "vision_score": scores.get(active_db_name) if active_db_name else next(iter(scores.values()), None),
            "vision_scores": scores,
        })

    return {
        "images": images,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page if total > 0 else 0,
    }


@router.post("/api/labeler/{image_id}/tags")
async def update_tags(image_id: int, tags: list[str]):
    """Replace all tags for an image."""
    ldb = await get_labels_db_async()
    await ldb.execute("DELETE FROM tags WHERE image_id = ?", [image_id])
    for tag in tags:
        tag = tag.strip()
        if tag:
            await ldb.execute("INSERT OR IGNORE INTO tags (image_id, tag) VALUES (?, ?)", [image_id, tag])
    await ldb.commit()
    return {"ok": True}


@router.get("/api/labeler/export")
async def export_liked(
    verdict: str = Query("liked", pattern="^(liked|disliked|skipped)$"),
    tag: Optional[str] = Query(None),
    max_size: int = Query(1024, ge=0, le=4096, description="Max dimension in pixels"),
):
    """Export liked (or filtered) images as a ZIP archive streamed to the client."""
    import tempfile

    from PIL import Image as PILImage
    PILImage.MAX_IMAGE_PIXELS = 100_000_000

    db = await get_db()
    ldb = await get_labels_db_async()

    conditions = ["l.verdict = ?"]
    params: list = [verdict]

    if tag:
        conditions.append("l.image_id IN (SELECT image_id FROM tags WHERE tag = ?)")
        params.append(tag)

    where = " AND ".join(conditions)

    async with ldb.execute(f"SELECT image_id FROM labels l WHERE {where}", params) as c:
        image_ids = [r[0] for r in await c.fetchall()]

    if not image_ids:
        raise HTTPException(status_code=404, detail="No images found for export")

    placeholders = ",".join("?" * len(image_ids))
    async with db.execute(
        f"SELECT id, file_path, source, source_id FROM images WHERE id IN ({placeholders}) AND file_path IS NOT NULL",
        image_ids,
    ) as c:
        rows = await c.fetchall()

    # Fetch tags
    async with ldb.execute(
        f"SELECT image_id, tag FROM tags WHERE image_id IN ({placeholders})", image_ids
    ) as c:
        tag_rows = await c.fetchall()

    tags_map: dict[int, list[str]] = {}
    for r in tag_rows:
        tags_map.setdefault(r[0], []).append(r[1])

    # Collect valid file entries
    file_entries = []
    for r in rows:
        fp = r["file_path"]
        full_path = CRAWLER_DIR / fp
        if full_path.exists():
            file_entries.append((r["id"], fp, str(full_path), r["source"], r["source_id"]))

    if not file_entries:
        raise HTTPException(status_code=404, detail="No image files found on disk")

    # Serialisable copy of tags_map for thread
    tags_snap = dict(tags_map)

    def _build_zip_sync() -> tuple[str, str]:
        """Build entire ZIP in a worker thread. Returns (tmp_path, filename)."""
        from PIL import Image as _PIL
        _PIL.MAX_IMAGE_PIXELS = 100_000_000

        tmp_fd = tempfile.NamedTemporaryFile(delete=False, suffix=".zip", dir="/tmp")
        tmp_path = tmp_fd.name
        meta = []
        seen: set[str] = set()

        with zipfile.ZipFile(tmp_fd, 'w', zipfile.ZIP_STORED) as zf:
            for img_id, fp, full_str, source, source_id in file_entries:
                if max_size == 0:
                    # Original resolution: raw copy, no re-encoding
                    data = Path(full_str).read_bytes()
                    out_ext = Path(fp).suffix.lstrip(".")
                else:
                    try:
                        img = _PIL.open(full_str)
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
                        del img, buf  # free immediately
                    except Exception:
                        # fallback: raw copy
                        data = Path(full_str).read_bytes()
                        out_ext = Path(fp).suffix.lstrip(".")

                base = Path(fp).stem
                arcname = f"images/{base}.{out_ext}"
                c = 1
                while arcname in seen:
                    arcname = f"images/{base}_{c}.{out_ext}"
                    c += 1
                seen.add(arcname)
                zf.writestr(arcname, data)
                del data  # free
                meta.append({
                    "id": img_id, "source": source, "source_id": source_id,
                    "file_path": fp, "filename": Path(arcname).name,
                    "tags": tags_snap.get(img_id, []),
                })
            zf.writestr("metadata.json", json.dumps(meta, ensure_ascii=False, indent=2))

        tag_suffix = f"_{tag}" if tag else ""
        dl_name = f"booru_{verdict}{tag_suffix}_{len(meta)}imgs.zip"
        return tmp_path, dl_name

    loop = asyncio.get_running_loop()
    try:
        tmp_path, dl_filename = await loop.run_in_executor(None, _build_zip_sync)
    except Exception:
        raise

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
