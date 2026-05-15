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
from services.danbooru_candidates_repo import DanbooruCandidatesRepo

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

    model = state._preference_model["model"]
    client = get_danbooru_client()

    # Fetch multiple pages from DanbooruFinder in parallel (200 images)
    fetch_pages = 5

    async def _fetch_page(p: int) -> list:
        req_params: dict = {"page": str(p), "per_page": "40", "order_by": "random"}
        if rating:
            req_params["rating"] = rating
        try:
            resp = await client.get("/search", params=req_params)
            return resp.json().get("results", [])
        except httpx.HTTPError:
            return []

    page_results = await asyncio.gather(*[_fetch_page(p) for p in range(1, fetch_pages + 1)])
    all_images = [img for results in page_results for img in results]

    # Check only fetched IDs against labels (not ALL labeled IDs)
    dldb = await get_danbooru_labels_db()
    candidate_ids = [img["id"] for img in all_images]
    if candidate_ids:
        placeholders = ",".join("?" * len(candidate_ids))
        async with dldb.execute(f"SELECT image_id FROM labels WHERE image_id IN ({placeholders})", candidate_ids) as c:
            labeled_ids = {r[0] for r in await c.fetchall()}
    else:
        labeled_ids = set()

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

    # Build features and predict (CPU-bound, run in thread)
    def _predict():
        X = np.array(
            [
                _build_preference_features(img.get("tags", ""), img.get("rating", ""), state._preference_model)
                for img in unlabeled
            ]
        )
        return model.predict_proba(X)[:, 1]

    probas = await asyncio.to_thread(_predict)

    # Combine and filter by min_score
    scored = []
    for img, prob in zip(unlabeled, probas):
        if prob >= min_score:
            ext = img.get("ext", "jpg")
            is_video = ext in ("mp4", "webm", "zip")
            scored.append(
                {
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
                }
            )

    # Sort by preference score descending
    scored.sort(key=lambda x: x["preference_score"], reverse=True)

    # Paginate
    total = len(scored)
    pages_total = (total + per_page - 1) // per_page if total > 0 else 0
    offset = (page - 1) * per_page
    page_items = scored[offset : offset + per_page]

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
            "total": 0,
            "pending": 0,
            "labeled": 0,
            "score_distribution": {},
            "rating_distribution": {},
            "model_loaded": state._preference_model is not None,
        }

    loop = asyncio.get_running_loop()

    def _query():
        conn = sqlite3.connect(str(CANDIDATES_DB_PATH), timeout=30)
        try:
            repo = DanbooruCandidatesRepo(conn)
            total = repo.count_total()
            pending = repo.count_pending()
            labeled = repo.count_labeled()
            score_dist = repo.count_by_score_bucket()
            rating_dist = repo.count_by_rating()
            avg = repo.avg_score()
            top = repo.top_score()
            all_scores, accepted_scores, rejected_scores = repo.fetch_score_log()
            histogram_bins = repo.build_histogram(accepted_scores, rejected_scores)
            ci_stats = repo.confidence_stats(all_scores)

            return {
                "total": total,
                "pending": pending,
                "labeled": labeled,
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
                "cnn_auc": state._models[state._active_model].get("cv_auc", 0)
                if state._active_model and state._active_model in state._models
                else 0,
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
        finally:
            conn.close()

    return await loop.run_in_executor(state._db_executor, _query)
