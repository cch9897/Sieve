"""Tests for /api/images endpoints."""

import pytest


@pytest.mark.asyncio
async def test_list_images(client):
    resp = await client.get("/api/images")
    assert resp.status_code == 200
    data = resp.json()
    assert "images" in data
    assert "total" in data
    assert data["total"] == 3
    assert len(data["images"]) == 3


@pytest.mark.asyncio
async def test_list_images_pagination(client):
    resp = await client.get("/api/images", params={"page": 1, "per_page": 2})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["images"]) == 2
    assert data["total"] == 3


@pytest.mark.asyncio
async def test_list_images_filter_source(client):
    resp = await client.get("/api/images", params={"source": "pixiv"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    for img in data["images"]:
        assert img["source"] == "pixiv"


@pytest.mark.asyncio
async def test_list_images_filter_source_danbooru(client):
    resp = await client.get("/api/images", params={"source": "danbooru"})
    data = resp.json()
    assert data["total"] == 1
    assert data["images"][0]["source"] == "danbooru"


@pytest.mark.asyncio
async def test_get_image_detail(client):
    resp = await client.get("/api/images/1")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == 1
    assert data["source"] == "pixiv"
    assert "phash" in data


@pytest.mark.asyncio
async def test_get_image_not_found(client):
    resp = await client.get("/api/images/9999")
    assert resp.status_code == 404
