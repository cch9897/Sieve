import asyncio
import sqlite3
from typing import Optional

import httpx
import numpy as np
from fastapi import APIRouter, HTTPException, Query

import state
from config import CANDIDATES_DB_PATH
from database import get_danbooru_client, get_danbooru_labels_db
from models import _build_preference_features

router = APIRouter()


@router.get("/api/danbooru/recommended")
async def danbooru_recommended(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    min_score: float = Query(0.5, ge=0, le=1),
    rating: Optional[str] = Query(None),
):
    """Get AI-recommended Danbooru images sorted by preference score."""
    if state._preference_model is None:
        raise HTTPException(status_code=503, detail="Preference model not loaded")

    model = state._preference_model['model']
    client = get_danbooru_client()

    # Get labeled IDs to exclude
    dldb = await get_danbooru_labels_db()
    async with dldb.execute("SELECT image_id FROM labels") as c:
        labeled_ids = {r[0] for r in await c.fetchall()}

    # Fetch multiple pages from DanbooruFinder (200 images)
    all_images = []
    fetch_pages = 5
    for p in range(1, fetch_pages + 1):
        params: dict = {"page": str(p), "per_page": "40", "order_by": "random"}
        if rating:
            params["rating"] = rating
        try:
            resp = await client.get("/search", params=params)
            data = resp.json()
            results = data.get("results", [])
            all_images.extend(results)
        except httpx.HTTPError:
            continue

    # Filter out already labeled
    unlabeled = [img for img in all_images if img["id"] not in labeled_ids]

    if not unlabeled:
        return {
            "images": [],
            "total": 0,
            "page": page,
            "per_page": per_page,
            "pages": 0,
            "model_info": {
                "auc": state._preference_model.get("auc", 0),
                "n_samples": state._preference_model.get("n_samples", 0),
                "model_type": state._preference_model.get("model_type", "unknown"),
            },
        }

    # Build features and predict
    X = np.array([
        _build_preference_features(img.get("tags", ""), img.get("rating", ""), state._preference_model)
        for img in unlabeled
    ])
    probas = model.predict_proba(X)[:, 1]

    # Combine and filter by min_score
    scored = []
    for img, prob in zip(unlabeled, probas):
        if prob >= min_score:
            ext = img.get("ext", "jpg")
            is_video = ext in ("mp4", "webm", "zip")
            scored.append({
                "id": img["id"],
                "ext": ext,
                "score": img.get("score", 0),
                "rating": img.get("rating", ""),
                "danbooru_tags": img.get("tags", ""),
                "is_video": is_video,
                "thumb_url": f"/api/danbooru/thumbnail/{img['id']}.{ext}",
                "preview_url": f"/api/danbooru/preview/{img['id']}.{ext}",
                "video_url": f"/api/danbooru/video_preview/{img['id']}.{ext}" if is_video else None,
                "verdict": "",
                "updated_at": "",
                "tags": [],
                "preference_score": float(prob),
            })

    # Sort by preference score descending
    scored.sort(key=lambda x: x["preference_score"], reverse=True)

    # Paginate
    total = len(scored)
    pages_total = (total + per_page - 1) // per_page if total > 0 else 0
    offset = (page - 1) * per_page
    page_items = scored[offset:offset + per_page]

    return {
        "images": page_items,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": pages_total,
        "model_info": {
            "auc": state._preference_model.get("auc", 0),
            "n_samples": state._preference_model.get("n_samples", 0),
            "model_type": state._preference_model.get("model_type", "unknown"),
        },
    }


# CANDIDATES_DB_PATH is imported from config


