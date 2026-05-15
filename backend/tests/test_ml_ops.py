"""Tests for /api/ml/* and /api/danbooru/gpu/* endpoints + _build_subprocess_env unit.

Mocks all subprocess managers so no external processes are spawned.
"""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# ---------------------------------------------------------------------------
# Unit tests for _build_subprocess_env (no FastAPI involved)
# ---------------------------------------------------------------------------


def test_build_subprocess_env_cpu_mode(monkeypatch):
    """In cpu mode, no GPU env vars set; thread-count vars present."""
    from routers import ml_ops

    monkeypatch.setattr(
        ml_ops,
        "_load_gpu_config",
        lambda: {"inference_mode": "cpu", "url": "", "batch_size": 16, "enabled": False},
    )
    env = ml_ops._build_subprocess_env()
    assert env["INFERENCE_MODE"] == "cpu"
    assert env["OMP_NUM_THREADS"] == "6"
    assert "GPU_INFERENCE_URL" not in env
    assert "GPU_BATCH_SIZE" not in env
    assert "CUDA_VISIBLE_DEVICES" not in env or env.get("CUDA_VISIBLE_DEVICES") != "0"


def test_build_subprocess_env_remote_mode(monkeypatch):
    """In remote mode, GPU url + batch size are exported."""
    from routers import ml_ops

    monkeypatch.setattr(
        ml_ops,
        "_load_gpu_config",
        lambda: {
            "inference_mode": "remote",
            "url": "http://gpu.local:9000",
            "batch_size": 32,
            "enabled": True,
        },
    )
    env = ml_ops._build_subprocess_env()
    assert env["INFERENCE_MODE"] == "remote"
    assert env["GPU_INFERENCE_URL"] == "http://gpu.local:9000"
    assert env["GPU_BATCH_SIZE"] == "32"


def test_build_subprocess_env_local_gpu_mode(monkeypatch):
    """local_gpu mode pins CUDA_VISIBLE_DEVICES=0 and drops remote vars."""
    from routers import ml_ops

    monkeypatch.setattr(
        ml_ops,
        "_load_gpu_config",
        lambda: {"inference_mode": "local_gpu", "url": "", "batch_size": 16, "enabled": False},
    )
    env = ml_ops._build_subprocess_env()
    assert env["INFERENCE_MODE"] == "local_gpu"
    assert env["CUDA_VISIBLE_DEVICES"] == "0"
    assert "GPU_INFERENCE_URL" not in env


def test_build_subprocess_env_extras_override(monkeypatch):
    """Caller-supplied extras override base values (and add new keys)."""
    from routers import ml_ops

    monkeypatch.setattr(
        ml_ops,
        "_load_gpu_config",
        lambda: {"inference_mode": "cpu", "url": "", "batch_size": 16, "enabled": False},
    )
    env = ml_ops._build_subprocess_env({"FOO": "bar", "INFERENCE_MODE": "override"})
    assert env["FOO"] == "bar"
    assert env["INFERENCE_MODE"] == "override"


# ---------------------------------------------------------------------------
# Endpoint tests — register ml_ops router on test app
# ---------------------------------------------------------------------------


class _FakeManagedSubprocess:
    """Stand-in for ManagedSubprocess that doesn't fork anything."""

    def __init__(self, running: bool = False, log: str = "") -> None:
        self._running = running
        self._log = log
        self.process = None

    def is_running(self) -> bool:
        return self._running

    async def read_log_tail(self, max_bytes: int = 5000) -> str:
        return self._log

    async def start(self, *args, **kwargs):
        self._running = True
        return {"started": True, "pid": 12345}

    async def stop(self, kill_external: bool = False):
        self._running = False
        return {"stopped": True}


@pytest_asyncio.fixture()
async def ml_client(app, monkeypatch):
    """Test client with ml_ops router included and subprocesses mocked."""
    import state
    from routers import ml_ops

    fake_subs = {key: _FakeManagedSubprocess() for key in state._subprocesses}
    monkeypatch.setattr(state, "_subprocesses", fake_subs)

    # Avoid touching the real GPU config file on disk.
    monkeypatch.setattr(
        ml_ops,
        "_load_gpu_config",
        lambda: {"inference_mode": "cpu", "url": "", "batch_size": 16, "enabled": False},
    )

    app.include_router(ml_ops.router)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_gpu_config_get(ml_client):
    """Reads the (mocked) GPU config; remote_health is None when not enabled."""
    resp = await ml_client.get("/api/danbooru/gpu/config")
    assert resp.status_code == 200
    data = resp.json()
    assert data["inference_mode"] == "cpu"
    assert data["url"] == ""
    assert data["remote_health"] is None


@pytest.mark.asyncio
async def test_gpu_test_no_url(ml_client):
    """Without a configured URL, the test endpoint returns ok=False with explanatory error."""
    resp = await ml_client.post("/api/danbooru/gpu/test")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is False
    assert "GPU" in data["error"] or "未设置" in data["error"]


@pytest.mark.asyncio
async def test_inference_status_shape(ml_client):
    """status endpoint always responds 200 even with no models loaded."""
    resp = await ml_client.get("/api/inference/status")
    assert resp.status_code == 200
    data = resp.json()
    # Required keys regardless of CUDA availability
    for key in (
        "inference_mode",
        "current_device",
        "cuda_available",
        "cnn_loaded",
        "loaded_models",
        "active_model",
    ):
        assert key in data
    assert data["cnn_loaded"] is False
    assert data["loaded_models"] == []


@pytest.mark.asyncio
async def test_ml_models_info_empty(ml_client):
    """With no models registered, response shape stays well-formed."""
    resp = await ml_client.get("/api/ml/models")
    assert resp.status_code == 200
    data = resp.json()
    assert data["xgboost"] is None
    assert data["cnn"] is None
    assert data["vision_models"] == {}
    assert data["active_model"] is None


@pytest.mark.asyncio
async def test_prefetch_status_not_running(ml_client):
    """Mocked prefetch manager reports not running."""
    resp = await ml_client.get("/api/danbooru/prefetch/status")
    assert resp.status_code == 200
    assert resp.json() == {"running": False}


@pytest.mark.asyncio
async def test_prefetch_stop_when_idle(ml_client):
    """Stop on an idle manager returns stopped=True (mock behavior)."""
    resp = await ml_client.post("/api/danbooru/prefetch/stop")
    assert resp.status_code == 200
    data = resp.json()
    assert data["running"] is False


@pytest.mark.asyncio
async def test_inference_mode_invalid(ml_client):
    """Unknown mode rejected with 400."""
    resp = await ml_client.post("/api/inference/mode", json={"mode": "bogus"})
    assert resp.status_code == 400
