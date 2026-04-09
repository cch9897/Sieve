"""Tests for pure utility functions."""

from pathlib import Path


def test_safe_under_crawler_valid(patch_config, tmp_crawler):
    import state
    state._ALLOWED_ROOTS = {tmp_crawler.resolve()}
    assert state._safe_under_crawler(tmp_crawler / "downloads" / "test.jpg") is True


def test_safe_under_crawler_traversal(patch_config, tmp_crawler):
    import state
    state._ALLOWED_ROOTS = {tmp_crawler.resolve()}
    assert state._safe_under_crawler(Path("/etc/passwd")) is False


def test_model_db_name_missing():
    import state
    assert state._model_db_name("nonexistent") == "nonexistent"


def test_active_model_db_name_none():
    import state
    state._active_model = None
    assert state._active_model_db_name() == ""
