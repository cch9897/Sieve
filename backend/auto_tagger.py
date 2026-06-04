#!/usr/bin/env python3
"""
Incremental auto-tagger using imgutils WD14.

Usage:
    python auto_tagger.py [--batch N] [--sleep S] [--threshold T]

Designed to run periodically via cron/systemd timer.
Low resource usage: processes one image at a time, sleeps between images,
limits batch size per run.
"""

import argparse
import gc
import json
import logging
import os
import sqlite3
import time
from pathlib import Path

# Limit threads for ONNX/numpy to avoid CPU hogging
os.environ.setdefault("OMP_NUM_THREADS", "4")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "4")
os.environ.setdefault("MKL_NUM_THREADS", "4")
os.environ.setdefault("ONNXRUNTIME_NUM_THREADS", "4")

import state as _state
from config import CRAWLER_DIR, DB_PATH, LABELS_DB_PATH

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("auto_tagger")

IMAGE_EXTS = _state.IMAGE_EXTS

# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def init_auto_tags_table(labels_db: str):
    """Create auto_tags table if not exists."""
    conn = sqlite3.connect(str(labels_db))
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS auto_tags (
                image_id INTEGER PRIMARY KEY,
                rating_json TEXT NOT NULL,
                general_json TEXT NOT NULL,
                character_json TEXT NOT NULL,
                top_tags TEXT NOT NULL,
                model_name TEXT NOT NULL DEFAULT 'SwinV2_v3',
                general_threshold REAL NOT NULL DEFAULT 0.35,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_auto_tags_created ON auto_tags(created_at)")
        conn.commit()
    finally:
        conn.close()
    log.info("auto_tags table ready")


def get_untagged_image_ids(dedup_db: str, labels_db: str, limit: int) -> list[tuple[int, str]]:
    """Get image IDs that haven't been auto-tagged yet. Returns [(id, file_path), ...]."""
    # Read already-tagged IDs from labels DB
    lconn = sqlite3.connect(str(labels_db))
    try:
        tagged_ids = {r[0] for r in lconn.execute("SELECT image_id FROM auto_tags").fetchall()}
    finally:
        lconn.close()

    # Read candidate images from dedup DB (read-only)
    dconn = sqlite3.connect(f"file:{dedup_db}?mode=ro", uri=True)
    try:
        dconn.row_factory = sqlite3.Row
        rows = dconn.execute("SELECT id, file_path FROM images WHERE file_path IS NOT NULL ORDER BY id").fetchall()
    finally:
        dconn.close()

    candidates = []
    for r in rows:
        if r["id"] in tagged_ids:
            continue
        fp = r["file_path"]
        ext = Path(fp).suffix.lower()
        if ext not in IMAGE_EXTS:
            continue
        full_path = CRAWLER_DIR / fp
        if not full_path.exists():
            continue
        candidates.append((r["id"], fp))
        if len(candidates) >= limit:
            break

    return candidates


def save_tags(
    labels_db: str, image_id: int, rating: dict, general: dict, characters: dict, model_name: str, threshold: float
):
    """Save auto-tag results to DB."""
    # Top tags: sorted by confidence, as comma-separated string for quick display
    all_tags = {**general, **characters}
    top = sorted(all_tags.items(), key=lambda x: x[1], reverse=True)[:30]
    top_str = ", ".join(t[0] for t in top)

    conn = sqlite3.connect(str(labels_db))
    try:
        conn.execute(
            """INSERT OR REPLACE INTO auto_tags
               (image_id, rating_json, general_json, character_json, top_tags, model_name, general_threshold, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
            [
                image_id,
                json.dumps(rating, ensure_ascii=False),
                json.dumps(general, ensure_ascii=False),
                json.dumps(characters, ensure_ascii=False),
                top_str,
                model_name,
                threshold,
            ],
        )
        conn.commit()
    finally:
        conn.close()


def save_error(labels_db: str, image_id: int, model_name: str, threshold: float, error_msg: str):
    """Mark an image as failed so it won't be retried."""
    conn = sqlite3.connect(str(labels_db))
    try:
        conn.execute(
            """INSERT OR REPLACE INTO auto_tags
               (image_id, rating_json, general_json, character_json, top_tags, model_name, general_threshold, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
            [
                image_id,
                json.dumps({"_error": error_msg}),
                "{}",
                "{}",
                "_error",
                model_name,
                threshold,
            ],
        )
        conn.commit()
    finally:
        conn.close()


def get_progress(dedup_db: str, labels_db: str) -> tuple[int, int]:
    """Return (tagged_count, total_images). Excludes error entries."""
    lconn = sqlite3.connect(str(labels_db))
    try:
        tagged = lconn.execute("SELECT COUNT(*) FROM auto_tags WHERE top_tags != '_error'").fetchone()[0]
    finally:
        lconn.close()

    dconn = sqlite3.connect(f"file:{dedup_db}?mode=ro", uri=True)
    try:
        # Count only images (not videos)
        _video_exclude_sql, _video_exclude_params = _state.video_filter_sql()
        total = dconn.execute(
            f"SELECT COUNT(*) FROM images WHERE file_path IS NOT NULL AND {_video_exclude_sql}",
            _video_exclude_params,
        ).fetchone()[0]
    finally:
        dconn.close()
    return tagged, total


def run(batch: int = 50, sleep_sec: float = 1.0, threshold: float = 0.35, model_name: str = "SwinV2_v3"):
    init_auto_tags_table(str(LABELS_DB_PATH))

    tagged, total = get_progress(str(DB_PATH), str(LABELS_DB_PATH))
    log.info(f"Progress: {tagged}/{total} images tagged")

    candidates = get_untagged_image_ids(str(DB_PATH), str(LABELS_DB_PATH), batch)
    if not candidates:
        log.info("No untagged images found. All done!")
        return

    log.info(f"Processing {len(candidates)} images (batch={batch}, sleep={sleep_sec}s)")

    # Lazy import to delay model loading
    from imgutils.tagging import get_wd14_tags
    from PIL import Image as _PILImage

    _PILImage.MAX_IMAGE_PIXELS = 80_000_000  # skip decompression bombs

    success = 0
    errors = 0

    for i, (image_id, file_path) in enumerate(candidates):
        full_path = CRAWLER_DIR / file_path
        try:
            # Skip images with too many pixels to avoid OOM
            with _PILImage.open(str(full_path)) as _img:
                _w, _h = _img.size
                if _w * _h > 80_000_000:
                    raise ValueError(f"Image too large: {_w}x{_h} = {_w * _h} pixels")
            rating, general, characters = get_wd14_tags(
                str(full_path),
                model_name=model_name,
                general_threshold=threshold,
                character_threshold=0.85,
                no_underline=True,
                drop_overlap=True,
            )
            save_tags(str(LABELS_DB_PATH), image_id, rating, general, characters, model_name, threshold)
            success += 1

            top3 = sorted(general.items(), key=lambda x: x[1], reverse=True)[:3]
            top3_str = ", ".join(f"{t[0]}({t[1]:.2f})" for t in top3)
            log.info(f"  [{i + 1}/{len(candidates)}] #{image_id} -> {top3_str}")

        except Exception as e:
            errors += 1
            log.warning(f"  [{i + 1}/{len(candidates)}] #{image_id} FAILED: {e}")
            # Mark as error so we don't retry every run
            save_error(str(LABELS_DB_PATH), image_id, model_name, threshold, str(e))

        # Rate limit: sleep + explicit GC every 10 images
        if sleep_sec > 0:
            time.sleep(sleep_sec)
        if (i + 1) % 10 == 0:
            gc.collect()

    tagged_now, total = get_progress(str(DB_PATH), str(LABELS_DB_PATH))
    log.info(f"Done: {success} ok, {errors} errors. Progress: {tagged_now}/{total}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Incremental WD14 auto-tagger")
    parser.add_argument("--batch", type=int, default=50, help="Max images per run (default: 50)")
    parser.add_argument("--sleep", type=float, default=1.0, help="Sleep seconds between images (default: 1.0)")
    parser.add_argument(
        "--threshold", type=float, default=0.35, help="General tag confidence threshold (default: 0.35)"
    )
    parser.add_argument("--model", type=str, default="SwinV2_v3", help="WD14 model name (default: SwinV2_v3)")
    args = parser.parse_args()

    run(batch=args.batch, sleep_sec=args.sleep, threshold=args.threshold, model_name=args.model)
