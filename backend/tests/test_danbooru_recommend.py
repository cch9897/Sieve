"""Tests for /api/danbooru/candidates/stats and DanbooruCandidatesRepo unit."""

import sqlite3

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from services.danbooru_candidates_repo import DanbooruCandidatesRepo

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_candidates_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE candidates (
            image_id INTEGER PRIMARY KEY,
            preference_score REAL,
            rating TEXT,
            status TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE score_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fused_score REAL,
            accepted INTEGER
        )
    """)


# ---------------------------------------------------------------------------
# Repo unit tests (sqlite3, no FastAPI)
# ---------------------------------------------------------------------------


def test_repo_empty_db():
    conn = sqlite3.connect(":memory:")
    _create_candidates_schema(conn)
    repo = DanbooruCandidatesRepo(conn)
    assert repo.count_total() == 0
    assert repo.count_pending() == 0
    assert repo.count_labeled() == 0
    assert repo.count_by_score_bucket() == {}
    assert repo.count_by_rating() == {}
    assert repo.avg_score() == 0
    assert repo.top_score() == 0
    all_s, acc, rej = repo.fetch_score_log()
    assert all_s == []
    assert acc == []
    assert rej == []


def test_repo_aggregations_with_seed():
    conn = sqlite3.connect(":memory:")
    _create_candidates_schema(conn)
    conn.executemany(
        "INSERT INTO candidates (image_id, preference_score, rating, status) VALUES (?, ?, ?, ?)",
        [
            (1, 0.95, "s", "pending"),
            (2, 0.75, "q", "pending"),
            (3, 0.40, "s", "labeled"),
        ],
    )
    conn.commit()
    repo = DanbooruCandidatesRepo(conn)
    assert repo.count_total() == 3
    assert repo.count_pending() == 2
    assert repo.count_labeled() == 1
    buckets = repo.count_by_score_bucket()
    assert buckets.get("90-100%") == 1
    assert buckets.get("70-80%") == 1
    assert buckets.get("<50%") == 1
    rating_dist = repo.count_by_rating()
    assert rating_dist["s"] == 2
    assert rating_dist["q"] == 1
    assert repo.top_score() == pytest.approx(0.95)
    assert repo.avg_score() == pytest.approx((0.95 + 0.75 + 0.40) / 3)


def test_repo_score_log_partition():
    conn = sqlite3.connect(":memory:")
    _create_candidates_schema(conn)
    conn.executemany(
        "INSERT INTO score_log (fused_score, accepted) VALUES (?, ?)",
        [(0.9, 1), (0.8, 1), (0.2, 0)],
    )
    conn.commit()
    repo = DanbooruCandidatesRepo(conn)
    all_s, acc, rej = repo.fetch_score_log()
    assert sorted(all_s) == [0.2, 0.8, 0.9]
    assert sorted(acc) == [0.8, 0.9]
    assert rej == [0.2]


def test_repo_build_histogram_bins():
    bins = DanbooruCandidatesRepo.build_histogram([0.05, 0.95], [0.5])
    assert len(bins) == 40
    # Each bin has lo, hi, count, accepted, rejected
    assert {"lo", "hi", "count", "accepted", "rejected"} <= set(bins[0].keys())
    total_accepted = sum(b["accepted"] for b in bins)
    total_rejected = sum(b["rejected"] for b in bins)
    assert total_accepted == 2
    assert total_rejected == 1


def test_repo_confidence_stats_empty():
    assert DanbooruCandidatesRepo.confidence_stats([]) == {}


def test_repo_confidence_stats_single():
    stats = DanbooruCandidatesRepo.confidence_stats([0.7])
    assert stats["n"] == 1
    assert stats["mean"] == 0.7


# ---------------------------------------------------------------------------
# Endpoint test — register danbooru_recommend router and stub state
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture()
async def dr_client(app, patch_config, monkeypatch):
    """Client with danbooru_recommend router included."""
    import config
    from routers import danbooru_recommend

    # Re-bind the module-level CANDIDATES_DB_PATH to the patched one
    # (it was imported at module load time before monkeypatch took effect).
    monkeypatch.setattr(danbooru_recommend, "CANDIDATES_DB_PATH", config.CANDIDATES_DB_PATH)

    app.include_router(danbooru_recommend.router)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_candidates_stats_no_db(dr_client):
    """When candidates.db doesn't exist, returns short-circuit zero shape."""
    resp = await dr_client.get("/api/danbooru/candidates/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0
    assert data["pending"] == 0
    assert data["labeled"] == 0
    assert data["score_distribution"] == {}
    assert data["rating_distribution"] == {}
    assert data["model_loaded"] is False


@pytest.mark.asyncio
async def test_candidates_stats_with_seeded_db(dr_client, patch_config):
    """Create candidates.db with rows; verify response keys and aggregations."""
    import config

    conn = sqlite3.connect(str(config.CANDIDATES_DB_PATH))
    _create_candidates_schema(conn)
    conn.executemany(
        "INSERT INTO candidates (image_id, preference_score, rating, status) VALUES (?, ?, ?, ?)",
        [
            (10, 0.92, "s", "pending"),
            (11, 0.55, "q", "labeled"),
        ],
    )
    conn.commit()
    conn.close()

    resp = await dr_client.get("/api/danbooru/candidates/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    assert data["pending"] == 1
    assert data["labeled"] == 1
    # Required keys per task brief
    for key in (
        "total",
        "pending",
        "labeled",
        "score_distribution",
        "rating_distribution",
        "avg_score",
        "top_score",
        "histogram",
    ):
        assert key in data
    assert data["top_score"] == pytest.approx(0.92, abs=1e-3)