@router.get("/api/danbooru/candidates/stats")
async def danbooru_candidates_stats():
    """Get AI pre-screening candidate statistics."""
    if not CANDIDATES_DB_PATH.exists():
        return {
            "total": 0, "pending": 0, "labeled": 0,
            "score_distribution": {},
            "rating_distribution": {},
            "model_loaded": state._preference_model is not None,
        }

    loop = asyncio.get_event_loop()

    def _query():
        conn = sqlite3.connect(str(CANDIDATES_DB_PATH), timeout=30)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM candidates")
        total = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM candidates WHERE status='pending'")
        pending = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM candidates WHERE status='labeled'")
        labeled = cur.fetchone()[0]

        # Score distribution (buckets)
        score_dist = {}
        for lo, hi, label in [(0.9, 1.01, "90-100%"), (0.8, 0.9, "80-90%"),
                               (0.7, 0.8, "70-80%"), (0.6, 0.7, "60-70%"),
                               (0.5, 0.6, "50-60%"), (0.0, 0.5, "<50%")]:
            cur.execute("SELECT COUNT(*) FROM candidates WHERE preference_score >= ? AND preference_score < ?", (lo, hi))
            cnt = cur.fetchone()[0]
            if cnt > 0:
                score_dist[label] = cnt

        # Rating distribution
        cur.execute("SELECT rating, COUNT(*) FROM candidates GROUP BY rating ORDER BY COUNT(*) DESC")
        rating_dist = {r[0]: r[1] for r in cur.fetchall()}

        # Average score
        cur.execute("SELECT AVG(preference_score) FROM candidates")
        avg = cur.fetchone()[0] or 0

        # Top score
        cur.execute("SELECT MAX(preference_score) FROM candidates")
        top = cur.fetchone()[0] or 0

        # Fine-grained histogram (40 bins from 0 to 1) + confidence interval
        # Use score_log (all scored images) if available, fallback to candidates only
        import math as _math
        num_bins = 40
        bin_width = 1.0 / num_bins

        has_score_log = False
        try:
            cur.execute("SELECT COUNT(*) FROM score_log")
            score_log_count = cur.fetchone()[0]
            has_score_log = score_log_count > 0
        except Exception:
            pass

        if has_score_log:
            cur.execute("SELECT fused_score, accepted FROM score_log WHERE fused_score IS NOT NULL")
            all_rows = cur.fetchall()
            all_scores = [r[0] for r in all_rows]
            accepted_scores = [r[0] for r in all_rows if r[1] == 1]
            rejected_scores = [r[0] for r in all_rows if r[1] == 0]
        else:
            cur.execute("SELECT preference_score FROM candidates WHERE preference_score IS NOT NULL")
            all_scores = [r[0] for r in cur.fetchall()]
            accepted_scores = all_scores
            rejected_scores = []

        n = len(all_scores)

        # Build histogram with accepted/rejected split
        bin_accepted = [0] * num_bins
        bin_rejected = [0] * num_bins
        for s in accepted_scores:
            idx = min(int(s / bin_width), num_bins - 1)
            bin_accepted[idx] += 1
        for s in rejected_scores:
            idx = min(int(s / bin_width), num_bins - 1)
            bin_rejected[idx] += 1

        histogram_bins = []
        for i in range(num_bins):
            lo = round(i * bin_width, 4)
            hi = round((i + 1) * bin_width, 4)
            histogram_bins.append({
                "lo": lo, "hi": hi,
                "count": bin_accepted[i] + bin_rejected[i],
                "accepted": bin_accepted[i],
                "rejected": bin_rejected[i],
            })

        # Stats for confidence interval
        ci_stats = {}
        if n > 1:
            mean = sum(all_scores) / n
            variance = sum((s - mean) ** 2 for s in all_scores) / (n - 1)
            std = _math.sqrt(variance)
            se = std / _math.sqrt(n)
            z95 = 1.96
            sorted_scores = sorted(all_scores)
            ci_stats = {
                "mean": round(mean, 4),
                "std": round(std, 4),
                "ci95_lo": round(max(mean - z95 * se, 0), 4),
                "ci95_hi": round(min(mean + z95 * se, 1), 4),
                "median": round(sorted_scores[n // 2], 4),
                "p25": round(sorted_scores[n // 4], 4),
                "p75": round(sorted_scores[3 * n // 4], 4),
                "p10": round(sorted_scores[n // 10], 4),
                "p90": round(sorted_scores[9 * n // 10], 4),
                "n": n,
            }
        elif n == 1:
            ci_stats = {"mean": round(all_scores[0], 4), "std": 0, "ci95_lo": round(all_scores[0], 4), "ci95_hi": round(all_scores[0], 4), "median": round(all_scores[0], 4), "p25": round(all_scores[0], 4), "p75": round(all_scores[0], 4), "p10": round(all_scores[0], 4), "p90": round(all_scores[0], 4), "n": 1}

        conn.close()
        return {
            "total": total, "pending": pending, "labeled": labeled,
            "score_distribution": score_dist,
            "rating_distribution": rating_dist,
            "avg_score": round(avg, 4),
            "top_score": round(top, 4),
            "histogram": histogram_bins,
            "ci_stats": ci_stats,
            "score_log_total": len(all_scores),
            "score_log_accepted": len(accepted_scores),
            "score_log_rejected": len(rejected_scores),
            "model_loaded": state._preference_model is not None,
            "model_auc": state._preference_model.get("auc", 0) if state._preference_model else 0,
            "model_samples": state._preference_model.get("n_samples", 0) if state._preference_model else 0,
            "cnn_loaded": bool(state._models),
            "cnn_auc": state._models[state._active_model].get('cv_auc', 0) if state._active_model and state._active_model in state._models else 0,
            "active_model": state._active_model,
            "vision_models": {
                k: {
                    "model_class": v.get("model_class", ""),
                    "cv_auc": v.get("cv_auc", 0),
                    "type": v.get("type", ""),
                }
                for k, v in state._models.items()
            },
        }

    return await loop.run_in_executor(None, _query)
