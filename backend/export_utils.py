"""Shared ZIP-export helper for label-based export endpoints.

Both ``/api/labeler/export`` and ``/api/danbooru/labeler/export`` build a ZIP
of labeled images, optionally PIL-resized to a max edge length, with a
``metadata.json`` index. The on-disk source differs (local crawler files vs
HTTP-fetched bytes), so this module exposes a builder that takes the byte
stream from a callback and lets the router decorate the metadata.
"""

from __future__ import annotations

import asyncio
import io
import json
import os
import tempfile
import zipfile
from typing import AsyncIterator, Callable, Iterable

import state


def _resize_to_bytes(raw: bytes, *, max_size: int, fallback_ext: str) -> tuple[bytes, str]:
    """PIL-resize ``raw`` to fit within ``max_size`` (longest edge).

    Returns ``(encoded_bytes, extension_without_dot)``. ``max_size == 0`` skips
    re-encoding and returns the raw bytes unchanged. On PIL failure we also
    fall back to the raw bytes with the ``fallback_ext``.
    """
    if max_size == 0:
        return raw, fallback_ext
    from PIL import Image as _PIL  # local import: PIL is heavy

    _PIL.MAX_IMAGE_PIXELS = 100_000_000
    try:
        img = _PIL.open(io.BytesIO(raw))
        if img.mode in ("RGBA", "P", "LA"):
            out_fmt, out_ext = "PNG", "png"
        else:
            img = img.convert("RGB")
            out_fmt, out_ext = "JPEG", "jpg"
        w, h = img.size
        if max(w, h) > max_size:
            ratio = max_size / max(w, h)
            img = img.resize((int(w * ratio), int(h * ratio)), _PIL.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format=out_fmt, quality=92)
        data = buf.getvalue()
        return data, out_ext
    except Exception:
        return raw, fallback_ext


def _build_zip_sync(
    items: list,
    *,
    max_size: int,
    fetch_bytes: Callable,
    arcname_fn: Callable,
    meta_fn: Callable,
    download_filename: str,
) -> tuple[str, str, int, int]:
    """Synchronous worker that writes a ZIP to a temp file.

    ``items`` is whatever sequence the router prepared (tuples typically).
    ``fetch_bytes(item) -> (raw_bytes_or_None, fallback_ext)`` returns the
    image bytes plus the original extension to use when resize fails.
    ``arcname_fn(item, ext) -> str`` decides the zip-internal path.
    ``meta_fn(item, arcname, final_ext) -> dict`` extends each metadata entry.
    Returns ``(tmp_path, dl_filename, packed, skipped)``.
    """
    tmp_fd = tempfile.NamedTemporaryFile(delete=False, suffix=".zip", dir="/tmp")
    tmp_path = tmp_fd.name
    meta: list[dict] = []
    seen: set[str] = set()
    packed = skipped = 0

    with zipfile.ZipFile(tmp_fd, "w", zipfile.ZIP_STORED) as zf:
        for item in items:
            raw, fallback_ext = fetch_bytes(item)
            if raw is None:
                skipped += 1
                continue
            data, out_ext = _resize_to_bytes(raw, max_size=max_size, fallback_ext=fallback_ext)
            del raw  # free the original copy promptly
            base_arc = arcname_fn(item, out_ext)
            arcname = base_arc
            collision = 1
            while arcname in seen:
                stem, dot, ext = base_arc.rpartition(".")
                if dot:
                    arcname = f"{stem}_{collision}.{ext}"
                else:
                    arcname = f"{base_arc}_{collision}"
                collision += 1
            seen.add(arcname)
            zf.writestr(arcname, data)
            del data
            meta.append(meta_fn(item, arcname, out_ext))
            packed += 1
        zf.writestr("metadata.json", json.dumps(meta, ensure_ascii=False, indent=2))

    return tmp_path, download_filename, packed, skipped


async def build_zip_to_temp(
    items: Iterable,
    *,
    max_size: int,
    fetch_bytes: Callable,
    arcname_fn: Callable,
    meta_fn: Callable,
    download_filename: str,
) -> tuple[str, str, int, int]:
    """Run :func:`_build_zip_sync` on the shared I/O executor.

    Returns the same ``(tmp_path, dl_filename, packed, skipped)`` tuple. The
    caller is responsible for unlinking ``tmp_path`` once the response stream
    finishes (or on early failure).
    """
    items_list = list(items)
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        state._io_executor,
        lambda: _build_zip_sync(
            items_list,
            max_size=max_size,
            fetch_bytes=fetch_bytes,
            arcname_fn=arcname_fn,
            meta_fn=meta_fn,
            download_filename=download_filename,
        ),
    )


async def stream_and_cleanup(tmp_path: str) -> AsyncIterator[bytes]:
    """Yield 1MiB chunks from ``tmp_path``, then unlink it."""
    try:
        with open(tmp_path, "rb") as f:
            while chunk := f.read(1024 * 1024):
                yield chunk
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


__all__ = [
    "build_zip_to_temp",
    "stream_and_cleanup",
]
