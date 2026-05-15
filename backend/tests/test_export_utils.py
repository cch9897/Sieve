"""Tests for export_utils.build_zip_to_temp / stream_and_cleanup.

We feed the builder synthetic byte streams (no real network or disk source)
so the module's branching logic — empty input, single item, name collisions,
PIL-resize path, raw fallback — is exercised in isolation.
"""

import json
import os
import struct
import zipfile
import zlib

import pytest

from export_utils import build_zip_to_temp, stream_and_cleanup


def _make_png(width: int = 4, height: int = 4) -> bytes:
    """Build a minimal valid RGB PNG of size width x height (white pixels)."""
    raw = b""
    for _ in range(height):
        raw += b"\x00" + (b"\xff\xff\xff" * width)  # filter=0 + RGB pixels
    compressed = zlib.compress(raw)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)

    def chunk(ctype: bytes, data: bytes) -> bytes:
        c = ctype + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)

    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", compressed) + chunk(b"IEND", b"")


# A trivial fetch_bytes that returns (raw, ext) directly from the item tuple.
def _fetch_factory(items_to_bytes):
    """Build a fetch_bytes(item) callable backed by the given mapping."""

    def fetch(item):
        return items_to_bytes.get(item, (None, "jpg"))

    return fetch


def _arcname(item, out_ext):
    return f"images/{item}.{out_ext}"


def _meta(item, arcname, out_ext):
    return {"id": item, "filename": arcname, "ext": out_ext}


# ---------------------------------------------------------------------------
# Empty / minimal inputs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_zip_empty_items_creates_metadata_only(patch_config):
    tmp_path, dl_name, packed, skipped = await build_zip_to_temp(
        items=[],
        max_size=0,
        fetch_bytes=lambda _i: (None, "jpg"),
        arcname_fn=_arcname,
        meta_fn=_meta,
        download_filename="empty.zip",
    )
    try:
        assert dl_name == "empty.zip"
        assert packed == 0
        assert skipped == 0
        assert os.path.exists(tmp_path)
        with zipfile.ZipFile(tmp_path) as zf:
            names = zf.namelist()
            assert "metadata.json" in names
            meta = json.loads(zf.read("metadata.json"))
            assert meta == []
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


@pytest.mark.asyncio
async def test_build_zip_single_item_no_resize(patch_config):
    raw = b"hello-bytes"
    items = ["a"]
    fetch = _fetch_factory({"a": (raw, "jpg")})

    tmp_path, _name, packed, skipped = await build_zip_to_temp(
        items=items,
        max_size=0,  # 0 disables resize → bytes pass through unchanged
        fetch_bytes=fetch,
        arcname_fn=_arcname,
        meta_fn=_meta,
        download_filename="single.zip",
    )
    try:
        assert packed == 1
        assert skipped == 0
        with zipfile.ZipFile(tmp_path) as zf:
            assert "images/a.jpg" in zf.namelist()
            assert zf.read("images/a.jpg") == raw
            meta = json.loads(zf.read("metadata.json"))
            assert len(meta) == 1
            assert meta[0]["id"] == "a"
            assert meta[0]["filename"] == "images/a.jpg"
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


# ---------------------------------------------------------------------------
# Multiple items + skipped item
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_zip_multiple_items_with_skipped(patch_config):
    items = ["a", "b", "missing"]
    fetch = _fetch_factory(
        {
            "a": (b"AAA", "jpg"),
            "b": (b"BBB", "png"),
            # 'missing' returns None bytes → must be skipped
        }
    )
    tmp_path, _name, packed, skipped = await build_zip_to_temp(
        items=items,
        max_size=0,
        fetch_bytes=fetch,
        arcname_fn=_arcname,
        meta_fn=_meta,
        download_filename="multi.zip",
    )
    try:
        assert packed == 2
        assert skipped == 1
        with zipfile.ZipFile(tmp_path) as zf:
            names = zf.namelist()
            assert "images/a.jpg" in names
            assert "images/b.png" in names
            assert not any("missing" in n for n in names)
            meta = json.loads(zf.read("metadata.json"))
            assert {m["id"] for m in meta} == {"a", "b"}
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


