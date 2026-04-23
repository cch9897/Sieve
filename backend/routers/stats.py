from fastapi import APIRouter

from database import get_db
from utils import ttl_cache

router = APIRouter()


@router.get("/api/stats")
async def get_stats():
    return await _get_stats_cached()


@ttl_cache(seconds=30)
async def _get_stats_cached():
    db = await get_db()
    stats = {}

    async with db.execute("SELECT COUNT(*) FROM images WHERE file_path IS NOT NULL") as c:
        stats["total"] = (await c.fetchone())[0]

    async with db.execute(
        "SELECT source, COUNT(*) as cnt FROM images WHERE file_path IS NOT NULL GROUP BY source ORDER BY cnt DESC"
    ) as c:
        stats["by_source"] = {r[0]: r[1] for r in await c.fetchall()}

    async with db.execute(
        """SELECT substr(file_path, 11, 10) as date, COUNT(*) as cnt
           FROM images WHERE file_path IS NOT NULL AND file_path LIKE 'downloads/%'
           GROUP BY date ORDER BY date DESC"""
    ) as c:
        rows = await c.fetchall()
        stats["by_date"] = {r[0]: r[1] for r in rows if r[0]}

    async with db.execute(
        """SELECT substr(file_path, 11, 10) as date, source, COUNT(*) as cnt
           FROM images WHERE file_path IS NOT NULL AND file_path LIKE 'downloads/%'
           GROUP BY date, source ORDER BY date DESC"""
    ) as c:
        date_source = {}
        for r in await c.fetchall():
            d = r[0]
            if d:
                if d not in date_source:
                    date_source[d] = {}
                date_source[d][r[1]] = r[2]
        stats["by_date_source"] = date_source

    async with db.execute("SELECT COUNT(*) FROM images") as c:
        stats["total_db"] = (await c.fetchone())[0]

    try:
        async with db.execute("SELECT COUNT(*) FROM novels WHERE file_path IS NOT NULL") as c:
            stats["total_novels"] = (await c.fetchone())[0]
    except Exception:
        stats["total_novels"] = 0

    return stats


@router.get("/api/dates")
async def get_dates():
    return await _get_dates_cached()


@ttl_cache(seconds=60)
async def _get_dates_cached():
    db = await get_db()
    async with db.execute(
        """SELECT DISTINCT substr(file_path, 11, 10) as date
           FROM images WHERE file_path IS NOT NULL AND file_path LIKE 'downloads/%'
           ORDER BY date DESC"""
    ) as c:
        rows = await c.fetchall()
        return {"dates": [r[0] for r in rows if r[0]]}


@router.get("/api/sources")
async def get_sources():
    return await _get_sources_cached()


@ttl_cache(seconds=60)
async def _get_sources_cached():
    db = await get_db()
    async with db.execute(
        "SELECT source, COUNT(*) as cnt FROM images WHERE file_path IS NOT NULL GROUP BY source ORDER BY source"
    ) as c:
        rows = await c.fetchall()
        return {"sources": [r[0] for r in rows], "counts": {r[0]: r[1] for r in rows}}
