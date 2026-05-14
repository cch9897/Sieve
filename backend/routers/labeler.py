import json
import random
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import state
from config import CRAWLER_DIR
from database import get_db, get_labels_db_async
from export_utils import build_zip_to_temp, stream_and_cleanup
from services import labeler_service as svc
from utils import _fetch_all_vision_scores, ttl_cache

VIDEO_EXTS = state.VIDEO_EXTS
_video_exclude_sql, _video_exclude_params = state.video_filter_sql()
_video_include_parts, _video_include_params = state.video_include_sql()

router = APIRouter()

# Local labeler uses no extra columns on the labels table.
LABELER_CFG = svc.LOCAL_LABELER


class LabelRequest(BaseModel):
    verdict: str  # liked, disliked, skipped
    tags: list[str] = []


@router.get("/api/labeler/next")
async def labeler_next(
    source: Optional[str] = Query(None),
    media: Optional[str] = Query(None, pattern="^(image|video)$"),
):
    """Get the next unlabeled image for review."""
    ldb = await get_labels_db_async()

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

    conditions.append("id NOT IN (SELECT image_id FROM labels)")
    where = " AND ".join(conditions)

    async with ldb.execute("SELECT COUNT(*) FROM labels") as c:
        total_labeled = (await c.fetchone())[0]

    async with ldb.execute(f"SELECT COUNT(*) FROM main_db.images WHERE {where}", params) as c:
        remaining = (await c.fetchone())[0]

    if remaining == 0:
        return {"image": None, "remaining": 0, "total_labeled": total_labeled}

    # ID-based random sampling: O(log n) via PK scan instead of O(n) OFFSET
    minmax_sql = f"SELECT MIN(id), MAX(id) FROM main_db.images WHERE {where}"
    async with ldb.execute(minmax_sql, params) as c:
        min_id, max_id = await c.fetchone()

    random_id = random.randint(min_id, max_id)
    forward_sql = f"SELECT id, source, source_id, file_path, url, created_at FROM main_db.images WHERE {where} AND id >= ? ORDER BY id LIMIT 10"
    async with ldb.execute(forward_sql, params + [random_id]) as c:
        candidates = await c.fetchall()

    if len(candidates) < 10 and len(candidates) < remaining:
        seen_ids = {row["id"] for row in candidates}
        wrap_sql = f"SELECT id, source, source_id, file_path, url, created_at FROM main_db.images WHERE {where} AND id < ? ORDER BY id LIMIT ?"
        async with ldb.execute(wrap_sql, params + [random_id, 10 - len(candidates)]) as c:
            wrap_rows = await c.fetchall()
        for row in wrap_rows:
            if row["id"] not in seen_ids:
                candidates.append(row)

    candidate_ids = [row["id"] for row in candidates]
    all_scores = await _fetch_all_vision_scores(ldb, candidate_ids)
    active_db_name = state._active_model_db_name() if state._active_model else ""

    for row in candidates:
        fp = row["file_path"]
        full_path = CRAWLER_DIR / fp
        if not full_path.exists():
            continue

        ext = Path(fp).suffix.lower()
        parts = fp.split("/")
        scores = all_scores.get(row["id"], {})
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
            "total_labeled": total_labeled,
        }

    return {"image": None, "remaining": remaining, "total_labeled": total_labeled}


@router.post("/api/labeler/{image_id}")
async def label_image(image_id: int, req: LabelRequest):
    """Label an image as liked/disliked/skipped, optionally with tags."""
    if req.verdict not in ("liked", "disliked", "skipped"):
        raise HTTPException(status_code=400, detail="verdict must be liked, disliked, or skipped")

    ldb = await get_labels_db_async()
    await svc.apply_label(ldb, LABELER_CFG, image_id, req.verdict, req.tags)
    await _labeler_stats_cached.cache_clear()
    return {"ok": True}


@router.delete("/api/labeler/{image_id}")
async def unlabel_image(image_id: int):
    """Remove label and tags for an image (undo)."""
    ldb = await get_labels_db_async()
    await svc.remove_label(ldb, LABELER_CFG, image_id)
    await _labeler_stats_cached.cache_clear()
    return {"ok": True}


@router.get("/api/labeler/stats")
async def labeler_stats():
    """Get labeling statistics."""
    return await _labeler_stats_cached()


