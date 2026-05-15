"""Tests for /api/stats, /api/dates, /api/sources endpoints."""

import pytest


@pytest.mark.asyncio
async def test_get_stats(client):
    resp = await client.get("/api/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 3
    assert "by_source" in data
    assert data["by_source"]["pixiv"] == 2
    assert data["by_source"]["danbooru"] == 1


@pytest.mark.asyncio
async def test_get_dates(client):
    resp = await client.get("/api/dates")
    assert resp.status_code == 200
    data = resp.json()
    assert "dates" in data
    assert len(data["dates"]) >= 1


@pytest.mark.asyncio
async def test_get_sources(client):
    resp = await client.get("/api/sources")
    assert resp.status_code == 200
    data = resp.json()
    assert "sources" in data
    sources = set(data["sources"])
    assert "pixiv" in sources
    assert "danbooru" in sources
    assert data["counts"]["pixiv"] == 2
