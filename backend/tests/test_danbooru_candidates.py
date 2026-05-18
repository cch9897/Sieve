"""Tests for /api/danbooru/candidates {next, mark, clear} endpoints.

The router talks to two SQLite files (``candidates.db`` and
``danbooru_labels.db``) via ATTACH. We seed both, then verify filtering,
labeling, and clearing behavior.
"""

import sqlite3

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient


def _create_candidates_db(db_path) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("""
            CREATE TABLE candidates (
                image_id INTEGER PRIMARY KEY,
                ext TEXT,
                score INTEGER,
                rating TEXT,
                tags TEXT,
                preference_score REAL NOT NULL,
                tag_score REAL,
                cnn_score REAL,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE score_log (
                image_id INTEGER PRIMARY KEY,
                tag_score REAL,
                cnn_score REAL,
                fused_score REAL,
                accepted INTEGER DEFAULT 0
            )
        """)
        conn.execute("""
            CREATE TABLE scan_state (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        conn.commit()
    finally:
        conn.close()


def _seed_candidates(db_path, rows: list[tuple]) -> None:
    """rows: (image_id, ext, score, rating, tags, pref, tag_sc, cnn_sc, status)"""
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executemany(
            "INSERT INTO candidates (image_id, ext, score, rating, tags, "
            "preference_score, tag_score, cnn_score, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        conn.commit()
    finally:
        conn.close()


def _label_image(dl_db_path, image_id: int, verdict: str = "liked") -> None:
    conn = sqlite3.connect(str(dl_db_path))
    try:
        conn.execute(
            "INSERT INTO labels (image_id, verdict) VALUES (?, ?)",
            (image_id, verdict),
        )
        conn.commit()
    finally:
        conn.close()


@pytest_asyncio.fixture()
async def dc_client(app, patch_config, monkeypatch):
    """Client with danbooru_candidates router mounted on the test app."""
    import config
    from routers import danbooru_candidates

    monkeypatch.setattr(danbooru_candidates, "CANDIDATES_DB_PATH", config.CANDIDATES_DB_PATH)
    monkeypatch.setattr(danbooru_candidates, "DANBOORU_LABELS_DB_PATH", config.DANBOORU_LABELS_DB_PATH)

    app.include_router(danbooru_candidates.router)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ---------------------------------------------------------------------------
# /next
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_next_no_db(dc_client):
    """When candidates.db doesn't exist, short-circuit empty response."""
    resp = await dc_client.get("/api/danbooru/candidates/next")
    assert resp.status_code == 200
    data = resp.json()
    assert data == {"image": None, "remaining": 0, "total_labeled": 0}


@pytest.mark.asyncio
async def test_next_returns_highest_score(dc_client, patch_config):
    import config

    _create_candidates_db(config.CANDIDATES_DB_PATH)
    _seed_candidates(
        config.CANDIDATES_DB_PATH,
        [
            (101, "jpg", 200, "s", "tag_a tag_b", 0.7, 0.6, 0.8, "pending"),
            (102, "png", 150, "g", "tag_c", 0.95, 0.9, 0.7, "pending"),
            (103, "jpg", 90, "s", "", 0.55, 0.5, 0.6, "pending"),
        ],
    )
    resp = await dc_client.get("/api/danbooru/candidates/next")
    data = resp.json()
    assert data["image"]["id"] == 102
    assert data["image"]["ext"] == "png"
    assert data["image"]["preference_score"] == pytest.approx(0.95)
    assert data["remaining"] == 3
    assert data["total_labeled"] == 0


@pytest.mark.asyncio
async def test_next_filters_by_min_score(dc_client, patch_config):
    import config

    _create_candidates_db(config.CANDIDATES_DB_PATH)
    _seed_candidates(
        config.CANDIDATES_DB_PATH,
        [
            (1, "jpg", 200, "s", "", 0.4, None, None, "pending"),
            (2, "jpg", 200, "s", "", 0.85, None, None, "pending"),
        ],
    )
    resp = await dc_client.get("/api/danbooru/candidates/next", params={"min_score": 0.8})
    data = resp.json()
    assert data["image"]["id"] == 2
    assert data["remaining"] == 1


@pytest.mark.asyncio
async def test_next_filters_by_rating(dc_client, patch_config):
    import config

    _create_candidates_db(config.CANDIDATES_DB_PATH)
    _seed_candidates(
        config.CANDIDATES_DB_PATH,
        [
            (1, "jpg", 200, "s", "", 0.9, None, None, "pending"),
            (2, "jpg", 200, "q", "", 0.95, None, None, "pending"),
        ],
    )
    resp = await dc_client.get("/api/danbooru/candidates/next", params={"rating": "s"})
    data = resp.json()
    assert data["image"]["id"] == 1
    assert data["image"]["rating"] == "s"


@pytest.mark.asyncio
async def test_next_filters_media_image_vs_video(dc_client, patch_config):
    import config

    _create_candidates_db(config.CANDIDATES_DB_PATH)
    _seed_candidates(
        config.CANDIDATES_DB_PATH,
        [
            (1, "jpg", 200, "s", "", 0.7, None, None, "pending"),
            (2, "mp4", 200, "s", "", 0.95, None, None, "pending"),
            (3, "webm", 200, "s", "", 0.5, None, None, "pending"),
        ],
    )
    resp_img = await dc_client.get("/api/danbooru/candidates/next", params={"media": "image"})
    img = resp_img.json()["image"]
    assert img["id"] == 1
    assert img["is_video"] is False

    resp_vid = await dc_client.get("/api/danbooru/candidates/next", params={"media": "video"})
    vid = resp_vid.json()["image"]
    assert vid["id"] == 2
    assert vid["is_video"] is True
    assert vid["video_url"] is not None


@pytest.mark.asyncio
async def test_next_excludes_already_labeled(dc_client, patch_config):
    import config

    _create_candidates_db(config.CANDIDATES_DB_PATH)
    _seed_candidates(
        config.CANDIDATES_DB_PATH,
        [
            (1, "jpg", 200, "s", "", 0.9, None, None, "pending"),
            (2, "jpg", 200, "s", "", 0.95, None, None, "pending"),
        ],
    )
    _label_image(config.DANBOORU_LABELS_DB_PATH, 2, verdict="liked")

    resp = await dc_client.get("/api/danbooru/candidates/next")
    data = resp.json()
    assert data["image"]["id"] == 1
    assert data["remaining"] == 1
    assert data["total_labeled"] == 1


@pytest.mark.asyncio
async def test_next_min_aes_skips_missing_cnn(dc_client, patch_config):
    import config

    _create_candidates_db(config.CANDIDATES_DB_PATH)
    _seed_candidates(
        config.CANDIDATES_DB_PATH,
        [
            (1, "jpg", 200, "s", "", 0.9, None, None, "pending"),  # cnn_score NULL
            (2, "jpg", 200, "s", "", 0.85, None, 0.4, "pending"),  # cnn too low
            (3, "jpg", 200, "s", "", 0.7, None, 0.8, "pending"),  # passes
        ],
    )
    resp = await dc_client.get("/api/danbooru/candidates/next", params={"min_aes": 0.5})
    data = resp.json()
    assert data["image"]["id"] == 3


# ---------------------------------------------------------------------------
# /mark
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mark_flips_status_to_labeled(dc_client, patch_config):
    import config

    _create_candidates_db(config.CANDIDATES_DB_PATH)
    _seed_candidates(
        config.CANDIDATES_DB_PATH,
        [(7, "jpg", 200, "s", "", 0.9, None, None, "pending")],
    )

    resp = await dc_client.post("/api/danbooru/candidates/7/mark")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}

    conn = sqlite3.connect(str(config.CANDIDATES_DB_PATH))
    try:
        status = conn.execute("SELECT status FROM candidates WHERE image_id=7").fetchone()[0]
    finally:
        conn.close()
    assert status == "labeled"


