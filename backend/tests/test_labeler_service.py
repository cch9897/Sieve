"""Tests for services.labeler_service.

Exercises both LabelerConfig variants:
- LOCAL_LABELER (no extra columns) against labels.db
- DANBOORU_LABELER (ext/score/rating/tags) against danbooru_labels.db
"""

import aiosqlite
import pytest
import pytest_asyncio

from services import labeler_service as svc


@pytest_asyncio.fixture()
async def local_db(init_databases):
    """Open the labels.db (local labeler schema)."""
    import config

    conn = await aiosqlite.connect(str(config.LABELS_DB_PATH))
    conn.row_factory = aiosqlite.Row
    try:
        yield conn
    finally:
        await conn.close()


@pytest_asyncio.fixture()
async def dan_db(init_databases):
    """Open the danbooru_labels.db (extended labels schema)."""
    import config

    conn = await aiosqlite.connect(str(config.DANBOORU_LABELS_DB_PATH))
    conn.row_factory = aiosqlite.Row
    try:
        yield conn
    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# apply_label
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_label_local_inserts_row(local_db):
    await svc.apply_label(local_db, svc.LOCAL_LABELER, image_id=1, verdict="liked")
    async with local_db.execute("SELECT image_id, verdict FROM labels WHERE image_id=1") as c:
        row = await c.fetchone()
    assert row is not None
    assert row["image_id"] == 1
    assert row["verdict"] == "liked"


@pytest.mark.asyncio
async def test_apply_label_with_user_tags(local_db):
    await svc.apply_label(
        local_db,
        svc.LOCAL_LABELER,
        image_id=2,
        verdict="liked",
        user_tags=["cat", "dog", " "],  # blank should be filtered
    )
    async with local_db.execute("SELECT tag FROM tags WHERE image_id=2 ORDER BY tag") as c:
        rows = await c.fetchall()
    tags = [r["tag"] for r in rows]
    assert "cat" in tags
    assert "dog" in tags
    assert "" not in tags  # blank filtered


@pytest.mark.asyncio
async def test_apply_label_upserts_on_conflict(local_db):
    await svc.apply_label(local_db, svc.LOCAL_LABELER, image_id=3, verdict="liked")
    await svc.apply_label(local_db, svc.LOCAL_LABELER, image_id=3, verdict="disliked")
    async with local_db.execute("SELECT verdict FROM labels WHERE image_id=3") as c:
        row = await c.fetchone()
    assert row["verdict"] == "disliked"


@pytest.mark.asyncio
async def test_apply_label_danbooru_with_extra_columns(dan_db):
    await svc.apply_label(
        dan_db,
        svc.DANBOORU_LABELER,
        image_id=42,
        verdict="liked",
        user_tags=None,
        extra_values={"ext": "jpg", "score": 100, "rating": "s", "tags": "tag_a tag_b"},
    )
    async with dan_db.execute("SELECT image_id, verdict, ext, score, rating, tags FROM labels WHERE image_id=42") as c:
        row = await c.fetchone()
    assert row["ext"] == "jpg"
    assert row["score"] == 100
    assert row["rating"] == "s"
    assert row["tags"] == "tag_a tag_b"


# ---------------------------------------------------------------------------
# remove_label
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_remove_label_clears_label_and_tags(local_db):
    await svc.apply_label(local_db, svc.LOCAL_LABELER, image_id=10, verdict="liked", user_tags=["a"])
    await svc.remove_label(local_db, svc.LOCAL_LABELER, image_id=10)

    async with local_db.execute("SELECT COUNT(*) FROM labels WHERE image_id=10") as c:
        assert (await c.fetchone())[0] == 0
    async with local_db.execute("SELECT COUNT(*) FROM tags WHERE image_id=10") as c:
        assert (await c.fetchone())[0] == 0


# ---------------------------------------------------------------------------
# replace_user_tags
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_replace_user_tags_overwrites_existing(local_db):
    await svc.apply_label(local_db, svc.LOCAL_LABELER, image_id=11, verdict="liked", user_tags=["old1", "old2"])
    await svc.replace_user_tags(local_db, svc.LOCAL_LABELER, image_id=11, tags=["new"])

    async with local_db.execute("SELECT tag FROM tags WHERE image_id=11") as c:
        rows = await c.fetchall()
    tags = {r["tag"] for r in rows}
    assert tags == {"new"}


# ---------------------------------------------------------------------------
# fetch_verdict_counts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_verdict_counts_empty(local_db):
    counts = await svc.fetch_verdict_counts(local_db, svc.LOCAL_LABELER)
    assert counts == {"liked": 0, "disliked": 0, "skipped": 0, "total_labeled": 0}


@pytest.mark.asyncio
async def test_fetch_verdict_counts_populated(local_db):
    await svc.apply_label(local_db, svc.LOCAL_LABELER, image_id=1, verdict="liked")
    await svc.apply_label(local_db, svc.LOCAL_LABELER, image_id=2, verdict="liked")
    await svc.apply_label(local_db, svc.LOCAL_LABELER, image_id=3, verdict="disliked")
    await svc.apply_label(local_db, svc.LOCAL_LABELER, image_id=4, verdict="skipped")

    counts = await svc.fetch_verdict_counts(local_db, svc.LOCAL_LABELER)
    assert counts == {"liked": 2, "disliked": 1, "skipped": 1, "total_labeled": 4}


