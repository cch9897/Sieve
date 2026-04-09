import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

import state
from database import get_db, get_labels_db_async

VIDEO_EXTS = state.VIDEO_EXTS
_video_exclude_sql, _video_exclude_params = state.video_filter_sql()

router = APIRouter()


@router.get("/api/autotags/stats")
async def auto_tags_stats():
    """Get auto-tagging progress stats."""
    db = await get_db()
    ldb = await get_labels_db_async()

    async with ldb.execute("SELECT COUNT(*) FROM auto_tags WHERE top_tags != '_error'") as c:
        tagged = (await c.fetchone())[0]

    async with ldb.execute("SELECT COUNT(*) FROM auto_tags WHERE top_tags = '_error'") as c:
        errored = (await c.fetchone())[0]

    async with db.execute(
        f"SELECT COUNT(*) FROM images WHERE file_path IS NOT NULL AND {_video_exclude_sql}",
        _video_exclude_params,
    ) as c:
        total_raw = (await c.fetchone())[0]

    # Exclude corrupted/unreadable files from the total
    total = total_raw - errored

    # Top 50 most common auto-tags across all images (excluding errors)
    async with ldb.execute("SELECT general_json FROM auto_tags WHERE top_tags != '_error'") as c:
        rows = await c.fetchall()

    tag_counts: dict[str, int] = {}
    for r in rows:
        try:
            tags = json.loads(r[0])
            for tag in tags:
                tag_counts[tag] = tag_counts.get(tag, 0) + 1
        except Exception:
            pass

    top_tags = sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)[:50]

    # Per-source error breakdown
    errors_by_source: dict[str, int] = {}
    if errored > 0:
        async with ldb.execute("SELECT image_id FROM auto_tags WHERE top_tags = '_error'") as c:
            error_ids = [r[0] for r in await c.fetchall()]
        for i in range(0, len(error_ids), 500):
            batch = error_ids[i:i+500]
            placeholders = ",".join("?" * len(batch))
            async with db.execute(
                f"SELECT source, COUNT(*) FROM images WHERE id IN ({placeholders}) GROUP BY source",
                batch,
            ) as c:
                for r in await c.fetchall():
                    errors_by_source[r[0]] = errors_by_source.get(r[0], 0) + r[1]

    return {
        "tagged": tagged,
        "total": total,
        "remaining": total - tagged,
        "progress_pct": round(tagged / total * 100, 1) if total > 0 else 0,
        "top_tags": [{"tag": t, "count": c} for t, c in top_tags],
        "errored": errored,
        "errors_by_source": dict(sorted(errors_by_source.items(), key=lambda x: x[1], reverse=True)),
    }


@router.get("/api/autotags/search")
async def search_by_auto_tag(
    tag: str = Query(..., min_length=1),
    page: int = Query(1, ge=1),
    per_page: int = Query(60, ge=1, le=200),
):
    """Search images by auto-generated tag."""
    ldb = await get_labels_db_async()
    db = await get_db()

    # Find image IDs whose general_json or character_json contains the tag
    # We search top_tags for quick text matching
    pattern = f"%{tag}%"
    offset = (page - 1) * per_page

    async with ldb.execute(
        "SELECT COUNT(*) FROM auto_tags WHERE top_tags LIKE ?", [pattern]
    ) as c:
        total = (await c.fetchone())[0]

    async with ldb.execute(
        "SELECT image_id, top_tags FROM auto_tags WHERE top_tags LIKE ? ORDER BY image_id DESC LIMIT ? OFFSET ?",
        [pattern, per_page, offset],
    ) as c:
        tag_rows = await c.fetchall()

    if not tag_rows:
        return {"images": [], "total": total, "page": page, "per_page": per_page, "pages": 0}

    image_ids = [r[0] for r in tag_rows]
    tags_map = {r[0]: r[1] for r in tag_rows}

    placeholders = ",".join("?" * len(image_ids))
    async with db.execute(
        f"SELECT id, source, source_id, file_path, url, created_at FROM images WHERE id IN ({placeholders})",
        image_ids,
    ) as c:
        img_rows = await c.fetchall()

    img_map = {r["id"]: r for r in img_rows}

    images = []
    for iid in image_ids:
        r = img_map.get(iid)
        if not r:
            continue
        fp = r["file_path"]
        ext = Path(fp).suffix.lower() if fp else ""
        parts = (fp or "").split("/")
        images.append({
            "id": r["id"],
            "source": r["source"],
            "file_path": fp,
            "created_at": r["created_at"],
            "date": parts[1] if len(parts) >= 2 else None,
            "is_video": ext in VIDEO_EXTS,
            "thumb_url": f"/api/thumb/{fp}",
            "auto_tags": tags_map.get(iid, ""),
        })

    return {
        "images": images,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page if total > 0 else 0,
    }


@router.get("/api/autotags/batch")
async def batch_auto_tags(ids: str = Query(..., description="Comma-separated image IDs")):
    """Get auto-tags for multiple images at once (for gallery view)."""
    try:
        image_ids = [int(x.strip()) for x in ids.split(",") if x.strip()][:200]
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid image IDs")

    if not image_ids:
        return {"tags": {}}

    ldb = await get_labels_db_async()
    placeholders = ",".join("?" * len(image_ids))
    async with ldb.execute(
        f"SELECT image_id, top_tags, rating_json FROM auto_tags WHERE image_id IN ({placeholders})",
        image_ids,
    ) as c:
        rows = await c.fetchall()

    result = {}
    for r in rows:
        try:
            rating = json.loads(r[2])
            top_rating = max(rating.items(), key=lambda x: x[1])[0] if rating else ""
        except Exception:
            top_rating = ""
        result[str(r[0])] = {"top_tags": r[1], "rating": top_rating}

    return {"tags": result}


@router.get("/api/autotags/{image_id}")
async def get_auto_tags(image_id: int):
    """Get auto-generated tags for an image."""
    ldb = await get_labels_db_async()
    async with ldb.execute(
        "SELECT rating_json, general_json, character_json, top_tags, model_name, general_threshold, created_at FROM auto_tags WHERE image_id = ?",
        [image_id],
    ) as c:
        row = await c.fetchone()
    if not row:
        return {"found": False, "image_id": image_id}
    return {
        "found": True,
        "image_id": image_id,
        "rating": json.loads(row[0]),
        "general": json.loads(row[1]),
        "characters": json.loads(row[2]),
        "top_tags": row[3],
        "model_name": row[4],
        "threshold": row[5],
        "created_at": row[6],
    }
