from typing import Optional

from fastapi import APIRouter, Query

from database import get_labels_db_async
from utils import ttl_cache

router = APIRouter()

_BUCKET_SQL = """
    SELECT
        CASE
            WHEN score < 0.1 THEN '0.0-0.1'
            WHEN score < 0.2 THEN '0.1-0.2'
            WHEN score < 0.3 THEN '0.2-0.3'
            WHEN score < 0.4 THEN '0.3-0.4'
            WHEN score < 0.5 THEN '0.4-0.5'
            WHEN score < 0.6 THEN '0.5-0.6'
            WHEN score < 0.7 THEN '0.6-0.7'
            WHEN score < 0.8 THEN '0.7-0.8'
            WHEN score < 0.9 THEN '0.8-0.9'
            ELSE '0.9-1.0'
        END AS bucket,
        COUNT(*) as cnt
    FROM vision_scores WHERE {where}
    GROUP BY bucket
"""


@router.get("/api/vision-scores/stats")
async def vision_scores_stats(model: Optional[str] = Query(None)):
    """Get vision scoring statistics. ?model=xxx for specific model, omit for all."""
    return await _vision_scores_stats_cached(model)


@ttl_cache(seconds=30)
async def _vision_scores_stats_cached(model: Optional[str] = None):
    ldb = await get_labels_db_async()

    async def _stats_for(where_clause: str, params: list):
        async with ldb.execute(
            f"SELECT COUNT(*), AVG(score), MIN(score), MAX(score) FROM vision_scores WHERE {where_clause}",
            params,
        ) as c:
            total, avg_score, min_score, max_score = await c.fetchone()

        raw_buckets = {}
        async with ldb.execute(_BUCKET_SQL.format(where=where_clause), params) as c:
            for r in await c.fetchall():
                raw_buckets[r[0]] = r[1]
        buckets = {
            f"{lo / 10:.1f}-{(lo + 1) / 10:.1f}": raw_buckets.get(f"{lo / 10:.1f}-{(lo + 1) / 10:.1f}", 0)
            for lo in range(10)
        }

        return {
            "total_scored": total,
            "avg_score": round(avg_score, 4) if avg_score else None,
            "min_score": round(min_score, 4) if min_score else None,
            "max_score": round(max_score, 4) if max_score else None,
            "distribution": buckets,
        }

    if model:
        stats = await _stats_for("model_name = ?", [model])
        stats["model_name"] = model
        return stats

    async with ldb.execute("SELECT DISTINCT model_name FROM vision_scores") as c:
        model_names = [r[0] for r in await c.fetchall()]

    if not model_names:
        return {"total_scored": 0, "models": {}, "model_name": None, "distribution": {}}

    # Single GROUP BY query instead of per-model loop
    models_stats = {}
    async with ldb.execute(
        "SELECT model_name, COUNT(*), AVG(score), MIN(score), MAX(score) FROM vision_scores GROUP BY model_name"
    ) as c:
        for r in await c.fetchall():
            mn = r[0]
            models_stats[mn] = {
                "total_scored": r[1],
                "avg_score": round(r[2], 4) if r[2] else None,
                "min_score": round(r[3], 4) if r[3] else None,
                "max_score": round(r[4], 4) if r[4] else None,
            }
    # Add bucket distributions per model
    for mn in model_names:
        raw_buckets = {}
        async with ldb.execute(_BUCKET_SQL.format(where="model_name = ?"), [mn]) as c:
            for r in await c.fetchall():
                raw_buckets[r[0]] = r[1]
        models_stats[mn]["distribution"] = {
            f"{lo / 10:.1f}-{(lo + 1) / 10:.1f}": raw_buckets.get(f"{lo / 10:.1f}-{(lo + 1) / 10:.1f}", 0)
            for lo in range(10)
        }

    combined = await _stats_for("1=1", [])
    combined["model_name"] = model_names[0] if len(model_names) == 1 else None
    combined["models"] = models_stats
    return combined


@router.get("/api/vision-scores/compare")
async def vision_scores_compare(image_id: int = Query(...)):
    """Return all model scores for a specific image."""
    ldb = await get_labels_db_async()
    async with ldb.execute(
        "SELECT model_name, score, scored_at FROM vision_scores WHERE image_id = ?", [image_id]
    ) as c:
        rows = await c.fetchall()
    return {
        "image_id": image_id,
        "scores": {r[0]: {"score": round(r[1], 4), "scored_at": r[2]} for r in rows},
    }


@router.get("/api/vision-scores/compare-stats")
async def vision_scores_compare_stats():
    """Return per-model statistics for comparison."""
    ldb = await get_labels_db_async()

    result = {}
    async with ldb.execute(
        "SELECT model_name, COUNT(*), AVG(score), MIN(score), MAX(score) FROM vision_scores GROUP BY model_name"
    ) as c:
        for row in await c.fetchall():
            result[row[0]] = {
                "total": row[1],
                "avg_score": round(row[2], 4) if row[2] else None,
                "min_score": round(row[3], 4) if row[3] else None,
                "max_score": round(row[4], 4) if row[4] else None,
            }
    return {"models": result}