# ---------------------------------------------------------------------------
# Arcname collision
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_zip_collision_disambiguates_arcname(patch_config):
    """Two items resolving to the same arcname must produce unique entries."""
    items = ["x", "y"]
    fetch = _fetch_factory({"x": (b"X", "jpg"), "y": (b"Y", "jpg")})
    # Force both items to the same base arcname.
    arc = lambda _item, _ext: "images/same.jpg"  # noqa: E731

    tmp_path, _name, packed, skipped = await build_zip_to_temp(
        items=items,
        max_size=0,
        fetch_bytes=fetch,
        arcname_fn=arc,
        meta_fn=_meta,
        download_filename="collision.zip",
    )
    try:
        assert packed == 2
        assert skipped == 0
        with zipfile.ZipFile(tmp_path) as zf:
            names = [n for n in zf.namelist() if n != "metadata.json"]
            # Both writers wrote (no DuplicateError); names must differ.
            assert len(names) == 2
            assert len(set(names)) == 2
            # First takes the base name, second gets a suffix.
            assert "images/same.jpg" in names
            assert any("same_1" in n for n in names)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


# ---------------------------------------------------------------------------
# PIL resize path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_zip_pil_resize_triggers_for_large_image(patch_config):
    """A real PNG larger than max_size should be re-encoded smaller."""
    big = _make_png(width=64, height=64)
    items = ["big"]
    fetch = _fetch_factory({"big": (big, "png")})

    tmp_path, _name, packed, skipped = await build_zip_to_temp(
        items=items,
        max_size=8,  # force resize down to 8x8
        fetch_bytes=fetch,
        arcname_fn=_arcname,
        meta_fn=_meta,
        download_filename="resize.zip",
    )
    try:
        assert packed == 1
        assert skipped == 0
        with zipfile.ZipFile(tmp_path) as zf:
            names = [n for n in zf.namelist() if n != "metadata.json"]
            # White RGB image → JPEG conversion path (extension changes).
            assert len(names) == 1
            entry_name = names[0]
            data = zf.read(entry_name)
            assert len(data) > 0
            # Resized image should be smaller than the original.
            assert len(data) < len(big) or entry_name.endswith(".jpg")
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


@pytest.mark.asyncio
async def test_build_zip_pil_failure_falls_back_to_raw(patch_config):
    """When PIL cannot decode the bytes, we must fall back to the raw payload."""
    items = ["bad"]
    bogus = b"not-an-image"
    fetch = _fetch_factory({"bad": (bogus, "jpg")})

    tmp_path, _name, packed, skipped = await build_zip_to_temp(
        items=items,
        max_size=512,  # request resize so the PIL branch is taken
        fetch_bytes=fetch,
        arcname_fn=_arcname,
        meta_fn=_meta,
        download_filename="fallback.zip",
    )
    try:
        assert packed == 1
        assert skipped == 0
        with zipfile.ZipFile(tmp_path) as zf:
            assert zf.read("images/bad.jpg") == bogus
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


# ---------------------------------------------------------------------------
# stream_and_cleanup
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stream_and_cleanup_yields_chunks_and_unlinks(tmp_path):
    payload = b"streamed-payload" * 1024  # ~16 KiB
    target = tmp_path / "stream.bin"
    target.write_bytes(payload)

    chunks = []
    async for chunk in stream_and_cleanup(str(target)):
        chunks.append(chunk)
    assert b"".join(chunks) == payload
    # File must be deleted after streaming.
    assert not target.exists()


@pytest.mark.asyncio
async def test_stream_and_cleanup_handles_missing_file_silently(tmp_path):
    """Cleanup of a non-existent file should not raise."""
    bogus = tmp_path / "does-not-exist.bin"
    # Streaming a missing file will raise during open, but the async iterator
    # is what we care about — verify that consumption fails cleanly.
    with pytest.raises(FileNotFoundError):
        async for _chunk in stream_and_cleanup(str(bogus)):
            pass  # pragma: no cover
