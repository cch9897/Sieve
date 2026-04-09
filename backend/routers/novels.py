import asyncio
from functools import partial
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from database import get_db
from utils import _read_novel_meta, extract_date_from_path

router = APIRouter()


@router.get("/api/novels")
async def list_novels(
    date: Optional[str] = Query(None),
    sort: str = Query("newest", pattern="^(newest|oldest|bookmarks|views|length)$"),
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(30, ge=1, le=100),
):
    """List novels with filtering, sorting and search."""
    db = await get_db()
    conditions = ["file_path IS NOT NULL"]
    params: list = []

    if date:
        conditions.append("file_path LIKE ?")
        params.append(f"%/{date}/%")

    if search:
        conditions.append("(title LIKE ? OR author LIKE ?)")
        params.append(f"%{search}%")
        params.append(f"%{search}%")

    where = " AND ".join(conditions)

    count_sql = f"SELECT COUNT(*) FROM novels WHERE {where}"

    needs_meta_sort = sort in ("bookmarks", "views", "length")

    if needs_meta_sort:
        order = "created_at DESC"
    else:
        order_map = {
            "newest": "created_at DESC",
            "oldest": "created_at ASC",
        }
        order = order_map.get(sort, "created_at DESC")

    offset = (page - 1) * per_page

    if needs_meta_sort:
        sql = f"""SELECT id, source, source_id, title, author, file_path, url, created_at
                  FROM novels WHERE {where} ORDER BY {order}"""
        async with db.execute(count_sql, params) as count_cursor, db.execute(sql, params) as list_cursor:
            total_row, rows = await count_cursor.fetchone(), await list_cursor.fetchall()
            total = total_row[0]

        loop = asyncio.get_running_loop()
        file_paths = [r["file_path"] for r in rows]
        metas = await loop.run_in_executor(None, lambda: [_read_novel_meta(fp) for fp in file_paths])

        novels = []
        for r, meta in zip(rows, metas):
            fp = r["file_path"]
            novel_date = extract_date_from_path(fp)

            novels.append({
                "id": r["id"],
                "source": r["source"],
                "source_id": r["source_id"],
                "title": r["title"] or meta.get("title", ""),
                "author": r["author"] or meta.get("author", ""),
                "date": novel_date,
                "url": r["url"],
                "created_at": r["created_at"],
                "text_length": meta.get("text_length", 0),
                "total_bookmarks": meta.get("total_bookmarks", 0),
                "total_view": meta.get("total_view", 0),
                "tags": meta.get("tags", []),
                "series_title": meta.get("series_title"),
                "r18": meta.get("r18", False),
            })

        if sort == "bookmarks":
            novels.sort(key=lambda n: n["total_bookmarks"], reverse=True)
        elif sort == "views":
            novels.sort(key=lambda n: n["total_view"], reverse=True)
        elif sort == "length":
            novels.sort(key=lambda n: n["text_length"], reverse=True)

        novels = novels[offset:offset + per_page]
    else:
        sql = f"""SELECT id, source, source_id, title, author, file_path, url, created_at
                  FROM novels WHERE {where} ORDER BY {order} LIMIT ? OFFSET ?"""
        async with db.execute(count_sql, params) as count_cursor, db.execute(sql, params + [per_page, offset]) as list_cursor:
            total_row, rows = await count_cursor.fetchone(), await list_cursor.fetchall()
            total = total_row[0]

        loop = asyncio.get_running_loop()
        file_paths = [r["file_path"] for r in rows]
        metas = await loop.run_in_executor(None, lambda: [_read_novel_meta(fp) for fp in file_paths])

        novels = []
        for r, meta in zip(rows, metas):
            fp = r["file_path"]
            novel_date = extract_date_from_path(fp)

            novels.append({
                "id": r["id"],
                "source": r["source"],
                "source_id": r["source_id"],
                "title": r["title"] or meta.get("title", ""),
                "author": r["author"] or meta.get("author", ""),
                "date": novel_date,
                "url": r["url"],
                "created_at": r["created_at"],
                "text_length": meta.get("text_length", 0),
                "total_bookmarks": meta.get("total_bookmarks", 0),
                "total_view": meta.get("total_view", 0),
                "tags": meta.get("tags", []),
                "series_title": meta.get("series_title"),
                "r18": meta.get("r18", False),
            })

    return {
        "novels": novels,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page if total > 0 else 0,
    }


@router.get("/api/novels/dates")
async def get_novel_dates():
    db = await get_db()
    async with db.execute("SELECT DISTINCT file_path FROM novels WHERE file_path IS NOT NULL") as c:
        rows = await c.fetchall()

    dates = set()
    for r in rows:
        d = extract_date_from_path(r[0])
        if d:
            dates.add(d)

    return {"dates": sorted(dates, reverse=True)}


@router.get("/api/novels/{novel_id}")
async def get_novel(novel_id: int):
    """Get novel detail including full text."""
    db = await get_db()
    sql = "SELECT id, source, source_id, title, author, file_path, url, created_at FROM novels WHERE id = ?"
    async with db.execute(sql, [novel_id]) as cursor:
        row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Novel not found")

    fp = row["file_path"]
    loop = asyncio.get_running_loop()
    meta = await loop.run_in_executor(None, partial(_read_novel_meta, fp, include_text=True))

    return {
        "id": row["id"],
        "source": row["source"],
        "source_id": row["source_id"],
        "title": row["title"] or meta.get("title", ""),
        "author": row["author"] or meta.get("author", ""),
        "url": row["url"],
        "created_at": row["created_at"],
        "text": meta.get("text", ""),
        "text_length": meta.get("text_length", 0),
        "total_bookmarks": meta.get("total_bookmarks", 0),
        "total_view": meta.get("total_view", 0),
        "tags": meta.get("tags", []),
        "series_title": meta.get("series_title"),
        "series_id": meta.get("series_id"),
        "caption": meta.get("caption", ""),
        "r18": meta.get("r18", False),
    }
