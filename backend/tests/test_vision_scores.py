"""Tests for /api/vision-scores endpoints with empty labels.db."""

import sqlite3

import pytest


@pytest.mark.asyncio
async def test_vision_scores_stats_empty(client):
    """Empty vision_scores table — no models, zero counts."""
    resp = await client.get("/api/vision-scores/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_scored"] == 0
    assert data["models"] == {}
    assert data["model_name"] is None


@pytest.mark.asyncio
async def test_vision_scores_stats_specific_model_empty(client):
    """Filter by model when no scores exist — should return zero shape."""
    resp = await client.get("/api/vision-scores/stats", params={"model": "nonexistent"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_scored"] == 0
    assert data["model_name"] == "nonexistent"
    assert "distribution" in data


@pytest.mark.asyncio
async def test_vision_scores_compare_no_scores(client):
    """compare endpoint for an image with no scores returns empty dict."""
    resp = await client.get("/api/vision-scores/compare", params={"image_id": 1})
    assert resp.status_code == 200
    data = resp.json()
    assert data["image_id"] == 1
    assert data["scores"] == {}


@pytest.mark.asyncio
async def test_vision_scores_compare_stats_empty(client):
    """compare-stats with empty DB returns empty models dict."""
    resp = await client.get("/api/vision-scores/compare-stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["models"] == {}


@pytest.mark.asyncio
async def test_vision_scores_stats_with_seeded_data(client, patch_config):
    """Seed labels.db with vision scores; verify aggregations."""
    import config

    conn = sqlite3.connect(str(config.LABELS_DB_PATH))
    conn.executemany(
        "INSERT INTO vision_scores (image_id, model_name, score) VALUES (?, ?, ?)",
        [(1, "modelA", 0.85), (2, "modelA", 0.45), (1, "modelB", 0.95)],
    )
    conn.commit()
    conn.close()

    # Query specific model — bypasses the @ttl_cache because key differs from earlier tests
    resp = await client.get("/api/vision-scores/stats", params={"model": "modelA"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_scored"] == 2
    assert data["model_name"] == "modelA"

    resp = await client.get("/api/vision-scores/compare", params={"image_id": 1})
    data = resp.json()
    assert set(data["scores"].keys()) == {"modelA", "modelB"}
