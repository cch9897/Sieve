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


@pytest.mark.asyncio
async def test_list_liked_empty(client):
    """No labels yet — should return zero images."""
    resp = await client.get("/api/liked")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0
    assert data["images"] == []


@pytest.mark.asyncio
async def test_list_liked_after_label(client):
    """Label one image as liked, then fetch liked images."""
    # Label image 1 as liked
    await client.post("/api/labeler/1", json={"verdict": "liked"})
    # Label image 2 as disliked (should not appear)
    await client.post("/api/labeler/2", json={"verdict": "disliked"})

    resp = await client.get("/api/liked")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["images"][0]["id"] == 1
    assert data["images"][0]["source"] == "pixiv"


@pytest.mark.asyncio
async def test_list_liked_filter_source(client):
    """Label multiple images, filter liked by source."""
    await client.post("/api/labeler/1", json={"verdict": "liked"})
    await client.post("/api/labeler/3", json={"verdict": "liked"})

    resp = await client.get("/api/liked", params={"source": "pixiv"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["images"][0]["source"] == "pixiv"


@pytest.mark.asyncio
async def test_list_liked_pagination(client):
    """Paginate liked images."""
    await client.post("/api/labeler/1", json={"verdict": "liked"})
    await client.post("/api/labeler/2", json={"verdict": "liked"})

    resp = await client.get("/api/liked", params={"page": 1, "per_page": 1})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["images"]) == 1
    assert data["total"] == 2
    assert data["pages"] == 2


@pytest.mark.asyncio
async def test_random_liked_empty(client):
    """No liked images — should return empty."""
    resp = await client.get("/api/liked/random")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0
    assert data["images"] == []


@pytest.mark.asyncio
async def test_random_liked_single(client):
    """One liked image — random should return it."""
    await client.post("/api/labeler/1", json={"verdict": "liked"})

    resp = await client.get("/api/liked/random")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert len(data["images"]) == 1
    assert data["images"][0]["id"] == 1


@pytest.mark.asyncio
async def test_random_liked_count(client):
    """Request multiple random liked images."""
    await client.post("/api/labeler/1", json={"verdict": "liked"})
    await client.post("/api/labeler/2", json={"verdict": "liked"})
    await client.post("/api/labeler/3", json={"verdict": "liked"})

    resp = await client.get("/api/liked/random", params={"count": 2})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 3
    assert len(data["images"]) == 2
    # All returned IDs must be from the liked set
    assert all(img["id"] in (1, 2, 3) for img in data["images"])


@pytest.mark.asyncio
async def test_random_liked_with_filter(client):
    """Random liked with source filter."""
    await client.post("/api/labeler/1", json={"verdict": "liked"})
    await client.post("/api/labeler/3", json={"verdict": "liked"})

    resp = await client.get("/api/liked/random", params={"source": "pixiv"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["images"][0]["source"] == "pixiv"


@pytest.mark.asyncio
async def test_random_liked_excludes_disliked(client):
    """Random liked should not return disliked images."""
    await client.post("/api/labeler/1", json={"verdict": "liked"})
    await client.post("/api/labeler/2", json={"verdict": "disliked"})

    # Call multiple times — statistically should never get id=2
    for _ in range(5):
        resp = await client.get("/api/liked/random")
        assert resp.status_code == 200
        data = resp.json()
        assert all(img["id"] != 2 for img in data["images"])
