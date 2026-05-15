"""Tests for database initialization and schema."""

import sqlite3

import pytest


def test_labels_db_schema(init_databases):
    import config

    conn = sqlite3.connect(str(config.LABELS_DB_PATH))
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "labels" in tables
    assert "tags" in tables
    assert "vision_scores" in tables
    assert "auto_tags" in tables
    conn.close()


def test_labels_db_vision_scores_composite_pk(init_databases):
    import config

    conn = sqlite3.connect(str(config.LABELS_DB_PATH))
    ddl = conn.execute("SELECT sql FROM sqlite_master WHERE name='vision_scores'").fetchone()[0]
    assert "PRIMARY KEY (image_id, model_name)" in ddl
    conn.close()


def test_danbooru_labels_db_schema(init_databases):
    import config

    conn = sqlite3.connect(str(config.DANBOORU_LABELS_DB_PATH))
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "labels" in tables
    assert "tags" in tables
    conn.close()


def test_labels_db_verdict_constraint(init_databases):
    import config

    conn = sqlite3.connect(str(config.LABELS_DB_PATH))
    conn.execute("INSERT INTO labels (image_id, verdict) VALUES (1, 'liked')")
    conn.commit()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO labels (image_id, verdict) VALUES (2, 'invalid_verdict')")
    conn.close()
