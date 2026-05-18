"""Transcode Danbooru-wrapped Pixiv ugoira (.zip with frames + animation.json)
into animated WebP, cached on disk with an LRU size cap.

Routers should never call Pillow / zipfile directly — go through this module.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import threading
import weakref
import zipfile
from functools import lru_cache
from pathlib import Path

import state

logger = logging.getLogger(__name__)

ANIMATION_META = "animation.json"

# Hard cap to keep transcode RAM bounded; Pillow needs all frames in memory
# for animated WebP encoding, so 400 frames of a 4K ugoira can easily exceed
# several GB of RGB pixels.
MAX_FRAMES = 400

# Per-file asyncio locks to prevent concurrent transcodes of the same zip.
# WeakValueDictionary so locks vanish once no coroutine holds a strong ref —
# avoids unbounded growth on long-running servers.
_locks: weakref.WeakValueDictionary[str, asyncio.Lock] = weakref.WeakValueDictionary()

# Serialises cache eviction so two concurrent transcodes don't both compute
# `total` independently and over-evict.
_eviction_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


@lru_cache(maxsize=512)
def _is_ugoira_cached(path_str: str, mtime_ns: int, size: int) -> bool:
    """Inner cache keyed by (path, mtime, size) so edits invalidate."""
    try:
        with zipfile.ZipFile(path_str) as z:
            return ANIMATION_META in z.namelist()
    except (zipfile.BadZipFile, OSError):
        return False


def is_ugoira_zip(path: Path) -> bool:
    """True iff ``path`` is a zip that contains an ``animation.json`` entry."""
    try:
        st = path.stat()
    except OSError:
        return False
    return _is_ugoira_cached(str(path), st.st_mtime_ns, st.st_size)


# ---------------------------------------------------------------------------
# Cache path mapping
# ---------------------------------------------------------------------------


def cache_path_for(relative_file_path: str) -> Path:
    """Return the disk path where the transcoded .webp for ``relative_file_path`` lives.

    ``relative_file_path`` is the same path stored in dedup.db (relative to CRAWLER_DIR,
    e.g. ``downloads/2026-03-17/danbooru/<hash>.zip``).

    Defends against path traversal: even though all current callers verify the
    input against ``_safe_under_crawler`` first, the service contract should
    not trust the caller blindly.
    """
    rel = Path(relative_file_path)
    if rel.is_absolute() or any(part == ".." for part in rel.parts):
        raise ValueError(f"unsafe relative_file_path: {relative_file_path!r}")
    dest = state.ANIMATIONS_DIR / rel.with_suffix(".webp")
    root = state.ANIMATIONS_DIR.resolve()
    if not dest.resolve().is_relative_to(root):
        raise ValueError(f"cache path escapes ANIMATIONS_DIR: {relative_file_path!r}")
    return dest


# ---------------------------------------------------------------------------
# Frame extraction (used by thumbnail route)
# ---------------------------------------------------------------------------


def extract_first_frame_thumb(zip_path: Path, dest: Path, max_width: int = 600) -> Path:
    """Extract the first frame of a ugoira zip and write a JPEG thumbnail to ``dest``.

    Returns the path actually written (``dest`` with a ``.jpg`` suffix). Resizes
    to ``max_width`` if the frame is wider, preserving aspect ratio.
    """
    from PIL import Image

    with zipfile.ZipFile(zip_path) as z:
        meta = json.loads(z.read(ANIMATION_META).decode("utf-8"))
        frames = meta.get("frames") or []
        if not frames:
            raise ValueError(f"ugoira {zip_path} has no frames")
        data = z.read(frames[0]["file"])

    img = Image.open(io.BytesIO(data))
    img.load()
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    if img.width > max_width:
        ratio = max_width / img.width
        new_h = int(img.height * ratio)
        img = img.resize((max_width, new_h), Image.LANCZOS)

    save_path = dest.with_suffix(".jpg")
    save_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(save_path), "JPEG", quality=85, optimize=True)
    return save_path


# ---------------------------------------------------------------------------
# Transcoding
# ---------------------------------------------------------------------------


def transcode_to_webp(zip_path: Path, dest_webp: Path) -> None:
    """Transcode a ugoira zip to an animated WebP at ``dest_webp``.

    Writes to a sibling ``.tmp`` first and atomically renames so partial files
    are never observed. After success, evicts oldest cache files until total
    cache size <= ``state.UGOIRA_CACHE_MAX_BYTES``.
    """
    from PIL import Image

    dest_webp.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest_webp.with_suffix(dest_webp.suffix + ".tmp")

    with zipfile.ZipFile(zip_path) as z:
        meta = json.loads(z.read(ANIMATION_META).decode("utf-8"))
        frames = meta.get("frames") or []
        if not frames:
            raise ValueError(f"ugoira {zip_path} has no frames")
        if len(frames) > MAX_FRAMES:
            raise ValueError(f"ugoira {zip_path} exceeds MAX_FRAMES ({len(frames)} > {MAX_FRAMES})")

        pil_frames = []
        durations: list[int] = []
        for f in frames:
            data = z.read(f["file"])
            img = Image.open(io.BytesIO(data))
            img.load()
            if img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGB")
            pil_frames.append(img)
            durations.append(int(f.get("delay", 100)))

    if not pil_frames:
        raise ValueError(f"ugoira {zip_path} produced no decodable frames")

    pil_frames[0].save(
        tmp,
        format="WebP",
        save_all=True,
        append_images=pil_frames[1:],
        duration=durations,
        loop=0,
        quality=85,
        method=4,
    )
    os.replace(tmp, dest_webp)
    _enforce_cache_limit(protect=dest_webp)


# ---------------------------------------------------------------------------
# LRU eviction
# ---------------------------------------------------------------------------


def _enforce_cache_limit(protect: Path | None = None) -> None:
    """Delete oldest .webp files until total size <= state.UGOIRA_CACHE_MAX_BYTES.

    ``protect`` (the file just written) is never evicted, even if it alone
    exceeds the cap — evicting the very file we just generated would defeat
    the purpose of the cache.

    Serialised via ``_eviction_lock`` so concurrent transcodes don't both
    scan + evict against an outdated view of total size.
    """
    cap = state.UGOIRA_CACHE_MAX_BYTES
    root = state.ANIMATIONS_DIR
    if not root.exists():
        return

    protect_resolved = protect.resolve() if protect else None

    with _eviction_lock:
        entries: list[tuple[float, int, Path]] = []
        total = 0
        for p in root.rglob("*.webp"):
            try:
                st = p.stat()
            except OSError:
                continue
            entries.append((st.st_mtime, st.st_size, p))
            total += st.st_size
        if total <= cap:
            return

        entries.sort()  # oldest mtime first
        for _mtime, size, p in entries:
            if total <= cap:
                break
            if protect_resolved is not None and p.resolve() == protect_resolved:
                continue
            try:
                p.unlink()
                total -= size
            except OSError as e:
                logger.warning("ugoira cache evict failed for %s: %s", p, e)


def touch(path: Path) -> None:
    """Update mtime on a cache hit so LRU ordering reflects recency."""
    try:
        os.utime(path, None)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Async orchestration
# ---------------------------------------------------------------------------


def _get_lock(key: str) -> asyncio.Lock:
    """Return the lock for ``key``, creating it if absent.

    Caller MUST keep a local strong ref to the returned lock for the duration
    of the critical section — the WeakValueDictionary will let it be GC'd
    otherwise. The single-threaded event loop makes the lookup+create+assign
    sequence atomic, so two coroutines racing on the same key will share the
    same lock.
    """
    lock = _locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _locks[key] = lock
    return lock


async def get_or_create_webp(zip_path: Path, relative_file_path: str) -> Path:
    """Return cached WebP path; transcode in executor if missing.

    Caller is expected to have already verified ``is_ugoira_zip(zip_path)``.
    """
    dest = cache_path_for(relative_file_path)
    if dest.exists():
        touch(dest)
        return dest

    lock = _get_lock(relative_file_path)
    async with lock:
        if dest.exists():
            touch(dest)
            return dest
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(state._animation_executor, transcode_to_webp, zip_path, dest)
    return dest


__all__ = [
    "ANIMATION_META",
    "MAX_FRAMES",
    "is_ugoira_zip",
    "extract_first_frame_thumb",
    "transcode_to_webp",
    "cache_path_for",
    "get_or_create_webp",
    "touch",
]
