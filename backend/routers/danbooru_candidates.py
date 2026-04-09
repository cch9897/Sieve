import asyncio
import sqlite3
from typing import Optional

from fastapi import APIRouter, Query

from config import CANDIDATES_DB_PATH
from database import get_danbooru_labels_db

router = APIRouter()


@router.get("/api/danbooru/candidates/next")
async def danbooru_candidates_next(
    rating: Optional[str] = Query(None),
    media: Optional[str] = Query(None),
    min_score: float = Query(0.0, ge=0, le=1),
    min_aes: Optional[float] = Query(None, ge=0, le=1),
):
    """Get next AI-recommended candidate for review (highest score first)."""
    if not CANDIDATES_DB_PATH.exists():
        return {"image": None, "remaining": 0, "total_labeled": 0}

    dldb = await get_danbooru_labels_db()
    async with dldb.execute("SELECT image_id FROM labels") as c:
        labeled_ids = {r[0] for r in await c.fetchall()}

    loop = asyncio.get_event_loop()

    # Convert labeled_ids to a frozenset for the closure
    _labeled_ids = frozenset(labeled_ids)

    def _query():
        conn = sqlite3.connect(str(CANDIDATES_DB_PATH), timeout=30)
        cur = conn.cursor()

        # Build query — filter media type and already-labeled at SQL level
        where = ["status = 'pending'"]
        params_list: list = []

        if min_score > 0:
            where.append("preference_score >= ?")
            params_list.append(min_score)
        if min_aes is not None:
            where.append("cnn_score IS NOT NULL AND cnn_score >= ?")
            params_list.append(min_aes)
        if rating:
            where.append("rating = ?")
            params_list.append(rating)
        if media == "image":
            where.append("ext NOT IN ('mp4', 'webm', 'zip')")
        elif media == "video":
            where.append("ext IN ('mp4', 'webm', 'zip')")

        # Exclude already-labeled ids
        if _labeled_ids:
            placeholders = ",".join("?" * len(_labeled_ids))
            where.append(f"image_id NOT IN ({placeholders})")
            params_list.extend(_labeled_ids)

        where_str = " AND ".join(where)
        cur.execute(f"SELECT image_id, ext, score, rating, tags, preference_score, tag_score, cnn_score FROM candidates WHERE {where_str} ORDER BY preference_score DESC LIMIT 1", params_list)
        row = cur.fetchone()

        # Count remaining
        cur.execute(f"SELECT COUNT(*) FROM candidates WHERE {where_str}", params_list)
        remaining = cur.fetchone()[0]

        conn.close()
        return row, remaining

    row, remaining = await loop.run_in_executor(None, _query)

    if row:
        img_id, ext, score, img_rating, tags_str, pref_score, tag_sc, cnn_sc = row
        is_video = ext in ("mp4", "webm", "zip")

        # Parse tag_categories from DanbooruFinder if needed
        tag_list = [t.strip().strip(',') for t in (tags_str or "").split() if t.strip()]
        tag_categories = {"general": tag_list}

        return {
            "image": {
                "id": img_id,
                "ext": ext or "jpg",
                "score": score or 0,
                "rating": img_rating or "",
                "created_at": "",
                "file_size": 0,
                "tags": tags_str or "",
                "tag_categories": tag_categories,
                "is_video": is_video,
                "thumb_url": f"/api/danbooru/thumbnail/{img_id}.{ext or 'jpg'}",
                "preview_url": f"/api/danbooru/preview/{img_id}.{ext or 'jpg'}",
                "video_url": f"/api/danbooru/video_preview/{img_id}.{ext or 'jpg'}" if is_video else None,
                "preference_score": float(pref_score),
                "tag_score": float(tag_sc) if tag_sc is not None else None,
                "aesthetic_score": float(cnn_sc) if cnn_sc is not None else None,
            },
            "remaining": remaining,
            "total_labeled": len(labeled_ids),
        }

    return {"image": None, "remaining": 0, "total_labeled": len(labeled_ids)}


@router.post("/api/danbooru/candidates/{image_id}/mark")
async def danbooru_candidates_mark(image_id: int):
    """Mark a candidate as labeled after the user reviews it."""
    if not CANDIDATES_DB_PATH.exists():
        return {"ok": True}
    loop = asyncio.get_event_loop()
    def _mark():
        conn = sqlite3.connect(str(CANDIDATES_DB_PATH), timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("UPDATE candidates SET status='labeled' WHERE image_id=?", (image_id,))
        conn.commit()
        conn.close()
    await loop.run_in_executor(None, _mark)
    return {"ok": True}


@router.post("/api/danbooru/candidates/clear")
async def danbooru_candidates_clear():
    """Clear all AI pre-screening candidates and reset scan position."""
    if not CANDIDATES_DB_PATH.exists():
        return {"ok": True, "deleted": 0}
    loop = asyncio.get_event_loop()
    def _clear():
        conn = sqlite3.connect(str(CANDIDATES_DB_PATH), timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        count = conn.execute("SELECT COUNT(*) FROM candidates").fetchone()[0]
        conn.execute("DELETE FROM candidates")
        conn.execute("CREATE TABLE IF NOT EXISTS scan_state (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute("DELETE FROM scan_state")
        # Also clear score_log so histogram resets
        try:
            conn.execute("DELETE FROM score_log")
        except sqlite3.OperationalError:
            pass  # table may not exist
        conn.commit()
        conn.close()
        return count
    deleted = await loop.run_in_executor(None, _clear)
    return {"ok": True, "deleted": deleted}
