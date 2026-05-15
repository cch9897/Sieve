import asyncio
import logging
import re
from pathlib import Path
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

import state
from config import CANDIDATES_DB_PATH, DANBOORU_LIKES_DIR
from database import get_candidates_db, get_danbooru_client, get_danbooru_labels_db
from services import labeler_service as svc
from services.export_service import build_export_zip

logger = logging.getLogger(__name__)

_SAFE_EXT_RE = re.compile(r"^[A-Za-z0-9]{1,8}$")


def _is_safe_ext(ext: str) -> bool:
    """Reject anything that could break out of a directory or hold a separator."""
    if not ext or len(ext) > 8:
        return False
    if any(ch in ext for ch in ("/", "\\", ".")) or ".." in ext:
        return False
    return bool(_SAFE_EXT_RE.fullmatch(ext))


router = APIRouter()

# Danbooru's labels table carries the extra columns persisted on every upsert.
LABELER_CFG = svc.DANBOORU_LABELER


class DanbooruLabelRequest(BaseModel):
    verdict: str  # liked, disliked, skipped
    tags: list[str] = []
    ext: str = ""
    score: int = 0
    rating: str = ""
    danbooru_tags: str = ""  # JSON string of original danbooru tags


@router.get("/api/danbooru/labeler/next")
async def danbooru_labeler_next(
    rating: Optional[str] = Query(None),
    min_score: Optional[int] = Query(None),
    media: Optional[str] = Query(None),
):
    """Get the next unlabeled danbooru image for review."""
    dldb = await get_danbooru_labels_db()

    # Build DanbooruFinder search params
    params: dict = {"order_by": "random", "per_page": "20"}
    if rating:
        params["rating"] = rating
    if min_score is not None:
        params["min_score"] = str(min_score)

    client = get_danbooru_client()
    try:
        resp = await client.get("/search", params=params)
        data = resp.json()
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"DanbooruFinder error: {e}")

    results = data.get("results", [])
    pagination = data.get("pagination", {})

    # Count ALL labeled images (not just the 20 candidates checked above)
    async with dldb.execute("SELECT COUNT(*) FROM labels") as c:
        total_labeled = (await c.fetchone())[0]

    # Check only the candidate IDs against labels (not ALL labeled IDs)
    candidate_ids = [item["id"] for item in results]
    if candidate_ids:
        placeholders = ",".join("?" * len(candidate_ids))
        async with dldb.execute(f"SELECT image_id FROM labels WHERE image_id IN ({placeholders})", candidate_ids) as c:
            labeled_ids = {r[0] for r in await c.fetchall()}
    else:
        labeled_ids = set()

    # Filter out already labeled
    for item in results:
        if item["id"] not in labeled_ids:
            is_video = item.get("ext", "") in ("mp4", "webm", "zip")
            if media == "image" and is_video:
                continue
            if media == "video" and not is_video:
                continue
            return {
                "image": {
                    "id": item["id"],
                    "ext": item.get("ext", "jpg"),
                    "score": item.get("score", 0),
                    "rating": item.get("rating", ""),
                    "created_at": item.get("created_at", ""),
                    "file_size": item.get("file_size", 0),
                    "tags": item.get("tags", ""),
                    "tag_categories": item.get("tag_categories", {}),
                    "is_video": is_video,
                    "thumb_url": f"/api/danbooru/thumbnail/{item['id']}.{item.get('ext', 'jpg')}",
                    "preview_url": f"/api/danbooru/preview/{item['id']}.{item.get('ext', 'jpg')}",
                    "video_url": f"/api/danbooru/video_preview/{item['id']}.{item.get('ext', 'jpg')}"
                    if is_video
                    else None,
                },
                "remaining": pagination.get("total", 0),
                "total_labeled": total_labeled,
            }

    return {"image": None, "remaining": 0, "total_labeled": len(labeled_ids)}


@router.post("/api/danbooru/labeler/{image_id}")
async def danbooru_label_image(image_id: int, req: DanbooruLabelRequest):
    """Label a danbooru image as liked/disliked/skipped."""
    if req.verdict not in ("liked", "disliked", "skipped"):
        raise HTTPException(status_code=400, detail="verdict must be liked, disliked, or skipped")

    dldb = await get_danbooru_labels_db()
    await svc.apply_label(
        dldb,
        LABELER_CFG,
        image_id,
        req.verdict,
        req.tags,
        extra_values={
            "ext": req.ext,
            "score": req.score,
            "rating": req.rating,
            "tags": req.danbooru_tags,
        },
    )

    # Auto-download liked images / remove if verdict changed away from liked
    if req.verdict == "liked" and req.ext:
        _task = asyncio.create_task(_download_danbooru_liked(image_id, req.ext))
        state._add_background_task(_task)
    else:
        _task = asyncio.create_task(_remove_danbooru_liked(image_id))
        state._add_background_task(_task)

    return {"ok": True}


