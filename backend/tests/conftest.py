"""Shared test fixtures for the Sieve backend test suite.

Creates temporary databases and a test FastAPI app that skips ML model loading.
"""

import os
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient


@pytest.fixture(scope="session", autouse=True)
def _set_test_env():
    """Ensure env is set before any imports."""
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"


@pytest.fixture()
def tmp_crawler(tmp_path):
    """Create a temporary CRAWLER_DIR with dedup.db and fake image files."""
    crawler_dir = tmp_path / "crawler"
    crawler_dir.mkdir()
    downloads = crawler_dir / "downloads" / "2024-01-01" / "pixiv"
    downloads.mkdir(parents=True)

    # Create a fake image (1x1 white PNG)
    import struct
    import zlib

    def make_png():
        raw = b"\x00\xff\xff\xff"
        compressed = zlib.compress(raw)
        ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)

        def chunk(ctype, data):
            c = ctype + data
            return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)

        return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", compressed) + chunk(b"IEND", b"")

    (downloads / "test1.jpg").write_bytes(make_png())
    (downloads / "test2.jpg").write_bytes(make_png())

    # Create dedup.db
    db = sqlite3.connect(str(crawler_dir / "dedup.db"))
    db.execute("""CREATE TABLE images (
        id INTEGER PRIMARY KEY, source TEXT, source_id TEXT,
        phash TEXT, file_path TEXT, url TEXT, created_at TIMESTAMP
    )""")
    db.execute("""CREATE TABLE novels (
        id INTEGER PRIMARY KEY, source TEXT, source_id TEXT,
        title TEXT, author TEXT, file_path TEXT, url TEXT, created_at TIMESTAMP
    )""")
    db.executemany(
        "INSERT INTO images VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            (
                1,
                "pixiv",
                "100",
                "aaa",
                "downloads/2024-01-01/pixiv/test1.jpg",
                "https://pixiv.net/100",
                "2024-01-01 12:00:00",
            ),
            (
                2,
                "pixiv",
                "101",
                "bbb",
                "downloads/2024-01-01/pixiv/test2.jpg",
                "https://pixiv.net/101",
                "2024-01-01 13:00:00",
            ),
            (
                3,
                "danbooru",
                "200",
                "ccc",
                "downloads/2024-01-01/pixiv/test1.jpg",
                "https://danbooru.donmai.us/200",
                "2024-01-02 10:00:00",
            ),
        ],
    )
    db.commit()
    db.close()
    return crawler_dir


@pytest.fixture()
def patch_config(tmp_crawler, tmp_path, monkeypatch):
    """Patch all config paths to use temporary directories."""
    import config

    monkeypatch.setattr(config, "CRAWLER_DIR", tmp_crawler)
    monkeypatch.setattr(config, "DB_PATH", tmp_crawler / "dedup.db")
    monkeypatch.setattr(config, "DOWNLOADS_DIR", tmp_crawler / "downloads")
    monkeypatch.setattr(config, "LABELS_DB_PATH", tmp_path / "labels.db")
    monkeypatch.setattr(config, "DANBOORU_LABELS_DB_PATH", tmp_path / "danbooru_labels.db")
    monkeypatch.setattr(config, "DANBOORU_LIKES_DIR", tmp_path / "danbooru_liked")
    monkeypatch.setattr(config, "PREFERENCE_MODEL_PATH", tmp_path / "nonexistent.joblib")
    monkeypatch.setattr(config, "CNN_MODEL_PATH", tmp_path / "nonexistent.pt")
    monkeypatch.setattr(config, "CANDIDATES_DB_PATH", tmp_path / "candidates.db")
    monkeypatch.setattr(config, "PROJECT_ROOT", Path(__file__).parent.parent.parent)

    # Also patch state module constants that were computed at import time
    import state

    monkeypatch.setattr(state, "THUMBS_DIR", tmp_crawler / ".thumbs")
    monkeypatch.setattr(state, "_ALLOWED_ROOTS", {tmp_crawler.resolve()})

    return tmp_path


@pytest.fixture()
def init_databases(patch_config):
    """Initialize labels and danbooru_labels databases."""
    from database import _init_auto_tags_table, _init_danbooru_labels_db, _init_labels_db

    _init_labels_db()
    _init_auto_tags_table()
    _init_danbooru_labels_db()


@pytest.fixture()
def reset_state(monkeypatch):
    """Reset mutable state between tests."""
    import state

    monkeypatch.setattr(state, "_preference_model", None)
    monkeypatch.setattr(state, "_cnn_model", None)
    monkeypatch.setattr(state, "_models", {})
    monkeypatch.setattr(state, "_active_model", None)
    monkeypatch.setattr(state, "_loaded_model_key", None)
    monkeypatch.setattr(state, "_inference_device", "cpu")
    monkeypatch.setattr(state, "_cuda_available_cached", False)
    monkeypatch.setattr(state, "_db_pool", None)
    monkeypatch.setattr(state, "_labels_pool", None)
    monkeypatch.setattr(state, "_danbooru_labels_pool", None)
    monkeypatch.setattr(state, "_candidates_pool", None)
    monkeypatch.setattr(state, "_danbooru_client", None)


@pytest_asyncio.fixture()
async def app(patch_config, init_databases, reset_state):
    """Create a test FastAPI app with a simplified lifespan (no ML models)."""
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware

    import state
    from database import get_sync_db

    @asynccontextmanager
    async def test_lifespan(app):
        state.THUMBS_DIR.mkdir(parents=True, exist_ok=True)
        with get_sync_db(readonly=False) as conn:
            conn.execute("CREATE INDEX IF NOT EXISTS idx_images_file_created_at ON images(file_path, created_at DESC)")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_images_source_file_created_at ON images(source, file_path, created_at DESC)"
            )
        yield
        # Cleanup pools
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

    test_app = FastAPI(title="Sieve-Test", lifespan=test_lifespan)
    test_app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

    from routers import (
        autotags,
        images,
        labeler,
        novels,
        stats,
        vision_scores,
    )

    test_app.include_router(images.router)
    test_app.include_router(novels.router)
    test_app.include_router(stats.router)
    test_app.include_router(labeler.router)
    test_app.include_router(vision_scores.router)
    test_app.include_router(autotags.router)

    return test_app


@pytest_asyncio.fixture()
async def client(app):
    """Async HTTP test client."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
