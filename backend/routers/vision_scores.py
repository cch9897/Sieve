from typing import Optional

from fastapi import APIRouter, Query

from database import get_labels_db_async

router = APIRouter()


@router.get("/api/vision-scores/stats")
async def vision_scores_stats(model: Optional[str] = Query(None)):
    """Get vision scoring statistics. ?model=xxx for specific model, omit for all."""
    ldb = await get_labels_db_async()

    async def _stats_for(where_clause: str, params: list):
        async with ldb.execute(f"SELECT COUNT(*) FROM vision_scores WHERE {where_clause}", params) as c:
            total = (await c.fetchone())[0]
        async with ldb.execute(f"SELECT AVG(score), MIN(score), MAX(score) FROM vision_scores WHERE {where_clause}", params) as c:
            row = await c.fetchone()
            avg_score, min_score, max_score = row[0], row[1], row[2]
        buckets = {}
        for lo in range(0, 10):
            lo_f, hi_f = lo / 10, (lo + 1) / 10
            async with ldb.execute(
                f"SELECT COUNT(*) FROM vision_scores WHERE {where_clause} AND score >= ? AND score < ?",
                params + [lo_f, hi_f if lo < 9 else 1.01]
            ) as c:
                buckets[f"{lo_f:.1f}-{hi_f:.1f}"] = (await c.fetchone())[0]
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

    # Return stats per model
    async with ldb.execute("SELECT DISTINCT model_name FROM vision_scores") as c:
        model_names = [r[0] for r in await c.fetchall()]

    if not model_names:
        return {"total_scored": 0, "models": {}, "model_name": None, "distribution": {}}

    models_stats = {}
    for mn in model_names:
        models_stats[mn] = await _stats_for("model_name = ?", [mn])

    # Also return combined stats for backward compat
    combined = await _stats_for("1=1", [])
    combined["model_name"] = model_names[0] if len(model_names) == 1 else None
    combined["models"] = models_stats
    return combined


@router.get("/api/vision-scores/compare")
async def vision_scores_compare(image_id: int = Query(...)):
    """Return all model scores for a specific image."""
    ldb = await get_labels_db_async()
    async with ldb.execute(
        "SELECT model_name, score, scored_at FROM vision_scores WHERE image_id = ?",
        [image_id]
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
    async with ldb.execute("SELECT DISTINCT model_name FROM vision_scores") as c:
        model_names = [r[0] for r in await c.fetchall()]

    result = {}
    for mn in model_names:
        async with ldb.execute(
            "SELECT COUNT(*), AVG(score), MIN(score), MAX(score) FROM vision_scores WHERE model_name = ?",
            [mn]
        ) as c:
            row = await c.fetchone()
        result[mn] = {
            "total": row[0],
            "avg_score": round(row[1], 4) if row[1] else None,
            "min_score": round(row[2], 4) if row[2] else None,
            "max_score": round(row[3], 4) if row[3] else None,
        }
    return {"models": result}
