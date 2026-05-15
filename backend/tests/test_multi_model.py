"""Tests for /api/models endpoints (multi-model registry).

The default `client` fixture's app does not register `multi_model.router`,
so we extend it via a per-test fixture.
"""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient


@pytest_asyncio.fixture()
async def mm_client(app):
    """Client with multi_model router included."""
    from routers import multi_model

    app.include_router(multi_model.router)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_list_models_empty(mm_client):
    """No-ML lifespan — state._models is empty."""
    resp = await mm_client.get("/api/models")
    assert resp.status_code == 200
    data = resp.json()
    assert data["models"] == {}
    assert data["active_model"] is None
    assert data["loaded_in_memory"] is None


@pytest.mark.asyncio
async def test_set_active_unknown_model_400(mm_client):
    """Switching to a model not in registry returns 400."""
    resp = await mm_client.post("/api/models/active", json={"model_key": "ghost"})
    assert resp.status_code == 400
    assert "Unknown model" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_list_models_reflects_state(mm_client, monkeypatch):
    """Inject a fake model into state._models and verify shape."""
    import state

    fake = {
        "model_name": "siglip-fake",
        "model_class": "NaFlexClassifier",
        "type": "siglip2",
        "cv_auc": 0.91,
        "n_samples": 100,
        "input_size": 384,
        "fold_aucs": [0.9, 0.92],
    }
    monkeypatch.setattr(state, "_models", {"fake_key": fake})
    monkeypatch.setattr(state, "_active_model", "fake_key")

    resp = await mm_client.get("/api/models")
    assert resp.status_code == 200
    data = resp.json()
    assert "fake_key" in data["models"]
    assert data["models"]["fake_key"]["is_active"] is True
    assert data["models"]["fake_key"]["cv_auc"] == 0.91
    assert data["active_model"] == "fake_key"


@pytest.mark.asyncio
async def test_set_active_model_success(mm_client, monkeypatch):
    """Set active to a known model key."""
    import state

    monkeypatch.setattr(state, "_models", {"k1": {"model_name": "m1"}, "k2": {"model_name": "m2"}})
    monkeypatch.setattr(state, "_active_model", "k1")

    resp = await mm_client.post("/api/models/active", json={"model_key": "k2"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["active_model"] == "k2"
