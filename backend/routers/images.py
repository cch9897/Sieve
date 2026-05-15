import random
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

import state
from database import get_db, get_labels_db_async
from utils import _fetch_all_vision_scores, extract_date_from_path

_video_exclude_sql, _video_exclude_params = state.video_filter_sql()
_video_include_parts, _video_include_params = state.video_include_sql()

router = APIRouter()


@router.get("/api/images")
async def list_images(
    source: Optional[str] = Query(None),
    date: Optional[str] = Query(None),
    media: Optional[str] = Query(None, pattern="^(image|video)$"),
    sort: str = Query("newest", pattern="^(newest|oldest)$"),
    page: int = Query(1, ge=1),
    per_page: int = Query(60, ge=1, le=200),
):
    db = await get_db()
    conditions = ["file_path IS NOT NULL"]
    params: list = []

    if source:
        conditions.append("source = ?")
        params.append(source)

    if date:
        conditions.append("file_path LIKE ?")
        params.append(f"downloads/{date}/%")

    if media == "video":
        conditions.append(f"({_video_include_parts})")
        params.extend(_video_include_params)
    elif media == "image":
        conditions.append(_video_exclude_sql)
        params.extend(_video_exclude_params)

    where = " AND ".join(conditions)
    order = "created_at DESC" if sort == "newest" else "created_at ASC"
    offset = (page - 1) * per_page

    count_sql = f"SELECT COUNT(*) FROM images WHERE {where}"
    list_sql = f"SELECT id, source, source_id, file_path, url, created_at FROM images WHERE {where} ORDER BY {order} LIMIT ? OFFSET ?"

    async with (
        db.execute(count_sql, params) as count_cursor,
        db.execute(list_sql, params + [per_page, offset]) as list_cursor,
    ):
        total_row, rows = await count_cursor.fetchone(), await list_cursor.fetchall()
        total = total_row[0]

    # Batch fetch vision scores
    ldb = await get_labels_db_async()
    row_ids = [r["id"] for r in rows]
    all_scores_map = await _fetch_all_vision_scores(ldb, row_ids)

    # Active model score for backward compat
    active_db_name = state._active_model_db_name() if state._active_model else ""

    images = []
    for r in rows:
        fp = r["file_path"]
        parts = fp.split("/")
        img_date = extract_date_from_path(fp)
        subfolder = parts[2] if len(parts) >= 3 else None
        ext = Path(fp).suffix.lower()
        is_video = ext in state.VIDEO_EXTS

        scores = all_scores_map.get(r["id"], {})
        images.append(
            {
                "id": r["id"],
                "source": r["source"],
                "source_id": r["source_id"],
                "file_path": fp,
                "url": r["url"],
                "created_at": r["created_at"],
                "date": img_date,
                "subfolder": subfolder,
                "is_video": is_video,
                "thumb_url": f"/api/thumb/{fp}" if not is_video else f"/images/{fp}",
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


@router.get("/api/liked")
async def list_liked(
    source: Optional[str] = Query(None),
    date: Optional[str] = Query(None),
    media: Optional[str] = Query(None, pattern="^(image|video)$"),
    sort: str = Query("newest", pattern="^(newest|oldest)$"),
    page: int = Query(1, ge=1),
    per_page: int = Query(60, ge=1, le=200),
):
    """List liked images with the same filters as /api/images."""
    ldb = await get_labels_db_async()
    conditions = ["i.file_path IS NOT NULL", "l.verdict = 'liked'"]
    params: list = []

    if source:
        conditions.append("i.source = ?")
        params.append(source)

    if date:
        conditions.append("i.file_path LIKE ?")
        params.append(f"downloads/{date}/%")

    if media == "video":
        conditions.append(f"({_video_include_parts.replace('file_path', 'i.file_path')})")
        params.extend(_video_include_params)
    elif media == "image":
        conditions.append(_video_exclude_sql.replace("file_path", "i.file_path"))
        params.extend(_video_exclude_params)

    where = " AND ".join(conditions)
    order = "i.created_at DESC" if sort == "newest" else "i.created_at ASC"
    offset = (page - 1) * per_page

    count_sql = f"SELECT COUNT(*) FROM main_db.images i INNER JOIN labels l ON i.id = l.image_id WHERE {where}"
    list_sql = (
        f"SELECT i.id, i.source, i.source_id, i.file_path, i.url, i.created_at "
        f"FROM main_db.images i INNER JOIN labels l ON i.id = l.image_id "
        f"WHERE {where} ORDER BY {order} LIMIT ? OFFSET ?"
    )

    async with (
        ldb.execute(count_sql, params) as count_cursor,
        ldb.execute(list_sql, params + [per_page, offset]) as list_cursor,
    ):
        total_row, rows = await count_cursor.fetchone(), await list_cursor.fetchall()
        total = total_row[0]

    row_ids = [r["id"] for r in rows]
    all_scores_map = await _fetch_all_vision_scores(ldb, row_ids)

    active_db_name = state._active_model_db_name() if state._active_model else ""

    images = []
    for r in rows:
        fp = r["file_path"]
        parts = fp.split("/")
        img_date = extract_date_from_path(fp)
        subfolder = parts[2] if len(parts) >= 3 else None
        ext = Path(fp).suffix.lower()
        is_video = ext in state.VIDEO_EXTS

        scores = all_scores_map.get(r["id"], {})
        images.append(
            {
                "id": r["id"],
                "source": r["source"],
                "source_id": r["source_id"],
                "file_path": fp,
                "url": r["url"],
                "created_at": r["created_at"],
                "date": img_date,
                "subfolder": subfolder,
                "is_video": is_video,
                "thumb_url": f"/api/thumb/{fp}" if not is_video else f"/images/{fp}",
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


@router.get("/api/liked/random")
async def random_liked(
    source: Optional[str] = Query(None),
    date: Optional[str] = Query(None),
    media: Optional[str] = Query(None, pattern="^(image|video)$"),
    count: int = Query(1, ge=1, le=20),
):
    """Get random liked images using ID-based random sampling (O(log n))."""
    ldb = await get_labels_db_async()
    conditions = ["i.file_path IS NOT NULL", "l.verdict = 'liked'"]
    params: list = []

    if source:
        conditions.append("i.source = ?")
        params.append(source)

    if date:
        conditions.append("i.file_path LIKE ?")
        params.append(f"downloads/{date}/%")

    if media == "video":
        conditions.append(f"({_video_include_parts.replace('file_path', 'i.file_path')})")
        params.extend(_video_include_params)
    elif media == "image":
        conditions.append(_video_exclude_sql.replace("file_path", "i.file_path"))
        params.extend(_video_exclude_params)

    where = " AND ".join(conditions)

    # Count total matching liked images
    async with ldb.execute(
        f"SELECT COUNT(*) FROM main_db.images i INNER JOIN labels l ON i.id = l.image_id WHERE {where}", params
    ) as c:
        total = (await c.fetchone())[0]

    if total == 0:
        return {"images": [], "total": 0}

    # ID-based random sampling: pick a random offset in the ID range, scan forward
    minmax_sql = (
        f"SELECT MIN(i.id), MAX(i.id) FROM main_db.images i INNER JOIN labels l ON i.id = l.image_id WHERE {where}"
    )
    async with ldb.execute(minmax_sql, params) as c:
        min_id, max_id = await c.fetchone()

    fetch_limit = min(count * 3, 50)  # over-fetch to compensate for gaps
    random_id = random.randint(min_id, max_id)
    forward_sql = (
        f"SELECT i.id, i.source, i.source_id, i.file_path, i.url, i.created_at "
        f"FROM main_db.images i INNER JOIN labels l ON i.id = l.image_id "
        f"WHERE {where} AND i.id >= ? ORDER BY i.id LIMIT ?"
    )
    async with ldb.execute(forward_sql, params + [random_id, fetch_limit]) as c:
        candidates = await c.fetchall()

    # Wrap around if not enough candidates
    if len(candidates) < count and len(candidates) < total:
        seen_ids = {row["id"] for row in candidates}
        wrap_sql = (
            f"SELECT i.id, i.source, i.source_id, i.file_path, i.url, i.created_at "
            f"FROM main_db.images i INNER JOIN labels l ON i.id = l.image_id "
            f"WHERE {where} AND i.id < ? ORDER BY i.id LIMIT ?"
        )
        async with ldb.execute(wrap_sql, params + [random_id, fetch_limit - len(candidates)]) as c:
            wrap_rows = await c.fetchall()
        for row in wrap_rows:
            if row["id"] not in seen_ids:
                candidates.append(row)

    # Shuffle and pick requested count
    random.shuffle(candidates)
    candidates = candidates[:count]

    # Build response with vision scores
    row_ids = [r["id"] for r in candidates]
    all_scores_map = await _fetch_all_vision_scores(ldb, row_ids)
    active_db_name = state._active_model_db_name() if state._active_model else ""

    images = []
    for r in candidates:
        fp = r["file_path"]
        parts = fp.split("/")
        img_date = extract_date_from_path(fp)
        subfolder = parts[2] if len(parts) >= 3 else None
        ext = Path(fp).suffix.lower()
        is_video = ext in state.VIDEO_EXTS
        scores = all_scores_map.get(r["id"], {})
        images.append(
            {
                "id": r["id"],
                "source": r["source"],
                "source_id": r["source_id"],
                "file_path": fp,
                "url": r["url"],
                "created_at": r["created_at"],
                "date": img_date,
                "subfolder": subfolder,
                "is_video": is_video,
                "thumb_url": f"/api/thumb/{fp}" if not is_video else f"/images/{fp}",
                "vision_score": scores.get(active_db_name) if active_db_name else next(iter(scores.values()), None),
                "vision_scores": scores,
            }
        )

    return {"images": images, "total": total}


@router.get("/api/images/{image_id}")
async def get_image(image_id: int):
    db = await get_db()
    sql = "SELECT id, source, source_id, phash, file_path, url, created_at FROM images WHERE id = ?"
    async with db.execute(sql, [image_id]) as cursor:
        row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Image not found")

    fp = row["file_path"]
    ext = Path(fp).suffix.lower() if fp else ""
    parts = (fp or "").split("/")

    return {
        "id": row["id"],
        "source": row["source"],
        "source_id": row["source_id"],
        "phash": row["phash"],
        "file_path": fp,
        "url": row["url"],
        "created_at": row["created_at"],
        "date": parts[1] if len(parts) >= 2 else None,
        "subfolder": parts[2] if len(parts) >= 3 else None,
        "is_video": ext in state.VIDEO_EXTS,
        "thumb_url": f"/images/{fp}" if fp else None,
    }
