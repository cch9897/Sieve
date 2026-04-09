"""Database connection management and initialization for the Sieve backend.

Manages connection pools for dedup.db (crawler), labels.db, danbooru_labels.db,
and the shared httpx client for DanbooruFinder API.
"""

import asyncio
import sqlite3

import aiosqlite
import httpx

import config
import state

_db_lock = asyncio.Lock()

# ---------------------------------------------------------------------------
# Main crawler DB pool (singleton, read-only)
# ---------------------------------------------------------------------------

async def get_db() -> aiosqlite.Connection:
    if state._db_pool is None:
        async with _db_lock:
            if state._db_pool is None:
                state._db_pool = await aiosqlite.connect(f"file:{config.DB_PATH}?mode=ro", uri=True)
                state._db_pool.row_factory = aiosqlite.Row
                await state._db_pool.execute("PRAGMA query_only = ON")
                await state._db_pool.execute("PRAGMA temp_store = MEMORY")
                await state._db_pool.execute("PRAGMA cache_size = -20000")
                await state._db_pool.execute("PRAGMA mmap_size = 268435456")
    return state._db_pool


def get_sync_db(readonly: bool = True):
    mode = "ro" if readonly else "rwc"
    conn = sqlite3.connect(f"file:{config.DB_PATH}?mode={mode}", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


# ---------------------------------------------------------------------------
# Labels DB
# ---------------------------------------------------------------------------

def _init_labels_db():
    """Initialize the labels database (separate from main dedup.db)."""
    conn = sqlite3.connect(str(config.LABELS_DB_PATH))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS labels (
            image_id INTEGER PRIMARY KEY,
            verdict TEXT NOT NULL CHECK(verdict IN ('liked', 'disliked', 'skipped')),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            image_id INTEGER NOT NULL,
            tag TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(image_id, tag)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tags_image ON tags(image_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tags_tag ON tags(tag)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_labels_verdict ON labels(verdict)")
    # Vision scores table — multi-model with composite PK
    # Check if old single-PK table exists and migrate
    cur = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='vision_scores'")
    row = cur.fetchone()
    if row:
        ddl = row[0] or ""
        # Old format: image_id INTEGER PRIMARY KEY (no composite key)
        if "PRIMARY KEY (image_id, model_name)" not in ddl:
            print("[db] Migrating vision_scores to multi-model format...")
            conn.execute("ALTER TABLE vision_scores RENAME TO vision_scores_old")
            conn.execute("""
                CREATE TABLE vision_scores (
                    image_id INTEGER NOT NULL,
                    model_name TEXT NOT NULL,
                    score REAL NOT NULL,
                    scored_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (image_id, model_name)
                )
            """)
            conn.execute("""
                INSERT INTO vision_scores (image_id, model_name, score, scored_at)
                SELECT image_id, 'default', score, scored_at FROM vision_scores_old
            """)
            conn.execute("DROP TABLE vision_scores_old")
            print("[db] Migration complete.")
    else:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS vision_scores (
                image_id INTEGER NOT NULL,
                model_name TEXT NOT NULL,
                score REAL NOT NULL,
                scored_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (image_id, model_name)
            )
        """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_vision_scores_score ON vision_scores(score DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_vision_scores_model ON vision_scores(model_name)")
    conn.commit()
    conn.close()


def get_labels_db():
    conn = sqlite3.connect(str(config.LABELS_DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


async def get_labels_db_async() -> aiosqlite.Connection:
    if state._labels_pool is None:
        async with _db_lock:
            if state._labels_pool is None:
                state._labels_pool = await aiosqlite.connect(str(config.LABELS_DB_PATH))
                state._labels_pool.row_factory = aiosqlite.Row
                await state._labels_pool.execute("PRAGMA journal_mode=WAL")
    return state._labels_pool


# ---------------------------------------------------------------------------
# Auto-tags table (in labels DB)
# ---------------------------------------------------------------------------

def _init_auto_tags_table():
    """Initialize auto_tags table in labels DB."""
    conn = sqlite3.connect(str(config.LABELS_DB_PATH))
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
    conn.close()


# ---------------------------------------------------------------------------
# Danbooru labels DB
# ---------------------------------------------------------------------------

def _init_danbooru_labels_db():
    """Initialize the danbooru labels database (separate from labels.db)."""
    conn = sqlite3.connect(str(config.DANBOORU_LABELS_DB_PATH))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS labels (
            image_id INTEGER PRIMARY KEY,
            verdict TEXT NOT NULL CHECK(verdict IN ('liked', 'disliked', 'skipped')),
            ext TEXT,
            score INTEGER,
            rating TEXT,
            tags TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            image_id INTEGER NOT NULL,
            tag TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(image_id, tag)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_danbooru_tags_image ON tags(image_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_danbooru_tags_tag ON tags(tag)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_danbooru_labels_verdict ON labels(verdict)")
    conn.commit()
    conn.close()


async def get_danbooru_labels_db() -> aiosqlite.Connection:
    if state._danbooru_labels_pool is None:
        async with _db_lock:
            if state._danbooru_labels_pool is None:
                state._danbooru_labels_pool = await aiosqlite.connect(str(config.DANBOORU_LABELS_DB_PATH))
                state._danbooru_labels_pool.row_factory = aiosqlite.Row
                await state._danbooru_labels_pool.execute("PRAGMA journal_mode=WAL")
    return state._danbooru_labels_pool


# ---------------------------------------------------------------------------
# Shared httpx client for DanbooruFinder proxy
# ---------------------------------------------------------------------------

def get_danbooru_client() -> httpx.AsyncClient:
    if state._danbooru_client is None:
        state._danbooru_client = httpx.AsyncClient(
            base_url=config.DANBOORU_API,
            timeout=30.0,
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )
    return state._danbooru_client
