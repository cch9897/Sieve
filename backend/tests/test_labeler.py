"""Tests for /api/labeler endpoints (CRUD + stats)."""

import pytest


@pytest.mark.asyncio
async def test_labeler_next(client):
    resp = await client.get("/api/labeler/next")
    assert resp.status_code == 200
    data = resp.json()
    assert "image" in data
    assert "remaining" in data
    assert data["remaining"] >= 1


@pytest.mark.asyncio
async def test_label_and_stats(client):
    # Label an image as liked
    resp = await client.post("/api/labeler/1", json={"verdict": "liked", "tags": ["test_tag"]})
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("ok") is True

    # Check stats reflect the label
    resp = await client.get("/api/labeler/stats")
    assert resp.status_code == 200
    stats = resp.json()
    assert stats["liked"] >= 1
    assert stats["total_labeled"] >= 1


@pytest.mark.asyncio
async def test_label_and_unlabel(client):
    # Label image 2 as disliked
    resp = await client.post("/api/labeler/2", json={"verdict": "disliked"})
    assert resp.status_code == 200

    # Unlabel it
    resp = await client.delete("/api/labeler/2")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("ok") is True


@pytest.mark.asyncio
async def test_labeler_history(client):
    # Label an image first
    await client.post("/api/labeler/1", json={"verdict": "liked"})

    resp = await client.get("/api/labeler/history")
    assert resp.status_code == 200
    data = resp.json()
    assert "images" in data
    assert len(data["images"]) >= 1


@pytest.mark.asyncio
async def test_labeler_history_filter_verdict(client):
    await client.post("/api/labeler/1", json={"verdict": "liked"})
    await client.post("/api/labeler/2", json={"verdict": "disliked"})

    resp = await client.get("/api/labeler/history", params={"verdict": "liked"})
    data = resp.json()
    for img in data["images"]:
        assert img["verdict"] == "liked"


@pytest.mark.asyncio
async def test_update_tags(client):
    await client.post("/api/labeler/1", json={"verdict": "liked"})

    resp = await client.post("/api/labeler/1/tags", json=["tag_a", "tag_b"])
    assert resp.status_code == 200

    # Verify in history
    resp = await client.get("/api/labeler/history")
    data = resp.json()
    labeled_1 = [img for img in data["images"] if img["id"] == 1]
    assert len(labeled_1) == 1
    assert set(labeled_1[0].get("tags", [])) == {"tag_a", "tag_b"}


@pytest.mark.asyncio
async def test_label_invalid_verdict(client):
    resp = await client.post("/api/labeler/1", json={"verdict": "invalid"})
    assert resp.status_code == 400 or resp.status_code == 422