async def _download_danbooru_liked(image_id: int, ext: str):
    """Download original image from DanbooruFinder to local likes folder."""
    try:
        if not _is_safe_ext(ext):
            logger.warning("[danbooru_likes] Rejected unsafe ext=%r for image %d", ext, image_id)
            return
        DANBOORU_LIKES_DIR.mkdir(parents=True, exist_ok=True)
        likes_root = DANBOORU_LIKES_DIR.resolve()
        dest = (DANBOORU_LIKES_DIR / f"{image_id}.{ext}").resolve()
        if not dest.is_relative_to(likes_root):
            logger.warning("[danbooru_likes] Rejected escape ext=%r for image %d", ext, image_id)
            return
        if dest.exists():
            return
        client = get_danbooru_client()
        resp = await client.get(f"/original/{image_id}.{ext}", follow_redirects=True, timeout=60.0)
        if resp.status_code == 200:
            await asyncio.to_thread(dest.write_bytes, resp.content)
        elif resp.status_code == 404:
            resp2 = await client.get(f"/preview/{image_id}.{ext}", timeout=30.0)
            if resp2.status_code == 200:
                await asyncio.to_thread(dest.write_bytes, resp2.content)
    except Exception as e:
        logger.warning("[danbooru_likes] Failed to download %d.%s: %s", image_id, ext, e)


async def _remove_danbooru_liked(image_id: int):
    """Remove a previously downloaded liked image (on unlabel or verdict change)."""
    try:
        if not DANBOORU_LIKES_DIR.exists():
            return
        for f in DANBOORU_LIKES_DIR.glob(f"{image_id}.*"):
            f.unlink()
    except Exception as e:
        logger.warning("[danbooru_likes] Failed to remove %d: %s", image_id, e)


@router.delete("/api/danbooru/labeler/{image_id}")
async def danbooru_unlabel_image(image_id: int):
    """Remove label for a danbooru image (undo)."""
    dldb = await get_danbooru_labels_db()
    # Remove local file if it was liked
    _task = asyncio.create_task(_remove_danbooru_liked(image_id))
    state._add_background_task(_task)
    await svc.remove_label(dldb, LABELER_CFG, image_id)
    return {"ok": True}


@router.get("/api/danbooru/labeler/stats")
async def danbooru_labeler_stats():
    """Get danbooru labeling statistics."""
    dldb = await get_danbooru_labels_db()

    counts = await svc.fetch_verdict_counts(dldb, LABELER_CFG)
    stats: dict = {
        "total_images": 0,
        "liked": counts["liked"],
        "disliked": counts["disliked"],
        "skipped": counts["skipped"],
        "total_labeled": counts["total_labeled"],
    }

    # Get total from DanbooruFinder
    client = get_danbooru_client()
    try:
        resp = await client.get("/search", params={"per_page": "1"})
        data = resp.json()
        stats["total_images"] = data.get("pagination", {}).get("total", 0)
    except httpx.HTTPError:
        pass

    stats["remaining"] = stats["total_images"] - stats["total_labeled"]
    stats["top_tags"] = await svc.fetch_top_user_tags(dldb, LABELER_CFG, limit=50)

    # --- Rating distribution (all labeled) ---
    rating_dist: dict[str, dict[str, int]] = {}
    async with dldb.execute(
        "SELECT rating, verdict, COUNT(*) FROM labels WHERE rating IS NOT NULL GROUP BY rating, verdict"
    ) as c:
        for r in await c.fetchall():
            rat, verd, cnt = r[0], r[1], r[2]
            if rat not in rating_dist:
                rating_dist[rat] = {}
            rating_dist[rat][verd] = cnt
    stats["rating_distribution"] = rating_dist

    # --- Liked: rating breakdown ---
    liked_by_rating: dict[str, int] = {}
    async with dldb.execute(
        "SELECT rating, COUNT(*) FROM labels WHERE verdict = 'liked' AND rating IS NOT NULL GROUP BY rating"
    ) as c:
        for r in await c.fetchall():
            liked_by_rating[r[0]] = r[1]
    stats["liked_by_rating"] = dict(sorted(liked_by_rating.items(), key=lambda x: x[1], reverse=True))

    # --- Labeled by rating (liked+disliked) for like-rate ---
    labeled_by_rating: dict[str, int] = {}
    async with dldb.execute(
        "SELECT rating, COUNT(*) FROM labels WHERE verdict IN ('liked', 'disliked') AND rating IS NOT NULL GROUP BY rating"
    ) as c:
        for r in await c.fetchall():
            labeled_by_rating[r[0]] = r[1]
    stats["labeled_by_rating"] = labeled_by_rating

    # --- Top danbooru tags from liked images ---
    liked_tag_counts: dict[str, int] = {}
    async with dldb.execute("SELECT tags FROM labels WHERE verdict = 'liked' AND tags IS NOT NULL AND tags != ''") as c:
        for r in await c.fetchall():
            # Tags may be space-separated or comma-separated
            raw = r[0].replace(",", " ")
            for tag in raw.split():
                tag = tag.strip().strip(",")
                if tag:
                    liked_tag_counts[tag] = liked_tag_counts.get(tag, 0) + 1
    top_liked = sorted(liked_tag_counts.items(), key=lambda x: x[1], reverse=True)[:30]
    stats["liked_top_danbooru_tags"] = [{"tag": t, "count": c} for t, c in top_liked]

    return stats