@pytest.mark.asyncio
async def test_fetch_verdict_counts_danbooru_schema(dan_db):
    await svc.apply_label(
        dan_db,
        svc.DANBOORU_LABELER,
        image_id=10,
        verdict="liked",
        extra_values={"ext": "jpg"},
    )
    counts = await svc.fetch_verdict_counts(dan_db, svc.DANBOORU_LABELER)
    assert counts["liked"] == 1
    assert counts["total_labeled"] == 1


# ---------------------------------------------------------------------------
# fetch_history_page (filtering + pagination)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_history_page_basic(local_db):
    for i in range(1, 6):
        await svc.apply_label(local_db, svc.LOCAL_LABELER, image_id=i, verdict="liked")

    total, rows = await svc.fetch_history_page(
        local_db,
        svc.LOCAL_LABELER,
        select_columns="l.image_id, l.verdict, l.updated_at",
        verdict=None,
        tag=None,
        page=1,
        per_page=3,
    )
    assert total == 5
    assert len(rows) == 3


@pytest.mark.asyncio
async def test_fetch_history_page_filters_by_verdict(local_db):
    await svc.apply_label(local_db, svc.LOCAL_LABELER, image_id=1, verdict="liked")
    await svc.apply_label(local_db, svc.LOCAL_LABELER, image_id=2, verdict="disliked")
    await svc.apply_label(local_db, svc.LOCAL_LABELER, image_id=3, verdict="liked")

    total, rows = await svc.fetch_history_page(
        local_db,
        svc.LOCAL_LABELER,
        select_columns="l.image_id, l.verdict, l.updated_at",
        verdict="liked",
        tag=None,
        page=1,
        per_page=10,
    )
    assert total == 2
    for row in rows:
        # row[1] is the verdict column from select_columns
        assert row[1] == "liked"


@pytest.mark.asyncio
async def test_fetch_history_page_filters_by_tag(local_db):
    await svc.apply_label(local_db, svc.LOCAL_LABELER, image_id=1, verdict="liked", user_tags=["foo"])
    await svc.apply_label(local_db, svc.LOCAL_LABELER, image_id=2, verdict="liked", user_tags=["bar"])
    await svc.apply_label(local_db, svc.LOCAL_LABELER, image_id=3, verdict="liked", user_tags=["foo", "bar"])

    total, rows = await svc.fetch_history_page(
        local_db,
        svc.LOCAL_LABELER,
        select_columns="l.image_id, l.verdict, l.updated_at",
        verdict=None,
        tag="foo",
        page=1,
        per_page=10,
    )
    assert total == 2
    image_ids = {r[0] for r in rows}
    assert image_ids == {1, 3}


# ---------------------------------------------------------------------------
# fetch_top_user_tags / fetch_user_tags_map / fetch_export_targets
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_top_user_tags_orders_by_count(local_db):
    await svc.apply_label(local_db, svc.LOCAL_LABELER, image_id=1, verdict="liked", user_tags=["a", "b"])
    await svc.apply_label(local_db, svc.LOCAL_LABELER, image_id=2, verdict="liked", user_tags=["a"])
    await svc.apply_label(local_db, svc.LOCAL_LABELER, image_id=3, verdict="liked", user_tags=["a", "c"])

    top = await svc.fetch_top_user_tags(local_db, svc.LOCAL_LABELER, limit=10)
    counts = {t["tag"]: t["count"] for t in top}
    assert counts["a"] == 3
    # 'a' must come first.
    assert top[0]["tag"] == "a"


@pytest.mark.asyncio
async def test_fetch_user_tags_map(local_db):
    await svc.apply_label(local_db, svc.LOCAL_LABELER, image_id=1, verdict="liked", user_tags=["x", "y"])
    await svc.apply_label(local_db, svc.LOCAL_LABELER, image_id=2, verdict="liked", user_tags=["z"])

    tag_map = await svc.fetch_user_tags_map(local_db, svc.LOCAL_LABELER, [1, 2, 3])
    assert set(tag_map[1]) == {"x", "y"}
    assert tag_map[2] == ["z"]
    assert 3 not in tag_map  # no tags inserted for id=3


@pytest.mark.asyncio
async def test_fetch_user_tags_map_empty_list(local_db):
    assert await svc.fetch_user_tags_map(local_db, svc.LOCAL_LABELER, []) == {}


@pytest.mark.asyncio
async def test_fetch_export_targets_filters_by_verdict(local_db):
    await svc.apply_label(local_db, svc.LOCAL_LABELER, image_id=1, verdict="liked")
    await svc.apply_label(local_db, svc.LOCAL_LABELER, image_id=2, verdict="disliked")
    await svc.apply_label(local_db, svc.LOCAL_LABELER, image_id=3, verdict="liked")

    rows = await svc.fetch_export_targets(
        local_db,
        svc.LOCAL_LABELER,
        select_columns="l.image_id",
        verdict="liked",
        tag=None,
    )
    image_ids = {r[0] for r in rows}
    assert image_ids == {1, 3}