@pytest.mark.asyncio
async def test_mark_unknown_id_is_noop(dc_client, patch_config):
    import config

    _create_candidates_db(config.CANDIDATES_DB_PATH)
    # No rows seeded — mark should still succeed (UPDATE matches 0 rows)
    resp = await dc_client.post("/api/danbooru/candidates/9999/mark")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


@pytest.mark.asyncio
async def test_mark_no_db(dc_client):
    """If candidates.db is absent, /mark short-circuits without error."""
    resp = await dc_client.post("/api/danbooru/candidates/1/mark")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


# ---------------------------------------------------------------------------
# /clear
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_clear_wipes_all_tables(dc_client, patch_config):
    import config

    _create_candidates_db(config.CANDIDATES_DB_PATH)
    _seed_candidates(
        config.CANDIDATES_DB_PATH,
        [
            (1, "jpg", 200, "s", "", 0.9, None, None, "pending"),
            (2, "jpg", 200, "s", "", 0.5, None, None, "labeled"),
        ],
    )
    # Seed score_log + scan_state so we can assert they're wiped too
    conn = sqlite3.connect(str(config.CANDIDATES_DB_PATH))
    try:
        conn.execute("INSERT INTO score_log (image_id, fused_score, accepted) VALUES (1, 0.9, 1)")
        conn.execute("INSERT INTO scan_state (key, value) VALUES ('cursor', 'abc')")
        conn.commit()
    finally:
        conn.close()

    resp = await dc_client.post("/api/danbooru/candidates/clear")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "deleted": 2}

    conn = sqlite3.connect(str(config.CANDIDATES_DB_PATH))
    try:
        assert conn.execute("SELECT COUNT(*) FROM candidates").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM score_log").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM scan_state").fetchone()[0] == 0
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_clear_no_db(dc_client):
    """If candidates.db is absent, /clear short-circuits with deleted=0."""
    resp = await dc_client.post("/api/danbooru/candidates/clear")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "deleted": 0}


@pytest.mark.asyncio
async def test_clear_without_score_log_table(dc_client, patch_config):
    """Older DBs may not have score_log — clear should tolerate that."""
    import config

    # Build a candidates.db missing score_log
    conn = sqlite3.connect(str(config.CANDIDATES_DB_PATH))
    try:
        conn.execute("""
            CREATE TABLE candidates (
                image_id INTEGER PRIMARY KEY,
                ext TEXT, score INTEGER, rating TEXT, tags TEXT,
                preference_score REAL NOT NULL, tag_score REAL, cnn_score REAL,
                status TEXT DEFAULT 'pending'
            )
        """)
        conn.execute("INSERT INTO candidates (image_id, preference_score) VALUES (1, 0.5)")
        conn.commit()
    finally:
        conn.close()

    resp = await dc_client.post("/api/danbooru/candidates/clear")
    assert resp.status_code == 200
    assert resp.json()["deleted"] == 1
