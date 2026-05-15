"""Tests for /api/autotags endpoints."""

import json
import sqlite3

import pytest


@pytest.mark.asyncio
async def test_autotags_stats_empty(client):
    """Empty auto_tags — tagged=0, total reflects images."""
    resp = await client.get("/api/autotags/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["tagged"] == 0
    assert data["errored"] == 0
    assert data["top_tags"] == []
    assert "total" in data


@pytest.mark.asyncio
async def test_get_auto_tags_not_found(client):
    """Image with no auto-tags returns found=False."""
    resp = await client.get("/api/autotags/9999")
    assert resp.status_code == 200
    data = resp.json()
    assert data["found"] is False
    assert data["image_id"] == 9999


@pytest.mark.asyncio
async def test_batch_auto_tags_empty_ids(client):
    """Empty ids list returns empty tags map."""
    resp = await client.get("/api/autotags/batch", params={"ids": ""})
    assert resp.status_code == 200
    assert resp.json() == {"tags": {}}


@pytest.mark.asyncio
async def test_batch_auto_tags_invalid_ids(client):
    """Non-integer id returns 400."""
    resp = await client.get("/api/autotags/batch", params={"ids": "abc,def"})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_batch_auto_tags_post_empty(client):
    """POST batch with empty ids returns empty tags."""
    resp = await client.post("/api/autotags/batch", json={"ids": []})
    assert resp.status_code == 200
    assert resp.json() == {"tags": {}}


@pytest.mark.asyncio
async def test_get_auto_tags_with_seed(client, patch_config):
    """Seed auto_tags row and read it back."""
    import config

    conn = sqlite3.connect(str(config.LABELS_DB_PATH))
    conn.execute(
        "INSERT INTO auto_tags (image_id, rating_json, general_json, character_json, top_tags) VALUES (?, ?, ?, ?, ?)",
        (
            1,
            json.dumps({"safe": 0.9}),
            json.dumps(["1girl", "smile"]),
            json.dumps([]),
            "1girl, smile",
        ),
    )
    conn.commit()
    conn.close()

    resp = await client.get("/api/autotags/1")
    assert resp.status_code == 200
    data = resp.json()
    assert data["found"] is True
    assert data["image_id"] == 1
    assert data["general"] == ["1girl", "smile"]


@pytest.mark.asyncio
async def test_search_by_auto_tag_no_matches(client):
    """Empty DB — search returns no images."""
    resp = await client.get("/api/autotags/search", params={"tag": "nonexistent"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["images"] == []
    assert data["total"] == 0
