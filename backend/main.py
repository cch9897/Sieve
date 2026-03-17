import asyncio
import io
import json
import os
import signal
import sqlite3
import subprocess
import time
import zipfile
from contextlib import asynccontextmanager
from functools import partial
from pathlib import Path
from typing import Optional
from urllib.parse import quote

import mimetypes

import aiosqlite
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import httpx

import httpx
import joblib
import numpy as np

from config import (
    CRAWLER_DIR, DB_PATH, DOWNLOADS_DIR, HOST, LABELS_DB_PATH, PORT,
    DANBOORU_API, DANBOORU_LABELS_DB_PATH, DANBOORU_LIKES_DIR,
    PREFERENCE_MODEL_PATH, CNN_MODEL_PATH, CANDIDATES_DB_PATH, PROJECT_ROOT,
)

# Global preference models (loaded in lifespan)
_preference_model: dict | None = None
_cnn_model: dict | None = None  # {'model': nn.Module, 'transform': Compose, ...}

VIDEO_EXTS = {".mp4", ".webm", ".mkv", ".avi", ".mov"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".avif"}


def _range_file_response(file_path: Path, request: Request) -> StreamingResponse | FileResponse:
    """Serve a file with HTTP Range support (needed for video playback)."""
    ext = file_path.suffix.lower()
    content_type = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
    file_size = file_path.stat().st_size

    range_header = request.headers.get("range")
    if range_header and ext in VIDEO_EXTS:
        # Parse "bytes=start-end"
        range_spec = range_header.strip().lower()
        if range_spec.startswith("bytes="):
            range_spec = range_spec[6:]
        parts = range_spec.split("-", 1)
        start = int(parts[0]) if parts[0] else 0
        end = int(parts[1]) if parts[1] else file_size - 1
        end = min(end, file_size - 1)
        length = end - start + 1

        def iter_range():
            CHUNK = 1024 * 1024  # 1MB chunks
            with open(file_path, "rb") as f:
                f.seek(start)
                remaining = length
                while remaining > 0:
                    chunk = f.read(min(CHUNK, remaining))
                    if not chunk:
                        break
                    remaining -= len(chunk)
                    yield chunk

        return StreamingResponse(
            iter_range(),
            status_code=206,
            media_type=content_type,
            headers={
                "Content-Range": f"bytes {start}-{end}/{file_size}",
                "Content-Length": str(length),
                "Accept-Ranges": "bytes",
                "Cache-Control": "public, max-age=86400, immutable",
            },
        )

    # Non-range or non-video: serve normally
    headers = {"Cache-Control": "public, max-age=86400, immutable"}
    if ext in VIDEO_EXTS:
        headers["Accept-Ranges"] = "bytes"
    return FileResponse(file_path, headers=headers)

FRONTEND_DIST = Path(__file__).parent.parent / "frontend" / "dist"
THUMBS_DIR = CRAWLER_DIR / ".thumbs"
THUMB_WIDTH = 400

# Resolve symlink targets so security checks work with NFS mounts
_ALLOWED_ROOTS = {CRAWLER_DIR.resolve()}
_downloads_link = CRAWLER_DIR / "downloads"
if _downloads_link.is_symlink():
    _ALLOWED_ROOTS.add(_downloads_link.resolve().parent)


def _safe_under_crawler(path: Path) -> bool:
    """Check path resolves under CRAWLER_DIR or its symlink targets (prevent traversal)."""
    resolved = path.resolve()
    return any(resolved.is_relative_to(root) for root in _ALLOWED_ROOTS)


# ---------------------------------------------------------------------------
# DB connection pool (singleton)
# ---------------------------------------------------------------------------

_db_pool: aiosqlite.Connection | None = None


async def get_db() -> aiosqlite.Connection:
    global _db_pool
    if _db_pool is None:
        _db_pool = await aiosqlite.connect(f"file:{DB_PATH}?mode=ro", uri=True)
        _db_pool.row_factory = aiosqlite.Row
        await _db_pool.execute("PRAGMA query_only = ON")
        await _db_pool.execute("PRAGMA temp_store = MEMORY")
        await _db_pool.execute("PRAGMA cache_size = -20000")
        await _db_pool.execute("PRAGMA mmap_size = 268435456")
    return _db_pool


