"""Shared export-zip helper used by labeler / danbooru_labeler export endpoints.

Both endpoints assemble a list of items, build a streaming zip via
``export_utils.build_zip_to_temp``, then wrap the resulting temp file in a
``StreamingResponse`` with the right headers. This module centralises that
last leg so the routers only describe their item shape via callbacks.
"""

from __future__ import annotations

from typing import Callable, Iterable

from fastapi.responses import StreamingResponse

from export_utils import build_zip_to_temp, stream_and_cleanup


async def build_export_zip(
    items: Iterable,
    *,
    max_size: int,
    fetch_bytes: Callable,
    arcname_fn: Callable,
    meta_fn: Callable,
    download_filename: str,
    rename_after: Callable[[int, int], str] | None = None,
) -> tuple[StreamingResponse, int, int]:
    """Build a zip and return ``(StreamingResponse, packed, skipped)``.

    ``rename_after`` lets the caller compute the final download filename once
    ``packed`` is known (danbooru export reports the actual count, while the
    local labeler uses the pre-filtered count).
    """
    tmp_path, dl_filename, packed, skipped = await build_zip_to_temp(
        items,
        max_size=max_size,
        fetch_bytes=fetch_bytes,
        arcname_fn=arcname_fn,
        meta_fn=meta_fn,
        download_filename=download_filename,
    )

    if rename_after is not None:
        dl_filename = rename_after(packed, skipped)

    response = StreamingResponse(
        stream_and_cleanup(tmp_path),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{dl_filename}"'},
    )
    return response, packed, skipped


__all__ = ["build_export_zip"]
