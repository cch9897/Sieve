#!/usr/bin/env python3
"""
Training cache: unified tag database for all training data sources.

Stores WD14-format general_json / rating_json per image so train_classifier.py
can load everything from one place.  Sources that only have raw Danbooru tags
are converted to {tag: 1.0} dicts.

Usage:
  python training_cache.py            # sync danbooru_labels.db → cache
  python training_cache.py --stats    # show cache stats
"""

import json
import sqlite3
import os
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent

try:
    from dotenv import load_dotenv
    load_dotenv(_PROJECT_ROOT / ".env")
except ImportError:
    pass

CACHE_DB = Path(os.environ.get(
    "TRAINING_CACHE_DB",
    str(Path(__file__).parent / "training_cache.db"),
))

DANBOORU_LABELS_DB = Path(os.environ.get(
    "DANBOORU_LABELS_DB_PATH",
    str(_PROJECT_ROOT / "backend" / "danbooru_labels.db"),
))

# Danbooru rating → WD14 rating key mapping
_RATING_MAP = {
    "g": "general",
    "s": "sensitive",
    "q": "questionable",
    "e": "explicit",
}


def get_conn(db_path: Path = CACHE_DB) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS training_tags (
            source      TEXT NOT NULL,   -- 'danbooru', 'booru', 'twitter', ...
            image_id    TEXT NOT NULL,   -- unique within source
            verdict     TEXT NOT NULL,   -- 'liked' / 'disliked'
            general_json TEXT NOT NULL,  -- {tag: confidence, ...}
            rating_json  TEXT NOT NULL,  -- {general: x, sensitive: x, ...}
            has_wd14    INTEGER DEFAULT 0,  -- 1 if WD14-tagged, 0 if converted
            updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (source, image_id)
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_tc_source_verdict
        ON training_tags(source, verdict)
    """)
    conn.commit()
    return conn


def _danbooru_tags_to_general(tags_str: str) -> dict:
    """Convert comma-separated danbooru tags to {tag: 1.0} dict."""
    if not tags_str:
        return {}
    return {t.strip(): 1.0 for t in tags_str.split(",") if t.strip()}


def _danbooru_rating_to_wd14(rating: str) -> dict:
    """Convert single-letter danbooru rating to WD14 rating dict."""
    result = {"general": 0.0, "sensitive": 0.0, "questionable": 0.0, "explicit": 0.0}
    key = _RATING_MAP.get(rating, "")
    if key:
        result[key] = 1.0
    return result


def sync_danbooru(conn: sqlite3.Connection | None = None):
    """Sync danbooru_labels.db → training_cache.db.
    
    Only imports rows that don't already have WD14 tags in the cache.
    """
    if not DANBOORU_LABELS_DB.exists():
        print(f"  Danbooru labels DB not found: {DANBOORU_LABELS_DB}")
        return 0

    own_conn = conn is None
    if own_conn:
        conn = get_conn()

    src = sqlite3.connect(str(DANBOORU_LABELS_DB))
    rows = src.execute(
        "SELECT image_id, verdict, tags, rating FROM labels WHERE verdict IN ('liked', 'disliked')"
    ).fetchall()
    src.close()

    # Get existing WD14-tagged entries (don't overwrite those)
    existing_wd14 = set()
    for r in conn.execute(
        "SELECT image_id FROM training_tags WHERE source='danbooru' AND has_wd14=1"
    ).fetchall():
        existing_wd14.add(str(r[0]))

    inserted = 0
    for image_id, verdict, tags_str, rating in rows:
        sid = str(image_id)
        if sid in existing_wd14:
            continue
        general = _danbooru_tags_to_general(tags_str)
        rating_dict = _danbooru_rating_to_wd14(rating)
        conn.execute(
            """INSERT INTO training_tags (source, image_id, verdict, general_json, rating_json, has_wd14)
               VALUES (?, ?, ?, ?, ?, 0)
               ON CONFLICT(source, image_id) DO UPDATE SET
                 verdict=excluded.verdict,
                 general_json = CASE WHEN training_tags.has_wd14 = 1
                                     THEN training_tags.general_json
                                     ELSE excluded.general_json END,
                 rating_json = CASE WHEN training_tags.has_wd14 = 1
                                    THEN training_tags.rating_json
                                    ELSE excluded.rating_json END,
                 updated_at=CURRENT_TIMESTAMP""",
            [
                "danbooru", sid, verdict,
                json.dumps(general, ensure_ascii=False),
                json.dumps(rating_dict),
            ],
        )
        inserted += 1

    conn.commit()
    if own_conn:
        conn.close()
    return inserted


def upsert_wd14(source: str, image_id: str, verdict: str,
                general: dict, rating: dict,
                conn: sqlite3.Connection | None = None):
    """Insert or update a WD14-tagged entry (overwrites converted tags)."""
    own_conn = conn is None
    if own_conn:
        conn = get_conn()
    conn.execute(
        """INSERT INTO training_tags (source, image_id, verdict, general_json, rating_json, has_wd14)
           VALUES (?, ?, ?, ?, ?, 1)
           ON CONFLICT(source, image_id) DO UPDATE SET
             verdict=excluded.verdict,
             general_json=excluded.general_json,
             rating_json=excluded.rating_json,
             has_wd14=1,
             updated_at=CURRENT_TIMESTAMP""",
        [source, image_id, verdict,
         json.dumps(general, ensure_ascii=False),
         json.dumps(rating)],
    )
    conn.commit()
    if own_conn:
        conn.close()


def load_training_data(conn: sqlite3.Connection | None = None) -> list:
    """Load all cached training data in train_classifier.py format.
    
    Returns list of (general_dict, rating_dict, label_int, name_str).
    """
    own_conn = conn is None
    if own_conn:
        conn = get_conn()

    rows = conn.execute(
        "SELECT source, image_id, verdict, general_json, rating_json FROM training_tags"
    ).fetchall()

    if own_conn:
        conn.close()

    data = []
    for source, image_id, verdict, general_json, rating_json in rows:
        general = json.loads(general_json)
        rating = json.loads(rating_json)
        label = 1 if verdict == "liked" else 0
        data.append((general, rating, label, f"{source}_{image_id}"))
    return data


def print_stats(conn: sqlite3.Connection | None = None):
    own_conn = conn is None
    if own_conn:
        conn = get_conn()

    rows = conn.execute(
        "SELECT source, verdict, has_wd14, COUNT(*) FROM training_tags GROUP BY source, verdict, has_wd14"
    ).fetchall()

    if own_conn:
        conn.close()

    if not rows:
        print("  Cache is empty.")
        return

    print(f"  {'Source':<12} {'Verdict':<10} {'WD14':>5} {'Count':>6}")
    print(f"  {'-'*12} {'-'*10} {'-'*5} {'-'*6}")
    total = 0
    for source, verdict, has_wd14, count in rows:
        wd = "yes" if has_wd14 else "no"
        print(f"  {source:<12} {verdict:<10} {wd:>5} {count:>6}")
        total += count
    print(f"  {'':.<12} {'Total':<10} {'':>5} {total:>6}")


if __name__ == "__main__":
    if "--stats" in sys.argv:
        print("Training cache stats:")
        print_stats()
    else:
        print("Syncing danbooru_labels.db → training_cache.db ...")
        conn = get_conn()
        n = sync_danbooru(conn)
        print(f"  Synced {n} entries.")
        print()
        print_stats(conn)
        conn.close()