def get_sync_db(readonly: bool = True):
    mode = "ro" if readonly else "rwc"
    conn = sqlite3.connect(f"file:{DB_PATH}?mode={mode}", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# Novel metadata LRU cache (TTL-based)
# ---------------------------------------------------------------------------

_novel_meta_cache: dict[str, tuple[float, dict]] = {}
_NOVEL_CACHE_TTL = 300  # 5 minutes
_NOVEL_CACHE_MAX = 2000


def _read_novel_meta(file_path: str, include_text: bool = False) -> dict:
    """Read novel metadata from JSON file on disk, with in-memory caching."""
    if not file_path:
        return {}

    cache_key = file_path
    now = time.monotonic()

    # Check cache for non-text requests (text is large, don't cache it)
    if not include_text and cache_key in _novel_meta_cache:
        ts, cached = _novel_meta_cache[cache_key]
        if now - ts < _NOVEL_CACHE_TTL:
            return cached

    full_path = CRAWLER_DIR / file_path
    if not full_path.exists():
        full_path = Path(file_path)
    if not full_path.exists():
        return {}
    try:
        with open(full_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        result = {
            "title": data.get("title", ""),
            "author": data.get("author", ""),
            "tags": data.get("tags", []),
            "text_length": data.get("text_length", len(data.get("text", ""))),
            "total_bookmarks": data.get("total_bookmarks", 0),
            "total_view": data.get("total_view", 0),
            "series_title": data.get("series_title"),
            "series_id": data.get("series_id"),
            "caption": data.get("caption", ""),
            "r18": data.get("r18", False),
        }
        if include_text:
            result["text"] = data.get("text", "")
        else:
            # Evict oldest entries if cache is full
            if len(_novel_meta_cache) >= _NOVEL_CACHE_MAX:
                oldest_key = min(_novel_meta_cache, key=lambda k: _novel_meta_cache[k][0])
                del _novel_meta_cache[oldest_key]
            _novel_meta_cache[cache_key] = (now, result)
        return result
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

def _init_labels_db():
    """Initialize the labels database (separate from main dedup.db)."""
    conn = sqlite3.connect(str(LABELS_DB_PATH))
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
    conn.commit()
    conn.close()


def get_labels_db():
    conn = sqlite3.connect(str(LABELS_DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


_labels_pool: aiosqlite.Connection | None = None


async def get_labels_db_async() -> aiosqlite.Connection:
    global _labels_pool
    if _labels_pool is None:
        _labels_pool = await aiosqlite.connect(str(LABELS_DB_PATH))
        _labels_pool.row_factory = aiosqlite.Row
        await _labels_pool.execute("PRAGMA journal_mode=WAL")
    return _labels_pool


# ---------------------------------------------------------------------------
# Danbooru labels DB (completely separate from crawler labels)
# ---------------------------------------------------------------------------

def _init_auto_tags_table():
    """Initialize auto_tags table in labels DB."""
    conn = sqlite3.connect(str(LABELS_DB_PATH))
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


def _init_danbooru_labels_db():
    """Initialize the danbooru labels database (separate from labels.db)."""
    conn = sqlite3.connect(str(DANBOORU_LABELS_DB_PATH))
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


_danbooru_labels_pool: aiosqlite.Connection | None = None


async def get_danbooru_labels_db() -> aiosqlite.Connection:
    global _danbooru_labels_pool
    if _danbooru_labels_pool is None:
        _danbooru_labels_pool = await aiosqlite.connect(str(DANBOORU_LABELS_DB_PATH))
        _danbooru_labels_pool.row_factory = aiosqlite.Row
        await _danbooru_labels_pool.execute("PRAGMA journal_mode=WAL")
    return _danbooru_labels_pool


# Shared httpx client for Danbooru proxy
_danbooru_client: httpx.AsyncClient | None = None


def get_danbooru_client() -> httpx.AsyncClient:
    global _danbooru_client
    if _danbooru_client is None:
        _danbooru_client = httpx.AsyncClient(
            base_url=DANBOORU_API,
            timeout=30.0,

            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )
    return _danbooru_client


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not DB_PATH.exists():
        raise RuntimeError(f"Database not found: {DB_PATH}")
    THUMBS_DIR.mkdir(parents=True, exist_ok=True)
    _init_labels_db()
    _init_auto_tags_table()
    _init_danbooru_labels_db()

    # Load preference models
    global _preference_model, _cnn_model
    if PREFERENCE_MODEL_PATH.exists():
        try:
            _preference_model = joblib.load(PREFERENCE_MODEL_PATH)
            print(f"[preference] XGBoost loaded: AUC={_preference_model['auc']:.4f}, "
                  f"vocab={len(_preference_model['tag_vocab'])} tags")
        except Exception as e:
            print(f"[preference] Failed to load XGBoost: {e}")
            _preference_model = None
    else:
        print(f"[preference] XGBoost not found at {PREFERENCE_MODEL_PATH}")

    if CNN_MODEL_PATH.exists():
        try:
            import torch, timm
            from torchvision import transforms as T
            checkpoint = torch.load(str(CNN_MODEL_PATH), map_location='cpu', weights_only=False)
            model_name = checkpoint['model_name']
            cnn = timm.create_model(model_name, pretrained=False, num_classes=checkpoint['num_classes'])
            cnn.load_state_dict(checkpoint['model_state_dict'])
            cnn.eval()
            input_size = checkpoint.get('input_size', 224)
            mean = checkpoint.get('normalize_mean', [0.485, 0.456, 0.406])
            std = checkpoint.get('normalize_std', [0.229, 0.224, 0.225])
            transform = T.Compose([
                T.Resize(int(input_size * 1.14)),
                T.CenterCrop(input_size),
                T.ToTensor(),
                T.Normalize(mean=mean, std=std),
            ])
            _cnn_model = {
                'model': cnn, 'transform': transform,
                'cv_auc': checkpoint.get('cv_auc', 0),
                'n_samples': checkpoint.get('n_samples', 0),
                'model_name': model_name,
                'input_size': input_size,
                'fold_aucs': checkpoint.get('fold_aucs', []),
            }
            print(f"[preference] CNN loaded: {model_name}, AUC={_cnn_model['cv_auc']:.4f}")
        except Exception as e:
            print(f"[preference] Failed to load CNN: {e}")
            _cnn_model = None
    else:
        print(f"[preference] CNN not found at {CNN_MODEL_PATH}")

    with get_sync_db(readonly=False) as conn:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_images_file_created_at ON images(file_path, created_at DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_images_source_file_created_at ON images(source, file_path, created_at DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_novels_file_created_at ON novels(file_path, created_at DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_novels_title_author ON novels(title, author)")

    yield
    global _db_pool, _labels_pool, _danbooru_labels_pool, _danbooru_client
    if _db_pool is not None:
        await _db_pool.close()
        _db_pool = None
    if _labels_pool is not None:
        await _labels_pool.close()
        _labels_pool = None
    if _danbooru_labels_pool is not None:
        await _danbooru_labels_pool.close()
        _danbooru_labels_pool = None
    if _danbooru_client is not None:
        await _danbooru_client.aclose()
        _danbooru_client = None


app = FastAPI(title="Sieve", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Thumbnail endpoint
# ---------------------------------------------------------------------------

def _generate_thumb(source_path: Path, thumb_base: Path, thumb_width: int = 600) -> Path:
    """Generate a thumbnail synchronously (called in thread pool)."""
    from PIL import Image

    ext = source_path.suffix.lower()
    thumb_base.parent.mkdir(parents=True, exist_ok=True)

    with Image.open(source_path) as img:
        if img.width <= thumb_width:
            return source_path

        ratio = thumb_width / img.width
        new_h = int(img.height * ratio)
        thumb = img.resize((thumb_width, new_h), Image.LANCZOS)

        if ext == ".png" and img.mode == "RGBA":
            thumb.save(str(thumb_base), "PNG", optimize=True)
            return thumb_base
        else:
            if thumb.mode in ("RGBA", "P"):
                thumb = thumb.convert("RGB")
            save_path = thumb_base.with_suffix(".jpg")
            thumb.save(str(save_path), "JPEG", quality=85, optimize=True)
            return save_path


@app.get("/api/thumb/{file_path:path}")
async def serve_thumbnail(file_path: str, request: Request):
    """Serve cached thumbnail, generate in thread pool if missing."""
    source_path: Path | None = None
    for candidate in [file_path, quote(file_path, safe="/")]:
        full = CRAWLER_DIR / candidate
        if _safe_under_crawler(full) and full.exists():
            source_path = full
            break
    if source_path is None:
        raise HTTPException(status_code=404, detail="File not found")

    ext = source_path.suffix.lower()
    # Videos: serve directly with range support
    if ext in VIDEO_EXTS:
        return _range_file_response(source_path, request)

    # Check cached thumbnail (try both original ext and .jpg)
    thumb_base = THUMBS_DIR / file_path
    for candidate_thumb in [thumb_base, thumb_base.with_suffix(".jpg")]:
        if candidate_thumb.exists():
            return FileResponse(
                candidate_thumb,
                headers={"Cache-Control": "public, max-age=86400, immutable"},
            )

    # Generate thumbnail in thread pool (non-blocking)
    try:
        loop = asyncio.get_event_loop()
        thumb_path = await loop.run_in_executor(
            None, _generate_thumb, source_path, thumb_base
        )
        return FileResponse(
            thumb_path,
            headers={"Cache-Control": "public, max-age=86400, immutable"},
        )
    except Exception:
        # Fallback to original
        return FileResponse(
            source_path,
            headers={"Cache-Control": "public, max-age=86400, immutable"},
        )


# ---------------------------------------------------------------------------
# Image APIs
# ---------------------------------------------------------------------------

@app.get("/api/images")
async def list_images(
    source: Optional[str] = Query(None),
    date: Optional[str] = Query(None),
    media: Optional[str] = Query(None, pattern="^(image|video)$"),
    sort: str = Query("newest", pattern="^(newest|oldest)$"),
    page: int = Query(1, ge=1),
    per_page: int = Query(60, ge=1, le=200),
):
    db = await get_db()
    conditions = ["file_path IS NOT NULL"]
    params: list = []

    if source:
        conditions.append("source = ?")
        params.append(source)

    if date:
        conditions.append("file_path LIKE ?")
        params.append(f"downloads/{date}/%")

    if media == "video":
        conditions.append("(file_path LIKE '%.mp4' OR file_path LIKE '%.webm')")
    elif media == "image":
        conditions.append("file_path NOT LIKE '%.mp4' AND file_path NOT LIKE '%.webm'")

    where = " AND ".join(conditions)
    order = "created_at DESC" if sort == "newest" else "created_at ASC"
    offset = (page - 1) * per_page

    count_sql = f"SELECT COUNT(*) FROM images WHERE {where}"
    list_sql = f"SELECT id, source, source_id, file_path, url, created_at FROM images WHERE {where} ORDER BY {order} LIMIT ? OFFSET ?"

    async with db.execute(count_sql, params) as count_cursor, db.execute(list_sql, params + [per_page, offset]) as list_cursor:
        total_row, rows = await count_cursor.fetchone(), await list_cursor.fetchall()
        total = total_row[0]

    images = []
    for r in rows:
        fp = r["file_path"]
        parts = fp.split("/")
        img_date = parts[1] if len(parts) >= 2 else None
        subfolder = parts[2] if len(parts) >= 3 else None
        ext = Path(fp).suffix.lower()
        is_video = ext in VIDEO_EXTS

        images.append({
            "id": r["id"],
            "source": r["source"],
            "source_id": r["source_id"],
            "file_path": fp,
            "url": r["url"],
            "created_at": r["created_at"],
            "date": img_date,
            "subfolder": subfolder,
            "is_video": is_video,
            "thumb_url": f"/api/thumb/{fp}" if not is_video else f"/images/{fp}",
        })

    return {
        "images": images,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page if total > 0 else 0,
    }


@app.get("/api/images/{image_id}")
async def get_image(image_id: int):
    db = await get_db()
    sql = "SELECT id, source, source_id, phash, file_path, url, created_at FROM images WHERE id = ?"
    async with db.execute(sql, [image_id]) as cursor:
        row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Image not found")

    fp = row["file_path"]
    ext = Path(fp).suffix.lower() if fp else ""
    parts = (fp or "").split("/")

    return {
        "id": row["id"],
        "source": row["source"],
        "source_id": row["source_id"],
        "phash": row["phash"],
        "file_path": fp,
        "url": row["url"],
        "created_at": row["created_at"],
        "date": parts[1] if len(parts) >= 2 else None,
        "subfolder": parts[2] if len(parts) >= 3 else None,
        "is_video": ext in VIDEO_EXTS,
        "thumb_url": f"/images/{fp}" if fp else None,
    }


# ---------------------------------------------------------------------------
# Novel APIs
# ---------------------------------------------------------------------------

@app.get("/api/novels")
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

    order_map = {
        "newest": "created_at DESC",
        "oldest": "created_at ASC",
        "bookmarks": "created_at DESC",
        "views": "created_at DESC",
        "length": "created_at DESC",
    }
    order = order_map.get(sort, "created_at DESC")
    offset = (page - 1) * per_page

    sql = f"""SELECT id, source, source_id, title, author, file_path, url, created_at
              FROM novels WHERE {where} ORDER BY {order} LIMIT ? OFFSET ?"""
    async with db.execute(count_sql, params) as count_cursor, db.execute(sql, params + [per_page, offset]) as list_cursor:
        total_row, rows = await count_cursor.fetchone(), await list_cursor.fetchall()
        total = total_row[0]

    novels = []
    # Read all novel metadata in thread pool to avoid blocking event loop
    loop = asyncio.get_event_loop()
    file_paths = [r["file_path"] for r in rows]
    metas = await loop.run_in_executor(None, lambda: [_read_novel_meta(fp) for fp in file_paths])

    for r, meta in zip(rows, metas):
        fp = r["file_path"]
        parts = fp.split("/") if fp else []
        novel_date = None
        for p in parts:
            if len(p) == 10 and p[4] == '-' and p[7] == '-':
                novel_date = p
                break

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

    return {
        "novels": novels,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page if total > 0 else 0,
    }


@app.get("/api/novels/dates")
async def get_novel_dates():
    db = await get_db()
    async with db.execute("SELECT DISTINCT file_path FROM novels WHERE file_path IS NOT NULL") as c:
        rows = await c.fetchall()

    dates = set()
    for r in rows:
        fp = r[0]
        parts = fp.split("/") if fp else []
        for p in parts:
            if len(p) == 10 and p[4:5] == '-' and p[7:8] == '-':
                dates.add(p)
                break

    return {"dates": sorted(dates, reverse=True)}


@app.get("/api/novels/{novel_id}")
async def get_novel(novel_id: int):
    """Get novel detail including full text."""
    db = await get_db()
    sql = "SELECT id, source, source_id, title, author, file_path, url, created_at FROM novels WHERE id = ?"
    async with db.execute(sql, [novel_id]) as cursor:
        row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Novel not found")

    fp = row["file_path"]
    loop = asyncio.get_event_loop()
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


# ---------------------------------------------------------------------------
# Stats / filter data
# ---------------------------------------------------------------------------

@app.get("/api/stats")
async def get_stats():
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


@app.get("/api/dates")
async def get_dates():
    db = await get_db()
    async with db.execute(
        """SELECT DISTINCT substr(file_path, 11, 10) as date
           FROM images WHERE file_path IS NOT NULL AND file_path LIKE 'downloads/%'
           ORDER BY date DESC"""
    ) as c:
        rows = await c.fetchall()
        return {"dates": [r[0] for r in rows if r[0]]}


@app.get("/api/sources")
async def get_sources():
    db = await get_db()
    async with db.execute(
        "SELECT source, COUNT(*) as cnt FROM images WHERE file_path IS NOT NULL GROUP BY source ORDER BY source"
    ) as c:
        rows = await c.fetchall()
        return {"sources": [r[0] for r in rows], "counts": {r[0]: r[1] for r in rows}}


# ---------------------------------------------------------------------------
# Labeling APIs (for dataset curation)
# ---------------------------------------------------------------------------

class LabelRequest(BaseModel):
    verdict: str  # liked, disliked, skipped
    tags: list[str] = []


@app.get("/api/labeler/next")
async def labeler_next(
    source: Optional[str] = Query(None),
    media: Optional[str] = Query(None, pattern="^(image|video)$"),
):
    """Get the next unlabeled image for review."""
    db = await get_db()
    ldb = await get_labels_db_async()

    # Get all labeled image IDs
    async with ldb.execute("SELECT image_id FROM labels") as c:
        labeled_ids = {r[0] for r in await c.fetchall()}

    conditions = ["file_path IS NOT NULL"]
    params: list = []
    if source:
        conditions.append("source = ?")
        params.append(source)
    if media == "video":
        conditions.append("(file_path LIKE '%.mp4' OR file_path LIKE '%.webm')")
    elif media == "image":
        conditions.append("file_path NOT LIKE '%.mp4' AND file_path NOT LIKE '%.webm'")

    if labeled_ids:
        placeholders = ",".join("?" * len(labeled_ids))
        conditions.append(f"id NOT IN ({placeholders})")
        params.extend(labeled_ids)

    where = " AND ".join(conditions)

    # Count remaining
    async with db.execute(f"SELECT COUNT(*) FROM images WHERE {where}", params) as c:
        remaining = (await c.fetchone())[0]

    if remaining == 0:
        return {"image": None, "remaining": 0, "total_labeled": len(labeled_ids)}

    # Get random unlabeled images, try up to 10 to find one with an existing file
    sql = f"SELECT id, source, source_id, file_path, url, created_at FROM images WHERE {where} ORDER BY RANDOM() LIMIT 10"
    async with db.execute(sql, params) as c:
        candidates = await c.fetchall()

    for row in candidates:
        fp = row["file_path"]
        full_path = CRAWLER_DIR / fp
        if not full_path.exists():
            # Auto-skip missing files
            continue

        ext = Path(fp).suffix.lower()
        parts = fp.split("/")
        return {
            "image": {
                "id": row["id"],
                "source": row["source"],
                "source_id": row["source_id"],
                "file_path": fp,
                "url": row["url"],
                "created_at": row["created_at"],
                "date": parts[1] if len(parts) >= 2 else None,
                "is_video": ext in VIDEO_EXTS,
                "thumb_url": f"/api/thumb/{fp}",
            },
            "remaining": remaining,
            "total_labeled": len(labeled_ids),
        }

    return {"image": None, "remaining": 0, "total_labeled": len(labeled_ids)}


@app.post("/api/labeler/{image_id}")
async def label_image(image_id: int, req: LabelRequest):
    """Label an image as liked/disliked/skipped, optionally with tags."""
    if req.verdict not in ("liked", "disliked", "skipped"):
        raise HTTPException(status_code=400, detail="verdict must be liked, disliked, or skipped")

    ldb = await get_labels_db_async()
    await ldb.execute(
        """INSERT INTO labels (image_id, verdict, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)
           ON CONFLICT(image_id) DO UPDATE SET verdict=excluded.verdict, updated_at=CURRENT_TIMESTAMP""",
        [image_id, req.verdict],
    )

    # Handle tags
    if req.tags:
        for tag in req.tags:
            tag = tag.strip()
            if tag:
                await ldb.execute(
                    "INSERT OR IGNORE INTO tags (image_id, tag) VALUES (?, ?)",
                    [image_id, tag],
                )

    await ldb.commit()
    return {"ok": True}


@app.delete("/api/labeler/{image_id}")
async def unlabel_image(image_id: int):
    """Remove label and tags for an image (undo)."""
    ldb = await get_labels_db_async()
    await ldb.execute("DELETE FROM labels WHERE image_id = ?", [image_id])
    await ldb.execute("DELETE FROM tags WHERE image_id = ?", [image_id])
    await ldb.commit()
    return {"ok": True}


@app.get("/api/labeler/stats")
async def labeler_stats():
    """Get labeling statistics."""
    db = await get_db()
    ldb = await get_labels_db_async()

    async with db.execute("SELECT COUNT(*) FROM images WHERE file_path IS NOT NULL") as c:
        total_images = (await c.fetchone())[0]

    stats = {"total_images": total_images, "liked": 0, "disliked": 0, "skipped": 0}
    async with ldb.execute("SELECT verdict, COUNT(*) FROM labels GROUP BY verdict") as c:
        for r in await c.fetchall():
            stats[r[0]] = r[1]

    stats["total_labeled"] = stats["liked"] + stats["disliked"] + stats["skipped"]
    stats["remaining"] = total_images - stats["total_labeled"]

    # Top tags (manual)
    async with ldb.execute("SELECT tag, COUNT(*) as cnt FROM tags GROUP BY tag ORDER BY cnt DESC LIMIT 50") as c:
        stats["top_tags"] = [{"tag": r[0], "count": r[1]} for r in await c.fetchall()]

    # --- Liked images: auto-tag ranking & source distribution ---
    # Get liked image IDs
    async with ldb.execute("SELECT image_id FROM labels WHERE verdict = 'liked'") as c:
        liked_ids = [r[0] for r in await c.fetchall()]

    # Source distribution for liked images
    liked_by_source: dict[str, int] = {}
    if liked_ids:
        # Query in batches to avoid SQL variable limit
        for i in range(0, len(liked_ids), 500):
            batch = liked_ids[i:i+500]
            placeholders = ",".join("?" * len(batch))
            async with db.execute(
                f"SELECT source, COUNT(*) FROM images WHERE id IN ({placeholders}) GROUP BY source",
                batch,
            ) as c:
                for r in await c.fetchall():
                    liked_by_source[r[0]] = liked_by_source.get(r[0], 0) + r[1]
    stats["liked_by_source"] = dict(sorted(liked_by_source.items(), key=lambda x: x[1], reverse=True))

    # Total images per source (for like-rate calculation)
    async with db.execute(
        "SELECT source, COUNT(*) FROM images WHERE file_path IS NOT NULL GROUP BY source"
    ) as c:
        stats["total_by_source"] = {r[0]: r[1] for r in await c.fetchall()}

    # Labeled (liked+disliked) per source for like-rate denominator
    labeled_ids: list[int] = []
    async with ldb.execute("SELECT image_id FROM labels WHERE verdict IN ('liked', 'disliked')") as c:
        labeled_ids = [r[0] for r in await c.fetchall()]

    labeled_by_source: dict[str, int] = {}
    if labeled_ids:
        for i in range(0, len(labeled_ids), 500):
            batch = labeled_ids[i:i+500]
            placeholders = ",".join("?" * len(batch))
            async with db.execute(
                f"SELECT source, COUNT(*) FROM images WHERE id IN ({placeholders}) GROUP BY source",
                batch,
            ) as c:
                for r in await c.fetchall():
                    labeled_by_source[r[0]] = labeled_by_source.get(r[0], 0) + r[1]
    stats["labeled_by_source"] = labeled_by_source

    # Auto-tag ranking for liked images
    liked_auto_tags: dict[str, int] = {}
    if liked_ids:
        for i in range(0, len(liked_ids), 500):
            batch = liked_ids[i:i+500]
            placeholders = ",".join("?" * len(batch))
            async with ldb.execute(
                f"SELECT general_json FROM auto_tags WHERE top_tags != '_error' AND image_id IN ({placeholders})",
                batch,
            ) as c:
                import json as _json
                for r in await c.fetchall():
                    try:
                        tags_dict = _json.loads(r[0])
                        for tag in tags_dict:
                            liked_auto_tags[tag] = liked_auto_tags.get(tag, 0) + 1
                    except Exception:
                        pass
    top_liked_tags = sorted(liked_auto_tags.items(), key=lambda x: x[1], reverse=True)[:50]
    stats["liked_top_auto_tags"] = [{"tag": t, "count": c} for t, c in top_liked_tags]

    return stats


@app.get("/api/labeler/history")
async def labeler_history(
    verdict: Optional[str] = Query(None, pattern="^(liked|disliked|skipped)$"),
    tag: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(60, ge=1, le=200),
):
    """Get labeled images history with optional filters."""
    db = await get_db()
    ldb = await get_labels_db_async()

    conditions = ["1=1"]
    params: list = []

    if verdict:
        conditions.append("l.verdict = ?")
        params.append(verdict)

    if tag:
        conditions.append("l.image_id IN (SELECT image_id FROM tags WHERE tag = ?)")
        params.append(tag)

    where = " AND ".join(conditions)
    offset = (page - 1) * per_page

    async with ldb.execute(f"SELECT COUNT(*) FROM labels l WHERE {where}", params) as c:
        total = (await c.fetchone())[0]

    async with ldb.execute(
        f"SELECT l.image_id, l.verdict, l.updated_at FROM labels l WHERE {where} ORDER BY l.updated_at DESC LIMIT ? OFFSET ?",
        params + [per_page, offset],
    ) as c:
        label_rows = await c.fetchall()

    if not label_rows:
        return {"images": [], "total": total, "page": page, "per_page": per_page, "pages": 0}

    image_ids = [r[0] for r in label_rows]
    verdict_map = {r[0]: r[1] for r in label_rows}

    # Fetch image data from main DB
    placeholders = ",".join("?" * len(image_ids))
    async with db.execute(
        f"SELECT id, source, source_id, file_path, url, created_at FROM images WHERE id IN ({placeholders})",
        image_ids,
    ) as c:
        img_rows = await c.fetchall()

    img_map = {r["id"]: r for r in img_rows}

    # Fetch tags for these images
    async with ldb.execute(
        f"SELECT image_id, tag FROM tags WHERE image_id IN ({placeholders})",
        image_ids,
    ) as c:
        tag_rows = await c.fetchall()

    tags_map: dict[int, list[str]] = {}
    for r in tag_rows:
        tags_map.setdefault(r[0], []).append(r[1])

    images = []
    for iid in image_ids:
        r = img_map.get(iid)
        if not r:
            continue
        fp = r["file_path"]
        ext = Path(fp).suffix.lower() if fp else ""
        parts = (fp or "").split("/")
        images.append({
            "id": r["id"],
            "source": r["source"],
            "source_id": r["source_id"],
            "file_path": fp,
            "url": r["url"],
            "created_at": r["created_at"],
            "date": parts[1] if len(parts) >= 2 else None,
            "is_video": ext in VIDEO_EXTS,
            "thumb_url": f"/api/thumb/{fp}",
            "verdict": verdict_map.get(iid),
            "tags": tags_map.get(iid, []),
        })

    return {
        "images": images,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page if total > 0 else 0,
    }


@app.post("/api/labeler/{image_id}/tags")
async def update_tags(image_id: int, tags: list[str]):
    """Replace all tags for an image."""
    ldb = await get_labels_db_async()
    await ldb.execute("DELETE FROM tags WHERE image_id = ?", [image_id])
    for tag in tags:
        tag = tag.strip()
        if tag:
            await ldb.execute("INSERT OR IGNORE INTO tags (image_id, tag) VALUES (?, ?)", [image_id, tag])
    await ldb.commit()
    return {"ok": True}


@app.get("/api/labeler/export")
async def export_liked(
    verdict: str = Query("liked", pattern="^(liked|disliked|skipped)$"),
    tag: Optional[str] = Query(None),
):
    """Export liked (or filtered) images as a ZIP archive streamed to the client."""
    db = await get_db()
    ldb = await get_labels_db_async()

    conditions = ["l.verdict = ?"]
    params: list = [verdict]

    if tag:
        conditions.append("l.image_id IN (SELECT image_id FROM tags WHERE tag = ?)")
        params.append(tag)

    where = " AND ".join(conditions)

    async with ldb.execute(f"SELECT image_id FROM labels l WHERE {where}", params) as c:
        image_ids = [r[0] for r in await c.fetchall()]

    if not image_ids:
        raise HTTPException(status_code=404, detail="No images found for export")

    placeholders = ",".join("?" * len(image_ids))
    async with db.execute(
        f"SELECT id, file_path, source, source_id FROM images WHERE id IN ({placeholders}) AND file_path IS NOT NULL",
        image_ids,
    ) as c:
        rows = await c.fetchall()

    # Fetch tags
    async with ldb.execute(
        f"SELECT image_id, tag FROM tags WHERE image_id IN ({placeholders})", image_ids
    ) as c:
        tag_rows = await c.fetchall()

    tags_map: dict[int, list[str]] = {}
    for r in tag_rows:
        tags_map.setdefault(r[0], []).append(r[1])

    # Build metadata JSON
    metadata = []
    file_entries = []
    for r in rows:
        fp = r["file_path"]
        full_path = CRAWLER_DIR / fp
        if full_path.exists():
            file_entries.append((r["id"], fp, full_path))
            metadata.append({
                "id": r["id"],
                "source": r["source"],
                "source_id": r["source_id"],
                "file_path": fp,
                "filename": Path(fp).name,
                "tags": tags_map.get(r["id"], []),
            })

    if not file_entries:
        raise HTTPException(status_code=404, detail="No image files found on disk")

    def _build_zip():
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_STORED) as zf:
            # Add metadata
            zf.writestr("metadata.json", json.dumps(metadata, ensure_ascii=False, indent=2))
            # Add images
            for img_id, fp, full_path in file_entries:
                arcname = f"images/{Path(fp).name}"
                # Deduplicate filenames
                base = Path(fp).stem
                ext = Path(fp).suffix
                counter = 1
                while arcname in [info.filename for info in zf.filelist]:
                    arcname = f"images/{base}_{counter}{ext}"
                    counter += 1
                zf.write(full_path, arcname)
        buf.seek(0)
        return buf

    loop = asyncio.get_event_loop()
    zip_buf = await loop.run_in_executor(None, _build_zip)

    tag_suffix = f"_{tag}" if tag else ""
    filename = f"booru_{verdict}{tag_suffix}_{len(file_entries)}imgs.zip"

    return StreamingResponse(
        zip_buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# Prefetch Candidates Process Control (AI pre-screening)
# ---------------------------------------------------------------------------

_prefetch_process: Optional[subprocess.Popen] = None
_prefetch_lock = asyncio.Lock()

PREFETCH_SCRIPT = PROJECT_ROOT / "classifier" / "prefetch_candidates.py"


def _is_prefetch_running() -> bool:
    """Check if the prefetch_candidates process is running (ours or any)."""
    global _prefetch_process
    if _prefetch_process is not None:
        ret = _prefetch_process.poll()
        if ret is None:
            return True
        _prefetch_process = None
    try:
        result = subprocess.run(
            ["pgrep", "-f", "prefetch_candidates.py"],
            capture_output=True, timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return False


@app.get("/api/danbooru/prefetch/status")
async def prefetch_status():
    """Get AI pre-screening process status."""
    running = await asyncio.to_thread(_is_prefetch_running)
    return {"running": running}


@app.post("/api/danbooru/prefetch/start")
async def prefetch_start():
    """Start the AI pre-screening process."""
    global _prefetch_process
    async with _prefetch_lock:
        if _is_prefetch_running():
            return {"running": True, "message": "已在运行"}
        try:
            _prefetch_log = open(Path(__file__).parent / "prefetch.log", "a")
            _prefetch_process = subprocess.Popen(
                [
                    "nice", "-n", "15",
                    "ionice", "-c", "3",
                    str(Path(__file__).parent / "venv" / "bin" / "python"),
                    "-u",
                    str(PREFETCH_SCRIPT),
                ],
                cwd=str(PREFETCH_SCRIPT.parent),
                stdout=_prefetch_log,
                stderr=_prefetch_log,
                start_new_session=True,
            )
            await asyncio.sleep(1.0)
            if _prefetch_process.poll() is not None:
                code = _prefetch_process.returncode
                _prefetch_process = None
                return {"running": False, "message": f"启动失败 (exit code {code})"}
            return {"running": True, "message": "已启动"}
        except Exception as e:
            return {"running": False, "message": f"启动失败: {e}"}


@app.post("/api/danbooru/prefetch/stop")
async def prefetch_stop():
    """Stop the AI pre-screening process."""
    global _prefetch_process
    async with _prefetch_lock:
        killed = False
        if _prefetch_process is not None and _prefetch_process.poll() is None:
            try:
                os.killpg(os.getpgid(_prefetch_process.pid), signal.SIGTERM)
                _prefetch_process.wait(timeout=10)  # give time to save progress
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(os.getpgid(_prefetch_process.pid), signal.SIGKILL)
                except Exception:
                    pass
            except Exception:
                pass
            _prefetch_process = None
            killed = True
        # Also kill any externally-started prefetch
        try:
            subprocess.run(["pkill", "-f", "prefetch_candidates.py"], timeout=5)
            killed = True
        except Exception:
            pass
        return {"running": False, "stopped": killed}


# ---------------------------------------------------------------------------
# Auto-Tags APIs (WD14 tagger results)
# ---------------------------------------------------------------------------

@app.get("/api/autotags/stats")
async def auto_tags_stats():
    """Get auto-tagging progress stats."""
    db = await get_db()
    ldb = await get_labels_db_async()

    async with ldb.execute("SELECT COUNT(*) FROM auto_tags WHERE top_tags != '_error'") as c:
        tagged = (await c.fetchone())[0]

    async with ldb.execute("SELECT COUNT(*) FROM auto_tags WHERE top_tags = '_error'") as c:
        errored = (await c.fetchone())[0]

    async with db.execute(
        "SELECT COUNT(*) FROM images WHERE file_path IS NOT NULL AND file_path NOT LIKE '%.mp4' AND file_path NOT LIKE '%.webm' AND file_path NOT LIKE '%.mkv'"
    ) as c:
        total_raw = (await c.fetchone())[0]

    # Exclude corrupted/unreadable files from the total
    total = total_raw - errored

    # Top 50 most common auto-tags across all images (excluding errors)
    async with ldb.execute("SELECT general_json FROM auto_tags WHERE top_tags != '_error'") as c:
        rows = await c.fetchall()

    tag_counts: dict[str, int] = {}
    for r in rows:
        try:
            tags = json.loads(r[0])
            for tag in tags:
                tag_counts[tag] = tag_counts.get(tag, 0) + 1
        except Exception:
            pass

    top_tags = sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)[:50]

    # Per-source error breakdown
    errors_by_source: dict[str, int] = {}
    if errored > 0:
        async with ldb.execute("SELECT image_id FROM auto_tags WHERE top_tags = '_error'") as c:
            error_ids = [r[0] for r in await c.fetchall()]
        for i in range(0, len(error_ids), 500):
            batch = error_ids[i:i+500]
            placeholders = ",".join("?" * len(batch))
            async with db.execute(
                f"SELECT source, COUNT(*) FROM images WHERE id IN ({placeholders}) GROUP BY source",
                batch,
            ) as c:
                for r in await c.fetchall():
                    errors_by_source[r[0]] = errors_by_source.get(r[0], 0) + r[1]

    return {
        "tagged": tagged,
        "total": total,
        "remaining": total - tagged,
        "progress_pct": round(tagged / total * 100, 1) if total > 0 else 0,
        "top_tags": [{"tag": t, "count": c} for t, c in top_tags],
        "errored": errored,
        "errors_by_source": dict(sorted(errors_by_source.items(), key=lambda x: x[1], reverse=True)),
    }


@app.get("/api/autotags/search")
async def search_by_auto_tag(
    tag: str = Query(..., min_length=1),
    page: int = Query(1, ge=1),
    per_page: int = Query(60, ge=1, le=200),
):
    """Search images by auto-generated tag."""
    ldb = await get_labels_db_async()
    db = await get_db()

    # Find image IDs whose general_json or character_json contains the tag
    # We search top_tags for quick text matching
    pattern = f"%{tag}%"
    offset = (page - 1) * per_page

    async with ldb.execute(
        "SELECT COUNT(*) FROM auto_tags WHERE top_tags LIKE ?", [pattern]
    ) as c:
        total = (await c.fetchone())[0]

    async with ldb.execute(
        "SELECT image_id, top_tags FROM auto_tags WHERE top_tags LIKE ? ORDER BY image_id DESC LIMIT ? OFFSET ?",
        [pattern, per_page, offset],
    ) as c:
        tag_rows = await c.fetchall()

    if not tag_rows:
        return {"images": [], "total": total, "page": page, "per_page": per_page, "pages": 0}

    image_ids = [r[0] for r in tag_rows]
    tags_map = {r[0]: r[1] for r in tag_rows}

    placeholders = ",".join("?" * len(image_ids))
    async with db.execute(
        f"SELECT id, source, source_id, file_path, url, created_at FROM images WHERE id IN ({placeholders})",
        image_ids,
    ) as c:
        img_rows = await c.fetchall()

    img_map = {r["id"]: r for r in img_rows}

    images = []
    for iid in image_ids:
        r = img_map.get(iid)
        if not r:
            continue
        fp = r["file_path"]
        ext = Path(fp).suffix.lower() if fp else ""
        parts = (fp or "").split("/")
        images.append({
            "id": r["id"],
            "source": r["source"],
            "file_path": fp,
            "created_at": r["created_at"],
            "date": parts[1] if len(parts) >= 2 else None,
            "is_video": ext in VIDEO_EXTS,
            "thumb_url": f"/api/thumb/{fp}",
            "auto_tags": tags_map.get(iid, ""),
        })

    return {
        "images": images,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page if total > 0 else 0,
    }


@app.get("/api/autotags/batch")
async def batch_auto_tags(ids: str = Query(..., description="Comma-separated image IDs")):
    """Get auto-tags for multiple images at once (for gallery view)."""
    try:
        image_ids = [int(x.strip()) for x in ids.split(",") if x.strip()][:200]
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid image IDs")

    if not image_ids:
        return {"tags": {}}

    ldb = await get_labels_db_async()
    placeholders = ",".join("?" * len(image_ids))
    async with ldb.execute(
        f"SELECT image_id, top_tags, rating_json FROM auto_tags WHERE image_id IN ({placeholders})",
        image_ids,
    ) as c:
        rows = await c.fetchall()

    result = {}
    for r in rows:
        try:
            rating = json.loads(r[2])
            top_rating = max(rating.items(), key=lambda x: x[1])[0] if rating else ""
        except Exception:
            top_rating = ""
        result[str(r[0])] = {"top_tags": r[1], "rating": top_rating}

    return {"tags": result}


@app.get("/api/autotags/{image_id}")
async def get_auto_tags(image_id: int):
    """Get auto-generated tags for an image."""
    ldb = await get_labels_db_async()
    async with ldb.execute(
        "SELECT rating_json, general_json, character_json, top_tags, model_name, general_threshold, created_at FROM auto_tags WHERE image_id = ?",
        [image_id],
    ) as c:
        row = await c.fetchone()
    if not row:
        return {"found": False, "image_id": image_id}
    return {
        "found": True,
        "image_id": image_id,
        "rating": json.loads(row[0]),
        "general": json.loads(row[1]),
        "characters": json.loads(row[2]),
        "top_tags": row[3],
        "model_name": row[4],
        "threshold": row[5],
        "created_at": row[6],
    }


# ---------------------------------------------------------------------------
# Danbooru Proxy APIs
# ---------------------------------------------------------------------------

@app.get("/api/danbooru/search")
async def danbooru_search(request: Request):
    """Proxy DanbooruFinder /search endpoint."""
    client = get_danbooru_client()
    try:
        resp = await client.get("/search", params=dict(request.query_params))
        return resp.json()
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"DanbooruFinder error: {e}")


@app.get("/api/danbooru/preview/{image_id}.{ext}")
async def danbooru_preview(image_id: int, ext: str):
    """Proxy DanbooruFinder /preview/<id>.<ext> with streaming."""
    client = get_danbooru_client()
    try:
        resp = await client.get(f"/preview/{image_id}.{ext}")
        if resp.status_code != 200:
            raise HTTPException(status_code=resp.status_code, detail="Upstream error")
        return StreamingResponse(
            iter([resp.content]),
            media_type=resp.headers.get("content-type", "image/jpeg"),
            headers={"Cache-Control": "public, max-age=86400, immutable"},
        )
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"DanbooruFinder error: {e}")


@app.get("/api/danbooru/thumbnail/{image_id}.{ext}")
async def danbooru_thumbnail(image_id: int, ext: str):
    """Proxy DanbooruFinder /thumbnail/<id>.<ext> with streaming."""
    client = get_danbooru_client()
    try:
        resp = await client.get(f"/thumbnail/{image_id}.{ext}")
        if resp.status_code != 200:
            raise HTTPException(status_code=resp.status_code, detail="Upstream error")
        return StreamingResponse(
            iter([resp.content]),
            media_type=resp.headers.get("content-type", "image/webp"),
            headers={"Cache-Control": "public, max-age=86400, immutable"},
        )
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"DanbooruFinder error: {e}")


@app.get("/api/danbooru/video_preview/{image_id}.{ext}")
async def danbooru_video_preview(image_id: int, ext: str):
    """Proxy DanbooruFinder /video_preview/<id>.<ext> with streaming."""
    client = get_danbooru_client()
    try:
        resp = await client.get(f"/video_preview/{image_id}.{ext}")
        if resp.status_code != 200:
            raise HTTPException(status_code=resp.status_code, detail="Upstream error")
        return StreamingResponse(
            iter([resp.content]),
            media_type=resp.headers.get("content-type", "video/mp4"),
            headers={"Cache-Control": "public, max-age=86400, immutable"},
        )
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"DanbooruFinder error: {e}")


# ---------------------------------------------------------------------------
# Danbooru AI Recommendation API
# ---------------------------------------------------------------------------

def _cnn_score_image(image_path: str | Path) -> float | None:
    """Score a single image using the CNN model. Returns probability of 'liked'."""
    if _cnn_model is None:
        return None
    try:
        import torch
        from PIL import Image as PILImage
        img = PILImage.open(image_path).convert('RGB')
        tensor = _cnn_model['transform'](img).unsqueeze(0)
        with torch.no_grad():
            logit = _cnn_model['model'](tensor).squeeze()
            prob = torch.sigmoid(logit).item()
        return prob
    except Exception:
        return None


def _fused_score(tag_score: float, cnn_score: float | None, tag_weight: float = 0.5) -> float:
    """Fuse XGBoost tag score and CNN image score."""
    if cnn_score is None:
        return tag_score
    return tag_weight * tag_score + (1 - tag_weight) * cnn_score


def _build_preference_features(tags_str: str, rating: str, model_data: dict) -> np.ndarray:
    """Build feature vector for a Danbooru image (matches train_classifier.py logic)."""
    tag_vocab = model_data['tag_vocab']
    feature_names = model_data['feature_names']
    n_features = len(feature_names)

    x = np.zeros(n_features, dtype=np.float32)
    # Danbooru tags may be comma-separated or space-separated, with underscores
    raw_tags = [t.strip().strip(',') for t in tags_str.split()] if tags_str else []
    # WD14 vocab uses spaces for multi-word tags; Danbooru uses underscores
    # Try both: original (with underscores) and underscores→spaces
    image_tags = set()
    for t in raw_tags:
        image_tags.add(t)
        image_tags.add(t.replace('_', ' '))

    # Tag features (binary)
    tag_to_idx = {t: i for i, t in enumerate(tag_vocab)}
    matched = 0
    for tag in image_tags:
        if tag in tag_to_idx:
            x[tag_to_idx[tag]] = 1.0
            matched += 1

    # Rating features (4 dims)
    n_tags = len(tag_vocab)
    rating_map = {'general': 0, 'sensitive': 1, 'questionable': 2, 'explicit': 3}
    rating_full = {'g': 'general', 's': 'sensitive', 'q': 'questionable', 'e': 'explicit'}
    rating_name = rating_full.get(rating, '')
    if rating_name in rating_map:
        x[n_tags + rating_map[rating_name]] = 1.0

    # Meta features
    x[n_tags + 4] = len(raw_tags)  # tag_count (original count, not doubled)
    x[n_tags + 5] = 1.0  # max_confidence
    return x


@app.get("/api/danbooru/recommended")
async def danbooru_recommended(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    min_score: float = Query(0.5, ge=0, le=1),
    rating: Optional[str] = Query(None),
):
    """Get AI-recommended Danbooru images sorted by preference score."""
    if _preference_model is None:
        raise HTTPException(status_code=503, detail="Preference model not loaded")

    model = _preference_model['model']
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
                "auc": _preference_model.get("auc", 0),
                "n_samples": _preference_model.get("n_samples", 0),
                "model_type": _preference_model.get("model_type", "unknown"),
            },
        }

    # Build features and predict
    X = np.array([
        _build_preference_features(img.get("tags", ""), img.get("rating", ""), _preference_model)
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
            "auc": _preference_model.get("auc", 0),
            "n_samples": _preference_model.get("n_samples", 0),
            "model_type": _preference_model.get("model_type", "unknown"),
        },
    }


# CANDIDATES_DB_PATH is imported from config


@app.get("/api/danbooru/candidates/stats")
async def danbooru_candidates_stats():
    """Get AI pre-screening candidate statistics."""
    if not CANDIDATES_DB_PATH.exists():
        return {
            "total": 0, "pending": 0, "labeled": 0,
            "score_distribution": {},
            "rating_distribution": {},
            "model_loaded": _preference_model is not None,
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

        conn.close()
        return {
            "total": total, "pending": pending, "labeled": labeled,
            "score_distribution": score_dist,
            "rating_distribution": rating_dist,
            "avg_score": round(avg, 4),
            "top_score": round(top, 4),
            "model_loaded": _preference_model is not None,
            "model_auc": _preference_model.get("auc", 0) if _preference_model else 0,
            "model_samples": _preference_model.get("n_samples", 0) if _preference_model else 0,
            "cnn_loaded": _cnn_model is not None,
            "cnn_auc": _cnn_model['cv_auc'] if _cnn_model else 0,
        }

    return await loop.run_in_executor(None, _query)


# ---------------------------------------------------------------------------
# Danbooru Candidates (AI pre-screened) APIs
# ---------------------------------------------------------------------------

@app.get("/api/danbooru/candidates/next")
async def danbooru_candidates_next(
    rating: Optional[str] = Query(None),
    media: Optional[str] = Query(None),
    min_score: float = Query(0.0, ge=0, le=1),
):
    """Get next AI-recommended candidate for review (highest score first)."""
    if not CANDIDATES_DB_PATH.exists():
        return {"image": None, "remaining": 0, "total_labeled": 0}

    dldb = await get_danbooru_labels_db()
    async with dldb.execute("SELECT image_id FROM labels") as c:
        labeled_ids = {r[0] for r in await c.fetchall()}

    loop = asyncio.get_event_loop()

    # Convert labeled_ids to a frozenset for the closure
    _labeled_ids = frozenset(labeled_ids)

    def _query():
        conn = sqlite3.connect(str(CANDIDATES_DB_PATH), timeout=30)
        cur = conn.cursor()

        # Build query — filter media type and already-labeled at SQL level
        where = ["status = 'pending'"]
        params_list: list = []
        if min_score > 0:
            where.append("preference_score >= ?")
            params_list.append(min_score)
        if rating:
            where.append("rating = ?")
            params_list.append(rating)
        if media == "image":
            where.append("ext NOT IN ('mp4', 'webm', 'zip')")
        elif media == "video":
            where.append("ext IN ('mp4', 'webm', 'zip')")

        # Exclude already-labeled ids
        if _labeled_ids:
            placeholders = ",".join("?" * len(_labeled_ids))
            where.append(f"image_id NOT IN ({placeholders})")
            params_list.extend(_labeled_ids)

        where_str = " AND ".join(where)
        cur.execute(f"SELECT image_id, ext, score, rating, tags, preference_score FROM candidates WHERE {where_str} ORDER BY preference_score DESC LIMIT 1", params_list)
        row = cur.fetchone()

        # Count remaining
        cur.execute(f"SELECT COUNT(*) FROM candidates WHERE {where_str}", params_list)
        remaining = cur.fetchone()[0]

        conn.close()
        return row, remaining

    row, remaining = await loop.run_in_executor(None, _query)

    if row:
        img_id, ext, score, img_rating, tags_str, pref_score = row
        is_video = ext in ("mp4", "webm", "zip")

        # Parse tag_categories from DanbooruFinder if needed
        tag_list = [t.strip().strip(',') for t in (tags_str or "").split() if t.strip()]
        tag_categories = {"general": tag_list}

        return {
            "image": {
                "id": img_id,
                "ext": ext or "jpg",
                "score": score or 0,
                "rating": img_rating or "",
                "created_at": "",
                "file_size": 0,
                "tags": tags_str or "",
                "tag_categories": tag_categories,
                "is_video": is_video,
                "thumb_url": f"/api/danbooru/thumbnail/{img_id}.{ext or 'jpg'}",
                "preview_url": f"/api/danbooru/preview/{img_id}.{ext or 'jpg'}",
                "video_url": f"/api/danbooru/video_preview/{img_id}.{ext or 'jpg'}" if is_video else None,
                "preference_score": float(pref_score),
            },
            "remaining": remaining,
            "total_labeled": len(labeled_ids),
        }

    return {"image": None, "remaining": 0, "total_labeled": len(labeled_ids)}


@app.post("/api/danbooru/candidates/{image_id}/mark")
async def danbooru_candidates_mark(image_id: int):
    """Mark a candidate as labeled after the user reviews it."""
    if not CANDIDATES_DB_PATH.exists():
        return {"ok": True}
    loop = asyncio.get_event_loop()
    def _mark():
        conn = sqlite3.connect(str(CANDIDATES_DB_PATH), timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("UPDATE candidates SET status='labeled' WHERE image_id=?", (image_id,))
        conn.commit()
        conn.close()
    await loop.run_in_executor(None, _mark)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Danbooru Labeler APIs (independent from crawler labeler)
# ---------------------------------------------------------------------------

class DanbooruLabelRequest(BaseModel):
    verdict: str  # liked, disliked, skipped
    tags: list[str] = []
    ext: str = ""
    score: int = 0
    rating: str = ""
    danbooru_tags: str = ""  # JSON string of original danbooru tags


@app.get("/api/danbooru/labeler/next")
async def danbooru_labeler_next(
    rating: Optional[str] = Query(None),
    min_score: Optional[int] = Query(None),
    media: Optional[str] = Query(None),
):
    """Get the next unlabeled danbooru image for review."""
    dldb = await get_danbooru_labels_db()

    # Get all labeled image IDs
    async with dldb.execute("SELECT image_id FROM labels") as c:
        labeled_ids = {r[0] for r in await c.fetchall()}

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
                    "video_url": f"/api/danbooru/video_preview/{item['id']}.{item.get('ext', 'jpg')}" if is_video else None,
                },
                "remaining": pagination.get("total", 0),
                "total_labeled": len(labeled_ids),
            }

    return {"image": None, "remaining": 0, "total_labeled": len(labeled_ids)}


@app.post("/api/danbooru/labeler/{image_id}")
async def danbooru_label_image(image_id: int, req: DanbooruLabelRequest):
    """Label a danbooru image as liked/disliked/skipped."""
    if req.verdict not in ("liked", "disliked", "skipped"):
        raise HTTPException(status_code=400, detail="verdict must be liked, disliked, or skipped")

    dldb = await get_danbooru_labels_db()
    await dldb.execute(
        """INSERT INTO labels (image_id, verdict, ext, score, rating, tags, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
           ON CONFLICT(image_id) DO UPDATE SET
             verdict=excluded.verdict, ext=excluded.ext, score=excluded.score,
             rating=excluded.rating, tags=excluded.tags, updated_at=CURRENT_TIMESTAMP""",
        [image_id, req.verdict, req.ext, req.score, req.rating, req.danbooru_tags],
    )

    # Handle user-added tags
    if req.tags:
        for tag in req.tags:
            tag = tag.strip()
            if tag:
                await dldb.execute(
                    "INSERT OR IGNORE INTO tags (image_id, tag) VALUES (?, ?)",
                    [image_id, tag],
                )

    await dldb.commit()

    # Auto-download liked images / remove if verdict changed away from liked
    if req.verdict == "liked" and req.ext:
        asyncio.create_task(_download_danbooru_liked(image_id, req.ext))
    else:
        asyncio.create_task(_remove_danbooru_liked(image_id))

    return {"ok": True}


async def _download_danbooru_liked(image_id: int, ext: str):
    """Download original image from DanbooruFinder to local likes folder."""
    try:
        DANBOORU_LIKES_DIR.mkdir(parents=True, exist_ok=True)
        dest = DANBOORU_LIKES_DIR / f"{image_id}.{ext}"
        if dest.exists():
            return
        client = get_danbooru_client()
        resp = await client.get(f"/preview/{image_id}.{ext}")
        if resp.status_code == 200:
            dest.write_bytes(resp.content)
    except Exception as e:
        print(f"[danbooru_likes] Failed to download {image_id}.{ext}: {e}")


async def _remove_danbooru_liked(image_id: int):
    """Remove a previously downloaded liked image (on unlabel or verdict change)."""
    try:
        if not DANBOORU_LIKES_DIR.exists():
            return
        for f in DANBOORU_LIKES_DIR.glob(f"{image_id}.*"):
            f.unlink()
    except Exception as e:
        print(f"[danbooru_likes] Failed to remove {image_id}: {e}")


@app.delete("/api/danbooru/labeler/{image_id}")
async def danbooru_unlabel_image(image_id: int):
    """Remove label for a danbooru image (undo)."""
    dldb = await get_danbooru_labels_db()
    # Remove local file if it was liked
    asyncio.create_task(_remove_danbooru_liked(image_id))
    await dldb.execute("DELETE FROM labels WHERE image_id = ?", [image_id])
    await dldb.execute("DELETE FROM tags WHERE image_id = ?", [image_id])
    await dldb.commit()
    return {"ok": True}


@app.get("/api/danbooru/labeler/stats")
async def danbooru_labeler_stats():
    """Get danbooru labeling statistics."""
    dldb = await get_danbooru_labels_db()

    stats = {"total_images": 0, "liked": 0, "disliked": 0, "skipped": 0}

    # Get total from DanbooruFinder
    client = get_danbooru_client()
    try:
        resp = await client.get("/search", params={"per_page": "1"})
        data = resp.json()
        stats["total_images"] = data.get("pagination", {}).get("total", 0)
    except httpx.HTTPError:
        pass

    async with dldb.execute("SELECT verdict, COUNT(*) FROM labels GROUP BY verdict") as c:
        for r in await c.fetchall():
            stats[r[0]] = r[1]

    stats["total_labeled"] = stats["liked"] + stats["disliked"] + stats["skipped"]
    stats["remaining"] = stats["total_images"] - stats["total_labeled"]

    # Top user tags
    async with dldb.execute("SELECT tag, COUNT(*) as cnt FROM tags GROUP BY tag ORDER BY cnt DESC LIMIT 50") as c:
        stats["top_tags"] = [{"tag": r[0], "count": r[1]} for r in await c.fetchall()]

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
    async with dldb.execute(
        "SELECT tags FROM labels WHERE verdict = 'liked' AND tags IS NOT NULL AND tags != ''"
    ) as c:
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


@app.get("/api/danbooru/labeler/history")
async def danbooru_labeler_history(
    verdict: Optional[str] = Query(None, pattern="^(liked|disliked|skipped)$"),
    tag: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(60, ge=1, le=200),
):
    """Get danbooru labeled images history."""
    dldb = await get_danbooru_labels_db()

    conditions = ["1=1"]
    params: list = []

    if verdict:
        conditions.append("l.verdict = ?")
        params.append(verdict)

    if tag:
        conditions.append("l.image_id IN (SELECT image_id FROM tags WHERE tag = ?)")
        params.append(tag)

    where = " AND ".join(conditions)
    offset = (page - 1) * per_page

    async with dldb.execute(f"SELECT COUNT(*) FROM labels l WHERE {where}", params) as c:
        total = (await c.fetchone())[0]

    async with dldb.execute(
        f"""SELECT l.image_id, l.verdict, l.ext, l.score, l.rating, l.tags, l.updated_at
            FROM labels l WHERE {where} ORDER BY l.updated_at DESC LIMIT ? OFFSET ?""",
        params + [per_page, offset],
    ) as c:
        label_rows = await c.fetchall()

    if not label_rows:
        return {"images": [], "total": total, "page": page, "per_page": per_page, "pages": 0}

    image_ids = [r[0] for r in label_rows]

    # Fetch user tags
    placeholders = ",".join("?" * len(image_ids))
    async with dldb.execute(
        f"SELECT image_id, tag FROM tags WHERE image_id IN ({placeholders})",
        image_ids,
    ) as c:
        tag_rows = await c.fetchall()

    tags_map: dict[int, list[str]] = {}
    for r in tag_rows:
        tags_map.setdefault(r[0], []).append(r[1])

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

        images.append({
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
        })

    return {
        "images": images,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page if total > 0 else 0,
    }


@app.get("/api/danbooru/labeler/export")
async def danbooru_export_liked(
    verdict: str = Query("liked", pattern="^(liked|disliked|skipped)$"),
    tag: Optional[str] = Query(None),
):
    """Export danbooru labeled images as a ZIP archive (downloads from DanbooruFinder)."""
    dldb = await get_danbooru_labels_db()

    conditions = ["l.verdict = ?"]
    params: list = [verdict]

    if tag:
        conditions.append("l.image_id IN (SELECT image_id FROM tags WHERE tag = ?)")
        params.append(tag)

    where = " AND ".join(conditions)

    async with dldb.execute(
        f"SELECT image_id, ext, score, rating, tags FROM labels l WHERE {where}", params
    ) as c:
        rows = await c.fetchall()

    if not rows:
        raise HTTPException(status_code=404, detail="No images found for export")

    # Fetch user tags
    image_ids = [r[0] for r in rows]
    placeholders = ",".join("?" * len(image_ids))
    async with dldb.execute(
        f"SELECT image_id, tag FROM tags WHERE image_id IN ({placeholders})", image_ids
    ) as c:
        tag_rows = await c.fetchall()

    tags_map: dict[int, list[str]] = {}
    for r in tag_rows:
        tags_map.setdefault(r[0], []).append(r[1])

    client = get_danbooru_client()

    # Download images and build ZIP
    metadata = []
    image_data: list[tuple[str, bytes]] = []

    for r in rows:
        img_id, ext, score, rating, danbooru_tags = r[0], r[1] or "jpg", r[2], r[3], r[4]
        try:
            resp = await client.get(f"/preview/{img_id}.{ext}")
            if resp.status_code == 200:
                filename = f"{img_id}.{ext}"
                image_data.append((filename, resp.content))
                metadata.append({
                    "id": img_id,
                    "ext": ext,
                    "score": score,
                    "rating": rating,
                    "danbooru_tags": danbooru_tags,
                    "user_tags": tags_map.get(img_id, []),
                    "filename": filename,
                })
        except httpx.HTTPError:
            continue

    if not image_data:
        raise HTTPException(status_code=404, detail="No image files could be downloaded")

    def _build_zip():
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_STORED) as zf:
            zf.writestr("metadata.json", json.dumps(metadata, ensure_ascii=False, indent=2))
            for filename, data in image_data:
                zf.writestr(f"images/{filename}", data)
        buf.seek(0)
        return buf

    loop = asyncio.get_event_loop()
    zip_buf = await loop.run_in_executor(None, _build_zip)

    tag_suffix = f"_{tag}" if tag else ""
    filename = f"danbooru_{verdict}{tag_suffix}_{len(image_data)}imgs.zip"

    return StreamingResponse(
        zip_buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# ML Model Management APIs
# ---------------------------------------------------------------------------

@app.get("/api/ml/models")
async def ml_models_info():
    """Get preference classifier models info."""
    xgboost_info = None
    cnn_info = None
    if _preference_model is not None:
        xgboost_info = {
            "loaded": True,
            "auc": _preference_model.get("auc", 0),
            "n_samples": _preference_model.get("n_samples", 0),
            "n_liked": _preference_model.get("n_liked", 0),
            "n_disliked": _preference_model.get("n_disliked", 0),
            "model_type": _preference_model.get("model_type", "unknown"),
            "vocab_size": len(_preference_model.get("tag_vocab", [])),
        }
    if _cnn_model is not None:
        cnn_info = {
            "loaded": True,
            "model_name": _cnn_model.get("model_name", "unknown"),
            "cv_auc": _cnn_model.get("cv_auc", 0),
            "n_samples": _cnn_model.get("n_samples", 0),
            "input_size": _cnn_model.get("input_size", 224),
            "fold_aucs": _cnn_model.get("fold_aucs", []),
        }
    return {"xgboost": xgboost_info, "cnn": cnn_info}


# Retrain XGBoost management
_retrain_process: Optional[subprocess.Popen] = None
_retrain_lock = asyncio.Lock()
RETRAIN_LOG_PATH = Path(__file__).parent / "retrain.log"

RETRAIN_SCRIPT = PROJECT_ROOT / "classifier" / "retrain.sh"


def _is_retrain_running() -> bool:
    """Check if retrain script is running."""
    global _retrain_process
    if _retrain_process is not None:
        ret = _retrain_process.poll()
        if ret is None:
            return True
        _retrain_process = None
    try:
        result = subprocess.run(
            ["pgrep", "-f", "retrain.sh"],
            capture_output=True, timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return False


async def _reload_preference_model():
    """Hot-reload XGBoost model after retrain."""
    global _preference_model
    if PREFERENCE_MODEL_PATH.exists():
        try:
            import joblib
            new_model = joblib.load(PREFERENCE_MODEL_PATH)
            _preference_model = new_model
            print(f"[ml] XGBoost hot-reloaded: AUC={new_model.get('auc', 0):.4f}")
        except Exception as e:
            print(f"[ml] Failed to hot-reload XGBoost: {e}")


@app.post("/api/ml/retrain-xgboost")
async def ml_retrain_start():
    """Start XGBoost retraining."""
    global _retrain_process
    async with _retrain_lock:
        if _is_retrain_running():
            return {"status": "already_running"}
        RETRAIN_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(RETRAIN_LOG_PATH, "w") as log_f:
            log_f.write(f"=== Retrain started at {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
        try:
            _retrain_process = subprocess.Popen(
                ["bash", str(RETRAIN_SCRIPT)],
                cwd=str(RETRAIN_SCRIPT.parent),
                stdout=open(RETRAIN_LOG_PATH, "a"),
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            return {"status": "started"}
        except Exception as e:
            return {"status": "failed", "error": str(e)}


@app.get("/api/ml/retrain-xgboost/status")
async def ml_retrain_status():
    """Get retrain status and latest log."""
    running = await asyncio.to_thread(_is_retrain_running)
    log_content = ""
    if RETRAIN_LOG_PATH.exists():
        try:
            with open(RETRAIN_LOG_PATH, "r") as f:
                log_content = f.read()[-5000:]  # Last 5KB
        except Exception:
            pass
    if not running and _retrain_process is not None:
        exit_code = _retrain_process.poll()
        if exit_code == 0:
            # Success - hot reload model
            await _reload_preference_model()
            return {"running": False, "finished": True, "exit_code": 0, "log": log_content}
        return {"running": False, "finished": True, "exit_code": exit_code, "log": log_content}
    return {"running": running, "finished": False, "exit_code": None, "log": log_content}


# Pack Dataset management
_pack_process: Optional[subprocess.Popen] = None
_pack_lock = asyncio.Lock()
PACK_LOG_PATH = Path(__file__).parent / "pack.log"
PACK_SCRIPT = PROJECT_ROOT / "classifier" / "pack_pipeline.sh"


def _is_pack_running() -> bool:
    """Check if pack script is running."""
    global _pack_process
    if _pack_process is not None:
        ret = _pack_process.poll()
        if ret is None:
            return True
        _pack_process = None
    try:
        result = subprocess.run(
            ["pgrep", "-f", "pack_pipeline.sh"],
            capture_output=True, timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return False


@app.post("/api/ml/pack-dataset")
async def ml_pack_start():
    """Start dataset packing."""
    global _pack_process
    async with _pack_lock:
        if _is_pack_running():
            return {"status": "already_running"}
        PACK_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(PACK_LOG_PATH, "w") as log_f:
            log_f.write(f"=== Pack started at {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
        try:
            _pack_process = subprocess.Popen(
                ["bash", str(PACK_SCRIPT)],
                cwd=str(PACK_SCRIPT.parent),
                stdout=open(PACK_LOG_PATH, "a"),
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            return {"status": "started"}
        except Exception as e:
            return {"status": "failed", "error": str(e)}


@app.get("/api/ml/pack-dataset/status")
async def ml_pack_status():
    """Get pack status and latest log."""
    running = await asyncio.to_thread(_is_pack_running)
    log_content = ""
    if PACK_LOG_PATH.exists():
        try:
            with open(PACK_LOG_PATH, "r") as f:
                log_content = f.read()[-5000:]  # Last 5KB
        except Exception:
            pass
    if not running and _pack_process is not None:
        exit_code = _pack_process.poll()
        return {"running": False, "finished": True, "exit_code": exit_code, "log": log_content}
    return {"running": running, "finished": False, "exit_code": None, "log": log_content}


# ---------------------------------------------------------------------------
# Static file serving
# ---------------------------------------------------------------------------

@app.get("/images/{file_path:path}")
async def serve_image(file_path: str, request: Request):
    for candidate in [file_path, quote(file_path, safe="/")]:
        full_path = CRAWLER_DIR / candidate
        if not _safe_under_crawler(full_path):
            raise HTTPException(status_code=403, detail="Forbidden")
        if full_path.exists():
            return _range_file_response(full_path, request)
    raise HTTPException(status_code=404, detail="File not found")


if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}")
    async def serve_frontend(full_path: str):
        file = FRONTEND_DIST / full_path
        if file.is_file():
            return FileResponse(file)
        return FileResponse(FRONTEND_DIST / "index.html", headers={"Cache-Control": "no-cache"})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=HOST, port=PORT, reload=True)
