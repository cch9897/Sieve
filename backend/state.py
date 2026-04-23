"""Centralized mutable state and constants for the Sieve backend.

All mutable globals live here so that every module can access them
via attribute lookup (``state.xxx``).  Never bind these with
``from state import _active_model`` — that creates a snapshot.
"""

import asyncio
import concurrent.futures
import subprocess
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Optional

from config import CRAWLER_DIR, PROJECT_ROOT

# ---------------------------------------------------------------------------
# ML model state (loaded in lifespan)
# ---------------------------------------------------------------------------

_preference_model: dict | None = None
_cnn_model: dict | None = None  # backward compat alias

# Multi-model support (lazy loading: metadata at startup, weights on demand)
_models: dict[str, dict] = {}
_active_model: str | None = None
_active_model_lock = threading.Lock()
_loaded_model_key: str | None = None

# ---------------------------------------------------------------------------
# Media type constants
# ---------------------------------------------------------------------------

VIDEO_EXTS = {".mp4", ".webm", ".mkv", ".avi", ".mov"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".avif"}


def video_filter_sql(column: str = "file_path") -> tuple[str, list]:
    """Return (sql_condition, params) for filtering video/image media type.

    Usage:
        sql, params = video_filter_sql()  # returns exclusion condition for images
    """
    conditions = []
    params: list = []
    for ext in sorted(VIDEO_EXTS):
        conditions.append(f"{column} NOT LIKE ?")
        params.append(f"%{ext}")
    return " AND ".join(conditions), params


def video_include_sql(column: str = "file_path") -> tuple[str, list]:
    """Return (sql_condition, params) that matches video files."""
    conditions = []
    params: list = []
    for ext in sorted(VIDEO_EXTS):
        conditions.append(f"{column} LIKE ?")
        params.append(f"%{ext}")
    return " OR ".join(conditions), params

# ---------------------------------------------------------------------------
# Path constants
# ---------------------------------------------------------------------------

FRONTEND_DIST = Path(__file__).parent.parent / "frontend" / "dist"
THUMBS_DIR = CRAWLER_DIR / ".thumbs"
THUMB_WIDTH = 400

# Resolve symlink targets so security checks work with NFS mounts
_ALLOWED_ROOTS = {CRAWLER_DIR.resolve()}
_downloads_link = CRAWLER_DIR / "downloads"
if _downloads_link.is_symlink():
    _ALLOWED_ROOTS.add(_downloads_link.resolve().parent)

# ---------------------------------------------------------------------------
# Inference device
# ---------------------------------------------------------------------------

_inference_device: str = "cpu"
_cuda_available_cached: bool | None = None

# ---------------------------------------------------------------------------
# Subprocess handles & locks  (prefetch / rescore / retrain / pack / vscore / tag-train)
# ---------------------------------------------------------------------------

_prefetch_process: Optional[subprocess.Popen] = None
_prefetch_log_fh = None
_prefetch_lock = asyncio.Lock()

_rescore_process: Optional[subprocess.Popen] = None
_rescore_log_fh = None
_rescore_lock = asyncio.Lock()

_retrain_process: Optional[subprocess.Popen] = None
_retrain_log_fh = None
_retrain_lock = asyncio.Lock()

_pack_process: Optional[subprocess.Popen] = None
_pack_log_fh = None
_pack_lock = asyncio.Lock()

_vscore_process: Optional[subprocess.Popen] = None
_vscore_log_fh = None
_vscore_lock = asyncio.Lock()

_tag_train_process: Optional[subprocess.Popen] = None
_tag_train_log_fh = None
_tag_train_lock = asyncio.Lock()

# ---------------------------------------------------------------------------
# Dedicated thread pool executors (isolate I/O, image, and DB work)
# ---------------------------------------------------------------------------

_image_executor = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="img")
_io_executor = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="io")
_db_executor = concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix="db")

# ---------------------------------------------------------------------------
# Script & log path constants
# ---------------------------------------------------------------------------

PREFETCH_SCRIPT = PROJECT_ROOT / "classifier" / "prefetch_candidates.py"
GPU_CONFIG_PATH = Path(__file__).parent / "gpu_config.json"

RETRAIN_SCRIPT = PROJECT_ROOT / "classifier" / "retrain.sh"
RETRAIN_LOG_PATH = Path(__file__).parent / "retrain.log"

PACK_SCRIPT = PROJECT_ROOT / "classifier" / "pack_pipeline.sh"
PACK_LOG_PATH = Path(__file__).parent / "pack.log"

VSCORE_SCRIPT = Path(__file__).parent / "score_crawler.py"
VSCORE_LOG_PATH = Path(__file__).parent / "vision_score.log"

TAG_TRAIN_SCRIPT = PROJECT_ROOT / "classifier" / "tag_liked_t2i.py"
TAG_TRAIN_LOG_PATH = Path(__file__).parent / "tag_train.log"

RESCORE_LOG_PATH = Path(__file__).parent / "rescore.log"

# ---------------------------------------------------------------------------
# DB connection pools (managed by database.py)
# ---------------------------------------------------------------------------

_db_pool = None       # aiosqlite.Connection for dedup.db (read-only)
_labels_pool = None   # aiosqlite.Connection for labels.db
_danbooru_labels_pool = None  # aiosqlite.Connection for danbooru_labels.db

# ---------------------------------------------------------------------------
# Danbooru HTTP client (managed by database.py)
# ---------------------------------------------------------------------------

_danbooru_client = None  # httpx.AsyncClient, set by database.get_danbooru_client()

# ---------------------------------------------------------------------------
# Background task tracking (prevent GC from dropping fire-and-forget tasks)
# ---------------------------------------------------------------------------

_background_tasks: set = set()

# ---------------------------------------------------------------------------
# Novel meta cache
# ---------------------------------------------------------------------------

_novel_meta_cache: OrderedDict = OrderedDict()
_NOVEL_CACHE_TTL = 300
_NOVEL_CACHE_MAX = 2000

# ---------------------------------------------------------------------------
# Helper functions that only read global state
# ---------------------------------------------------------------------------


def _active_model_db_name() -> str:
    """Get the model_name string stored in DB for the active model."""
    if _active_model and _active_model in _models:
        return _models[_active_model]['model_name']
    return ""


def _model_db_name(key: str) -> str:
    """Get the model_name string stored in DB for a given model key."""
    if key in _models:
        return _models[key]['model_name']
    return key


def _safe_under_crawler(path: Path) -> bool:
    """Check path resolves under CRAWLER_DIR or its symlink targets (prevent traversal)."""
    resolved = path.resolve()
    return any(resolved.is_relative_to(root) for root in _ALLOWED_ROOTS)
