"""Tests for /api/danbooru/labeler endpoints.

Only covers paths that don't require live network calls to DanbooruFinder.
``/next`` is mocked through MockTransport because it raises 502 on real
HTTP failures; ``/stats`` swallows ``httpx.HTTPError`` and reports
``total_images=0`` when the upstream is unreachable, so it works offline
without mocking.
"""

import asyncio
from contextlib import asynccontextmanager

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


@pytest_asyncio.fixture()
async def dan_app(patch_config, init_databases, reset_state):
    """FastAPI app that includes only the danbooru_labeler router."""
    import state
    from database import get_sync_db

    @asynccontextmanager
    async def test_lifespan(app):
        state.THUMBS_DIR.mkdir(parents=True, exist_ok=True)
        with get_sync_db(readonly=False) as conn:
            conn.execute("CREATE INDEX IF NOT EXISTS idx_images_file_created_at ON images(file_path, created_at DESC)")
        yield
        # Cleanup pools (mirrors conftest.app)
        if state._db_pool is not None:
            await state._db_pool.close()
            state._db_pool = None
        if state._labels_pool is not None:
            await state._labels_pool.close()
            state._labels_pool = None
        if state._danbooru_labels_pool is not None:
            await state._danbooru_labels_pool.close()
            state._danbooru_labels_pool = None
        if state._candidates_pool is not None:
            await state._candidates_pool.close()
            state._candidates_pool = None
        if state._danbooru_client is not None:
            await state._danbooru_client.aclose()
            state._danbooru_client = None
        # Drain any background tasks the router scheduled (likes auto-download).
        if state._background_tasks:
            await asyncio.gather(*list(state._background_tasks), return_exceptions=True)

    test_app = FastAPI(lifespan=test_lifespan)

    from routers import danbooru_labeler

    test_app.include_router(danbooru_labeler.router)
    return test_app


@pytest_asyncio.fixture()
async def dan_client(dan_app):
    transport = ASGITransport(app=dan_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture()
def mock_danbooru_client(monkeypatch):
    """Inject an httpx.MockTransport so /next sees a fixed search response."""
    import database
    import state

    def _handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/search":
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "id": 1001,
                            "ext": "jpg",
                            "score": 50,
                            "rating": "s",
                            "created_at": "2024-01-01",
                            "file_size": 12345,
                            "tags": "cat dog",
                            "tag_categories": {},
                        },
                        {
                            "id": 1002,
                            "ext": "mp4",  # video
                            "score": 30,
                            "rating": "q",
                            "created_at": "2024-01-02",
                            "file_size": 23456,
                            "tags": "anime",
                            "tag_categories": {},
                        },
                    ],
                    "pagination": {"total": 2},
                },
            )
        return httpx.Response(404, json={"detail": "not found"})

    transport = httpx.MockTransport(_handler)
    client = httpx.AsyncClient(base_url="http://danbooru-mock", transport=transport)
    state._danbooru_client = client

    # Replace get_danbooru_client to keep returning our mock.
    def _get():
        return client

    monkeypatch.setattr(database, "get_danbooru_client", _get)
    return client