@ttl_cache(seconds=15)
async def _labeler_stats_cached():
    ldb = await get_labels_db_async()

    async with ldb.execute("SELECT COUNT(*) FROM main_db.images WHERE file_path IS NOT NULL") as c:
        total_images = (await c.fetchone())[0]

    counts = await svc.fetch_verdict_counts(ldb, LABELER_CFG)
    stats = {
        "total_images": total_images,
        "liked": counts["liked"],
        "disliked": counts["disliked"],
        "skipped": counts["skipped"],
        "total_labeled": counts["total_labeled"],
        "remaining": total_images - counts["total_labeled"],
    }

    stats["top_tags"] = await svc.fetch_top_user_tags(ldb, LABELER_CFG, limit=50)

    # Source distribution for liked images (cross-DB JOIN — labeler-specific)
    async with ldb.execute("""
        SELECT i.source, COUNT(*) FROM main_db.images i
        INNER JOIN labels l ON i.id = l.image_id
        WHERE l.verdict = 'liked'
        GROUP BY i.source ORDER BY COUNT(*) DESC
    """) as c:
        stats["liked_by_source"] = {r[0]: r[1] for r in await c.fetchall()}

    # Total images per source
    async with ldb.execute(
        "SELECT source, COUNT(*) FROM main_db.images WHERE file_path IS NOT NULL GROUP BY source"
    ) as c:
        stats["total_by_source"] = {r[0]: r[1] for r in await c.fetchall()}

    # Labeled (liked+disliked) per source
    async with ldb.execute("""
        SELECT i.source, COUNT(*) FROM main_db.images i
        INNER JOIN labels l ON i.id = l.image_id
        WHERE l.verdict IN ('liked', 'disliked')
        GROUP BY i.source
    """) as c:
        stats["labeled_by_source"] = {r[0]: r[1] for r in await c.fetchall()}

    # Auto-tag ranking for liked images (labels + auto_tags in same DB)
    liked_auto_tags: dict[str, int] = {}
    async with ldb.execute("""
        SELECT at.general_json FROM auto_tags at
        INNER JOIN labels l ON at.image_id = l.image_id
        WHERE l.verdict = 'liked' AND at.top_tags != '_error'
    """) as c:
        for r in await c.fetchall():
            try:
                for tag in json.loads(r[0]):
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

    total, label_rows = await svc.fetch_history_page(
        ldb,
        LABELER_CFG,
        select_columns="l.image_id, l.verdict, l.updated_at",
        verdict=verdict,
        tag=tag,
        page=page,
        per_page=per_page,
    )

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

    tags_map = await svc.fetch_user_tags_map(ldb, LABELER_CFG, image_ids)

    # Fetch vision scores (active model)
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
        images.append(
            {
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
            }
        )

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
    await svc.replace_user_tags(ldb, LABELER_CFG, image_id, tags)
    return {"ok": True}


@router.get("/api/labeler/export")
async def export_liked(
    verdict: str = Query("liked", pattern="^(liked|disliked|skipped)$"),
    tag: Optional[str] = Query(None),
    max_size: int = Query(1024, ge=0, le=4096, description="Max dimension in pixels"),
):
    """Export liked (or filtered) images as a ZIP archive streamed to the client."""
    db = await get_db()
    ldb = await get_labels_db_async()

    target_rows = await svc.fetch_export_targets(
        ldb,
        LABELER_CFG,
        select_columns="l.image_id",
        verdict=verdict,
        tag=tag,
    )
    image_ids = [r[0] for r in target_rows]

    if not image_ids:
        raise HTTPException(status_code=404, detail="No images found for export")

    placeholders = ",".join("?" * len(image_ids))
    async with db.execute(
        f"SELECT id, file_path, source, source_id FROM images WHERE id IN ({placeholders}) AND file_path IS NOT NULL",
        image_ids,
    ) as c:
        rows = await c.fetchall()

    tags_map = await svc.fetch_user_tags_map(ldb, LABELER_CFG, image_ids)

    # Collect (img_id, file_path, full_path, source, source_id) for files that exist on disk.
    file_entries: list[tuple[int, str, str, str, str]] = []
    for r in rows:
        fp = r["file_path"]
        full_path = CRAWLER_DIR / fp
        if full_path.exists():
            file_entries.append((r["id"], fp, str(full_path), r["source"], r["source_id"]))

    if not file_entries:
        raise HTTPException(status_code=404, detail="No image files found on disk")

    tags_snap = dict(tags_map)

    def _fetch_bytes(item: tuple) -> tuple[bytes | None, str]:
        _img_id, fp, full_str, _src, _sid = item
        try:
            return Path(full_str).read_bytes(), Path(fp).suffix.lstrip(".")
        except OSError:
            return None, Path(fp).suffix.lstrip(".")

    def _arcname(item: tuple, ext: str) -> str:
        _img_id, fp, _full, _src, _sid = item
        return f"images/{Path(fp).stem}.{ext}"

    def _meta(item: tuple, arcname: str, _ext: str) -> dict:
        img_id, fp, _full, source, source_id = item
        return {
            "id": img_id,
            "source": source,
            "source_id": source_id,
            "file_path": fp,
            "filename": Path(arcname).name,
            "tags": tags_snap.get(img_id, []),
        }

    tag_suffix = f"_{tag}" if tag else ""
    dl_filename = f"booru_{verdict}{tag_suffix}_{len(file_entries)}imgs.zip"

    tmp_path, dl_filename, _packed, _skipped = await build_zip_to_temp(
        file_entries,
        max_size=max_size,
        fetch_bytes=_fetch_bytes,
        arcname_fn=_arcname,
        meta_fn=_meta,
        download_filename=dl_filename,
    )

    return StreamingResponse(
        stream_and_cleanup(tmp_path),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{dl_filename}"'},
    )