@router.get("/api/danbooru/labeler/history")
async def danbooru_labeler_history(
    verdict: Optional[str] = Query(None, pattern="^(liked|disliked|skipped)$"),
    tag: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(60, ge=1, le=200),
):
    """Get danbooru labeled images history."""
    dldb = await get_danbooru_labels_db()

    total, label_rows = await svc.fetch_history_page(
        dldb,
        LABELER_CFG,
        select_columns="l.image_id, l.verdict, l.ext, l.score, l.rating, l.tags, l.updated_at",
        verdict=verdict,
        tag=tag,
        page=page,
        per_page=per_page,
    )

    if not label_rows:
        return {"images": [], "total": total, "page": page, "per_page": per_page, "pages": 0}

    image_ids = [r[0] for r in label_rows]

    tags_map = await svc.fetch_user_tags_map(dldb, LABELER_CFG, image_ids)

    # Fetch vision scores from candidates.db (pooled via database.get_candidates_db).
    placeholders = ",".join("?" * len(image_ids))
    vision_map: dict[int, float] = {}
    try:
        cdb = await get_candidates_db()
        async with cdb.execute(
            f"SELECT image_id, cnn_score FROM candidates WHERE image_id IN ({placeholders}) AND cnn_score IS NOT NULL",
            image_ids,
        ) as vc:
            async for vrow in vc:
                vision_map[vrow[0]] = round(vrow[1], 4)
    except FileNotFoundError:
        # candidates.db not yet built (no prefetch run); not an error — just no scores.
        logger.info("vision_score lookup skipped: candidates.db missing at %s", CANDIDATES_DB_PATH)
    except Exception as e:
        logger.warning(
            "Failed to fetch vision_scores for %d image_ids (first=%s): %s",
            len(image_ids),
            image_ids[0] if image_ids else None,
            e,
        )

    images = []
    for r in label_rows:
        img_id = r[0]
        ext = r[2] or "jpg"
        is_video = ext in ("mp4", "webm", "zip")
        danbooru_tags_raw = r[5]
        try:
            danbooru_tags = danbooru_tags_raw if danbooru_tags_raw else ""
        except Exception:
            danbooru_tags = ""

        images.append(
            {
                "id": img_id,
                "ext": ext,
                "score": r[3] or 0,
                "rating": r[4] or "",
                "danbooru_tags": danbooru_tags,
                "is_video": is_video,
                "thumb_url": f"/api/danbooru/thumbnail/{img_id}.{ext}",
                "preview_url": f"/api/danbooru/preview/{img_id}.{ext}",
                "video_url": f"/api/danbooru/video_preview/{img_id}.{ext}" if is_video else None,
                "verdict": r[1],
                "updated_at": r[6],
                "tags": tags_map.get(img_id, []),
                "vision_score": vision_map.get(img_id),
            }
        )

    return {
        "images": images,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page if total > 0 else 0,
    }