# ---------------------------------------------------------------------------
# /stats — works offline (httpx errors are swallowed → total_images = 0).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stats_empty(dan_client):
    resp = await dan_client.get("/api/danbooru/labeler/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["liked"] == 0
    assert data["disliked"] == 0
    assert data["skipped"] == 0
    assert data["total_labeled"] == 0
    assert data["top_tags"] == []
    assert data["liked_top_danbooru_tags"] == []


@pytest.mark.asyncio
async def test_stats_after_labeling(dan_client):
    # Label a couple of images via the public POST endpoint.
    await dan_client.post(
        "/api/danbooru/labeler/501",
        json={"verdict": "liked", "ext": "jpg", "score": 80, "rating": "s", "tags": ["t1"], "danbooru_tags": "cat dog"},
    )
    await dan_client.post(
        "/api/danbooru/labeler/502",
        json={"verdict": "disliked", "ext": "jpg", "score": 10, "rating": "q", "tags": [], "danbooru_tags": "ugly"},
    )
    resp = await dan_client.get("/api/danbooru/labeler/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["liked"] == 1
    assert data["disliked"] == 1
    assert data["total_labeled"] == 2
    # Top user tags should include 't1' (count 1).
    user_tags = {t["tag"]: t["count"] for t in data["top_tags"]}
    assert user_tags.get("t1") == 1
    # Liked top danbooru tags should include cat / dog (parsed from space-separated).
    liked_dan_tags = {t["tag"] for t in data["liked_top_danbooru_tags"]}
    assert "cat" in liked_dan_tags and "dog" in liked_dan_tags


# ---------------------------------------------------------------------------
# /history — pagination + filters
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_history_empty(dan_client):
    resp = await dan_client.get("/api/danbooru/labeler/history")
    assert resp.status_code == 200
    data = resp.json()
    assert data["images"] == []
    assert data["total"] == 0
    assert data["pages"] == 0


@pytest.mark.asyncio
async def test_history_returns_labeled(dan_client):
    await dan_client.post(
        "/api/danbooru/labeler/700",
        json={"verdict": "liked", "ext": "jpg", "score": 99, "rating": "s", "tags": ["aa"], "danbooru_tags": "tag1"},
    )
    resp = await dan_client.get("/api/danbooru/labeler/history")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert len(data["images"]) == 1
    img = data["images"][0]
    assert img["id"] == 700
    assert img["ext"] == "jpg"
    assert img["verdict"] == "liked"
    assert img["tags"] == ["aa"]
    assert img["danbooru_tags"] == "tag1"


@pytest.mark.asyncio
async def test_history_filter_by_verdict(dan_client):
    await dan_client.post(
        "/api/danbooru/labeler/801",
        json={"verdict": "liked", "ext": "jpg", "score": 0, "rating": "s", "tags": [], "danbooru_tags": ""},
    )
    await dan_client.post(
        "/api/danbooru/labeler/802",
        json={"verdict": "disliked", "ext": "jpg", "score": 0, "rating": "s", "tags": [], "danbooru_tags": ""},
    )
    resp = await dan_client.get("/api/danbooru/labeler/history", params={"verdict": "liked"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["images"][0]["id"] == 801
    assert data["images"][0]["verdict"] == "liked"


# ---------------------------------------------------------------------------
# POST / DELETE
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_post_invalid_verdict(dan_client):
    resp = await dan_client.post(
        "/api/danbooru/labeler/123",
        json={"verdict": "neutral", "ext": "jpg", "score": 0, "rating": "s", "tags": []},
    )
    assert resp.status_code == 400
    assert "verdict" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_delete_round_trip(dan_client):
    # Label, then delete.
    await dan_client.post(
        "/api/danbooru/labeler/9999",
        json={"verdict": "skipped", "ext": "jpg", "score": 0, "rating": "s", "tags": [], "danbooru_tags": ""},
    )
    resp = await dan_client.delete("/api/danbooru/labeler/9999")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}

    # Stats should show zero again.
    resp2 = await dan_client.get("/api/danbooru/labeler/stats")
    assert resp2.json()["total_labeled"] == 0


# ---------------------------------------------------------------------------
# /next — mocked DanbooruFinder via MockTransport
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_next_returns_first_unlabeled_candidate(dan_client, mock_danbooru_client):
    resp = await dan_client.get("/api/danbooru/labeler/next")
    assert resp.status_code == 200
    data = resp.json()
    assert data["image"] is not None
    # First mock result is id=1001.
    assert data["image"]["id"] == 1001
    assert data["image"]["ext"] == "jpg"
    assert data["image"]["is_video"] is False


@pytest.mark.asyncio
async def test_next_skips_already_labeled(dan_client, mock_danbooru_client):
    # Label the first mock candidate.
    await dan_client.post(
        "/api/danbooru/labeler/1001",
        json={"verdict": "skipped", "ext": "jpg", "score": 0, "rating": "s", "tags": [], "danbooru_tags": ""},
    )
    resp = await dan_client.get("/api/danbooru/labeler/next")
    assert resp.status_code == 200
    data = resp.json()
    # Should fall through to id=1002 (the video candidate).
    assert data["image"] is not None
    assert data["image"]["id"] == 1002
    assert data["image"]["is_video"] is True


@pytest.mark.asyncio
async def test_next_media_filter_excludes_videos(dan_client, mock_danbooru_client):
    """media=image should skip the mp4 candidate."""
    # Label 1001 first so 1002 is the only remaining candidate.
    await dan_client.post(
        "/api/danbooru/labeler/1001",
        json={"verdict": "skipped", "ext": "jpg", "score": 0, "rating": "s", "tags": [], "danbooru_tags": ""},
    )
    resp = await dan_client.get("/api/danbooru/labeler/next", params={"media": "image"})
    assert resp.status_code == 200
    data = resp.json()
    # 1002 is a video → filtered out → image=None.
    assert data["image"] is None
