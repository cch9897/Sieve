"""Tests for ugoira → animated WebP transcode flow."""

from __future__ import annotations

import asyncio
import io
import json
import sqlite3
import zipfile
from pathlib import Path

import pytest
from PIL import Image


def _make_jpeg(size: tuple[int, int] = (32, 24), color: tuple[int, int, int] = (255, 0, 0)) -> bytes:
    img = Image.new("RGB", size, color=color)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=70)
    return buf.getvalue()


def make_ugoira_zip(dest: Path, *, n_frames: int = 2, delay_ms: int = 50, size: tuple[int, int] = (32, 24)) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    frames_meta = []
    with zipfile.ZipFile(dest, "w") as z:
        for i in range(n_frames):
            name = f"{i:06d}.jpg"
            z.writestr(name, _make_jpeg(size, color=((i * 60) % 255, 100, 200)))
            frames_meta.append({"file": name, "delay": delay_ms, "md5": "x" * 32})
        meta = {
            "width": size[0],
            "height": size[1],
            "mime_type": "image/jpeg",
            "frames": frames_meta,
        }
        z.writestr("animation.json", json.dumps(meta))


def make_plain_zip(dest: Path) -> None:
    """Non-ugoira zip (no animation.json)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest, "w") as z:
        z.writestr("hello.txt", "world")


def _insert_image_row(crawler_dir: Path, *, image_id: int, file_path_rel: str, source: str = "danbooru") -> None:
    db = sqlite3.connect(str(crawler_dir / "dedup.db"))
    db.execute(
        "INSERT INTO images VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            image_id,
            source,
            str(image_id),
            None,
            file_path_rel,
            f"https://example.com/{image_id}",
            "2024-01-02 14:00:00",
        ),
    )
    db.commit()
    db.close()


@pytest.fixture()
def ugoira_setup(tmp_crawler):
    """Add one ugoira zip + one plain zip + matching dedup rows."""
    base = tmp_crawler / "downloads" / "2024-01-01" / "danbooru"
    base.mkdir(parents=True, exist_ok=True)

    ugoira_rel = "downloads/2024-01-01/danbooru/anim.zip"
    plain_rel = "downloads/2024-01-01/danbooru/plain.zip"
    make_ugoira_zip(tmp_crawler / ugoira_rel, n_frames=3)
    make_plain_zip(tmp_crawler / plain_rel)

    _insert_image_row(tmp_crawler, image_id=100, file_path_rel=ugoira_rel)
    _insert_image_row(tmp_crawler, image_id=101, file_path_rel=plain_rel)

    return {"crawler_dir": tmp_crawler, "ugoira_rel": ugoira_rel, "plain_rel": plain_rel}


@pytest.mark.asyncio
async def test_animation_endpoint_caches_and_serves(client, ugoira_setup):
    import state

    rel = ugoira_setup["ugoira_rel"]
    resp = await client.get(f"/api/animation/{rel}")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/webp"
    body = resp.content
    assert len(body) > 0

    cached = state.ANIMATIONS_DIR / Path(rel).with_suffix(".webp")
    assert cached.exists()

    # Second request must hit cache (file should still exist, response identical bytes)
    resp2 = await client.get(f"/api/animation/{rel}")
    assert resp2.status_code == 200
    assert resp2.content == body


@pytest.mark.asyncio
async def test_animation_endpoint_404_for_non_ugoira_zip(client, ugoira_setup):
    rel = ugoira_setup["plain_rel"]
    resp = await client.get(f"/api/animation/{rel}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_animation_endpoint_404_for_missing_file(client, ugoira_setup):
    resp = await client.get("/api/animation/downloads/2024-01-01/danbooru/nope.zip")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_thumbnail_endpoint_handles_ugoira(client, ugoira_setup):
    rel = ugoira_setup["ugoira_rel"]
    resp = await client.get(f"/api/thumb/{rel}")
    assert resp.status_code == 200
    # Pillow saves the thumbnail JPEG → content-type image/jpeg
    assert resp.headers["content-type"] == "image/jpeg"
    assert len(resp.content) > 0


@pytest.mark.asyncio
async def test_thumbnail_endpoint_404_for_plain_zip(client, ugoira_setup):
    rel = ugoira_setup["plain_rel"]
    resp = await client.get(f"/api/thumb/{rel}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_lru_eviction(client, ugoira_setup, monkeypatch):
    """Force a tiny cap so the second transcode evicts the first."""
    import state

    rel1 = ugoira_setup["ugoira_rel"]

    # Add a second ugoira and insert its row
    crawler = ugoira_setup["crawler_dir"]
    rel2 = "downloads/2024-01-01/danbooru/anim2.zip"
    make_ugoira_zip(crawler / rel2, n_frames=3, size=(40, 30))
    _insert_image_row(crawler, image_id=102, file_path_rel=rel2)

    # First request: populate cache
    resp = await client.get(f"/api/animation/{rel1}")
    assert resp.status_code == 200
    cached1 = state.ANIMATIONS_DIR / Path(rel1).with_suffix(".webp")
    assert cached1.exists()

    # Shrink cap below the existing file's size so the next transcode evicts it
    monkeypatch.setattr(state, "UGOIRA_CACHE_MAX_BYTES", 1)

    resp = await client.get(f"/api/animation/{rel2}")
    assert resp.status_code == 200
    cached2 = state.ANIMATIONS_DIR / Path(rel2).with_suffix(".webp")
    assert cached2.exists()
    # rel1 should have been evicted (only newest survives under cap of 1 byte)
    assert not cached1.exists()


@pytest.mark.asyncio
async def test_concurrent_requests_single_transcode(client, ugoira_setup, monkeypatch):
    """Two parallel requests for the same ugoira must transcode only once."""
    from services import ugoira_service

    rel = ugoira_setup["ugoira_rel"]
    calls = {"n": 0}
    real = ugoira_service.transcode_to_webp

    def counting(zip_path, dest_webp):
        calls["n"] += 1
        return real(zip_path, dest_webp)

    monkeypatch.setattr(ugoira_service, "transcode_to_webp", counting)

    r1, r2 = await asyncio.gather(
        client.get(f"/api/animation/{rel}"),
        client.get(f"/api/animation/{rel}"),
    )
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_images_endpoint_flags_zip_as_animation(client, ugoira_setup):
    """Listing API exposes is_animation only for actual ugoira zips."""
    resp = await client.get("/api/images")
    assert resp.status_code == 200
    data = resp.json()
    by_id = {img["id"]: img for img in data["images"]}
    assert by_id[100]["is_animation"] is True
    assert by_id[100]["is_video"] is False
    # Plain (non-ugoira) zips must NOT be flagged — otherwise the frontend
    # fetches /api/animation which 404s and the UI shows a broken image.
    assert by_id[101]["is_animation"] is False
    # Regular jpg rows must NOT be flagged
    assert by_id[1]["is_animation"] is False