@router.get("/api/danbooru/labeler/export")
async def danbooru_export_liked(
    verdict: str = Query("liked", pattern="^(liked|disliked|skipped)$"),
    tag: Optional[str] = Query(None),
    max_size: int = Query(1024, ge=0, le=4096, description="Max dimension in pixels"),
):
    """Export danbooru labeled images as a ZIP archive.

    Liked: read from local DANBOORU_LIKES_DIR (fast, no network).
    Disliked/skipped: fetch from DanbooruFinder API then resize.
    All images resized to max_size. ZIP streamed via temp file.
    """
    dldb = await get_danbooru_labels_db()

    rows = await svc.fetch_export_targets(
        dldb,
        LABELER_CFG,
        select_columns="l.image_id, l.ext, l.score, l.rating, l.tags",
        verdict=verdict,
        tag=tag,
    )

    if not rows:
        raise HTTPException(status_code=404, detail="No images found for export")

    image_ids = [r[0] for r in rows]
    tags_map = await svc.fetch_user_tags_map(dldb, LABELER_CFG, image_ids)

    local_dir = DANBOORU_LIKES_DIR if verdict == "liked" else None
    local_root = local_dir.resolve() if local_dir else None

    # Phase 1: resolve image sources -> list of (img_id, ext, score, rating, danbooru_tags, local_path|None).
    # For items without a local file, schedule an HTTP fetch.
    items: list[tuple] = []
    need_download: list[tuple[int, int, str]] = []  # (index_in_items, img_id, ext)

    for r in rows:
        img_id, ext = r[0], r[1] or "jpg"
        if not _is_safe_ext(ext):
            ext = "jpg"
        local_path = None
        if local_dir and local_root is not None:
            lp = (local_dir / f"{img_id}.{ext}").resolve()
            if lp.is_relative_to(local_root) and lp.exists():
                local_path = str(lp)
        items.append((img_id, ext, r[2], r[3], r[4], local_path))
        if local_path is None:
            need_download.append((len(items) - 1, img_id, ext))

    # Phase 2: async download missing images (concurrency-limited)
    downloaded: dict[int, bytes] = {}  # index -> bytes
    if need_download:
        client = get_danbooru_client()
        sem = asyncio.Semaphore(10)

        async def _fetch(idx: int, img_id: int, ext: str):
            async with sem:
                try:
                    resp = await client.get(f"/preview/{img_id}.{ext}", timeout=30.0)
                    if resp.status_code == 200:
                        downloaded[idx] = resp.content
                except Exception:
                    pass

        await asyncio.gather(*[_fetch(i, iid, e) for i, iid, e in need_download])

    # Phase 3: build ZIP via the shared helper (CPU-bound resize on the I/O executor).
    tags_snap = dict(tags_map)
    downloaded_snap = dict(downloaded)
    indexed_items = list(enumerate(items))

    def _fetch_bytes(entry: tuple) -> tuple[bytes | None, str]:
        idx, (_img_id, ext, _score, _rating, _dtags, local_p) = entry
        if local_p:
            try:
                return Path(local_p).read_bytes(), ext or "jpg"
            except OSError:
                pass
        raw = downloaded_snap.get(idx)
        return raw, ext or "jpg"

    def _arcname(entry: tuple, out_ext: str) -> str:
        _idx, (img_id, _ext, _s, _r, _t, _lp) = entry
        return f"images/{img_id}.{out_ext}"

    def _meta(entry: tuple, arcname: str, out_ext: str) -> dict:
        _idx, (img_id, ext, score, rating, dtags, _lp) = entry
        return {
            "id": img_id,
            "ext": out_ext,
            "original_ext": ext,
            "score": score,
            "rating": rating,
            "danbooru_tags": dtags,
            "user_tags": tags_snap.get(img_id, []),
            "filename": Path(arcname).name,
        }

    tag_suffix = f"_{tag}" if tag else ""
    placeholder_name = f"danbooru_{verdict}{tag_suffix}_PLACEHOLDER.zip"

    response, packed, skipped = await build_export_zip(
        indexed_items,
        max_size=max_size,
        fetch_bytes=_fetch_bytes,
        arcname_fn=_arcname,
        meta_fn=_meta,
        download_filename=placeholder_name,
        rename_after=lambda p, _s: f"danbooru_{verdict}{tag_suffix}_{p}imgs.zip",
    )

    if packed == 0:
        await response.body_iterator.aclose()
        raise HTTPException(status_code=404, detail="No image files could be loaded")

    if skipped > 0:
        logger.info("[danbooru_export] %s: packed %d, skipped %d", verdict, packed, skipped)

    return response
