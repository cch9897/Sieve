"""Tests for /api/novels list/detail/dates endpoints.

The novels router reads metadata from JSON files on disk in addition to
querying the dedup.db ``novels`` table, so each fixture seeds both layers.
"""

import json
import sqlite3
from pathlib import Path

import pytest


def _seed_novel(
    crawler_dir: Path,
    *,
    id: int,
    source: str,
    source_id: str,
    title: str,
    author: str,
    rel_path: str,
    created_at: str,
    meta: dict,
) -> None:
    """Insert one novel row + its JSON metadata file."""
    full = crawler_dir / rel_path
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(json.dumps(meta), encoding="utf-8")

    db = sqlite3.connect(str(crawler_dir / "dedup.db"))
    try:
        db.execute(
            "INSERT INTO novels (id, source, source_id, title, author, file_path, url, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (id, source, source_id, title, author, rel_path, f"https://example.test/{source_id}", created_at),
        )
        db.commit()
    finally:
        db.close()


@pytest.fixture()
def novels_seeded(tmp_crawler):
    """Seed three novels with distinct lengths, bookmarks, and dates."""
    _seed_novel(
        tmp_crawler,
        id=1,
        source="pixiv",
        source_id="N1",
        title="Alpha",
        author="Aoi",
        rel_path="downloads/2024-01-01/pixiv/novel1.json",
        created_at="2024-01-01 10:00:00",
        meta={
            "title": "Alpha",
            "author": "Aoi",
            "text": "x" * 100,
            "total_bookmarks": 50,
            "total_view": 500,
            "tags": ["fantasy"],
        },
    )
    _seed_novel(
        tmp_crawler,
        id=2,
        source="pixiv",
        source_id="N2",
        title="Bravo",
        author="Bing",
        rel_path="downloads/2024-02-01/pixiv/novel2.json",
        created_at="2024-02-01 10:00:00",
        meta={
            "title": "Bravo",
            "author": "Bing",
            "text": "y" * 500,
            "total_bookmarks": 10,
            "total_view": 2000,
            "tags": ["sf"],
        },
    )
    _seed_novel(
        tmp_crawler,
        id=3,
        source="pixiv",
        source_id="N3",
        title="Charlie",
        author="Aoi",
        rel_path="downloads/2024-03-01/pixiv/novel3.json",
        created_at="2024-03-01 10:00:00",
        meta={
            "title": "Charlie",
            "author": "Aoi",
            "text": "z" * 200,
            "total_bookmarks": 999,
            "total_view": 100,
            "tags": [],
        },
    )
    return tmp_crawler


@pytest.mark.asyncio
async def test_list_novels(client, novels_seeded):
    resp = await client.get("/api/novels")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 3
    assert len(data["novels"]) == 3
    # Default sort is "newest" -> created_at DESC -> id 3, 2, 1
    assert [n["id"] for n in data["novels"]] == [3, 2, 1]


@pytest.mark.asyncio
async def test_list_novels_sort_oldest(client, novels_seeded):
    resp = await client.get("/api/novels", params={"sort": "oldest"})
    data = resp.json()
    assert [n["id"] for n in data["novels"]] == [1, 2, 3]


@pytest.mark.asyncio
async def test_list_novels_sort_bookmarks(client, novels_seeded):
    resp = await client.get("/api/novels", params={"sort": "bookmarks"})
    data = resp.json()
    # bookmarks: 999, 50, 10 -> id 3, 1, 2
    assert [n["id"] for n in data["novels"]] == [3, 1, 2]


@pytest.mark.asyncio
async def test_list_novels_sort_views(client, novels_seeded):
    resp = await client.get("/api/novels", params={"sort": "views"})
    data = resp.json()
    # views: 2000, 500, 100 -> id 2, 1, 3
    assert [n["id"] for n in data["novels"]] == [2, 1, 3]


@pytest.mark.asyncio
async def test_list_novels_sort_length(client, novels_seeded):
    resp = await client.get("/api/novels", params={"sort": "length"})
    data = resp.json()
    # text lengths: 500, 200, 100 -> id 2, 3, 1
    assert [n["id"] for n in data["novels"]] == [2, 3, 1]


@pytest.mark.asyncio
async def test_list_novels_invalid_sort(client, novels_seeded):
    resp = await client.get("/api/novels", params={"sort": "bogus"})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_list_novels_search_title(client, novels_seeded):
    resp = await client.get("/api/novels", params={"search": "Bravo"})
    data = resp.json()
    assert data["total"] == 1
    assert data["novels"][0]["id"] == 2


@pytest.mark.asyncio
async def test_list_novels_search_author(client, novels_seeded):
    resp = await client.get("/api/novels", params={"search": "Aoi"})
    data = resp.json()
    # Aoi authored novels 1 and 3
    assert data["total"] == 2
    assert {n["id"] for n in data["novels"]} == {1, 3}


@pytest.mark.asyncio
async def test_list_novels_filter_by_date(client, novels_seeded):
    resp = await client.get("/api/novels", params={"date": "2024-02-01"})
    data = resp.json()
    assert data["total"] == 1
    assert data["novels"][0]["id"] == 2
    assert data["novels"][0]["date"] == "2024-02-01"


@pytest.mark.asyncio
async def test_list_novels_pagination(client, novels_seeded):
    resp = await client.get("/api/novels", params={"per_page": 2, "page": 1})
    data = resp.json()
    assert data["total"] == 3
    assert data["pages"] == 2
    assert len(data["novels"]) == 2
    resp2 = await client.get("/api/novels", params={"per_page": 2, "page": 2})
    data2 = resp2.json()
    assert len(data2["novels"]) == 1


@pytest.mark.asyncio
async def test_get_novel_detail_includes_text(client, novels_seeded):
    resp = await client.get("/api/novels/1")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == 1
    assert data["title"] == "Alpha"
    assert data["text"] == "x" * 100
    assert data["text_length"] == 100
    assert data["tags"] == ["fantasy"]


@pytest.mark.asyncio
async def test_get_novel_not_found(client, novels_seeded):
    resp = await client.get("/api/novels/9999")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_novel_dates(client, novels_seeded):
    resp = await client.get("/api/novels/dates")
    assert resp.status_code == 200
    data = resp.json()
    # Three distinct dates, sorted desc
    assert data["dates"] == ["2024-03-01", "2024-02-01", "2024-01-01"]
