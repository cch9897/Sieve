import asyncio
import logging
import os
import sys as _sys
from pathlib import Path
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

import state
from config import PROJECT_ROOT
from models import (
    _check_cuda_available,
    _cuda_info,
    _get_torch_device,
    _load_gpu_config,
    _migrate_cnn_to_device,
    _reload_preference_model,
    _save_gpu_config,
)
from subprocess_manager import make_header

logger = logging.getLogger(__name__)

router = APIRouter()


def _build_subprocess_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """Return an env dict for ManagedSubprocess: base os.environ + GPU config + caller extras."""
    env = os.environ.copy()
    env.update(
        {
            "OMP_NUM_THREADS": "6",
            "MKL_NUM_THREADS": "6",
            "TORCH_NUM_THREADS": "6",
            "OPENBLAS_NUM_THREADS": "6",
        }
    )
    gpu_cfg = _load_gpu_config()
    inf_mode = gpu_cfg.get("inference_mode", "cpu")
    env["INFERENCE_MODE"] = inf_mode
    if inf_mode == "remote" and gpu_cfg.get("url"):
        env["GPU_INFERENCE_URL"] = gpu_cfg["url"]
        env["GPU_BATCH_SIZE"] = str(gpu_cfg["batch_size"])
    else:
        env.pop("GPU_INFERENCE_URL", None)
        env.pop("GPU_BATCH_SIZE", None)
    if inf_mode == "local_gpu":
        env["CUDA_VISIBLE_DEVICES"] = "0"
    if extra:
        env.update(extra)
    return env


# ---------------------------------------------------------------------------
# GPU Config
# ---------------------------------------------------------------------------


@router.get("/api/danbooru/gpu/config")
async def gpu_config_get():
    """Get current GPU inference settings."""
    cfg = _load_gpu_config()
    # Probe remote health if enabled
    health = None
    if cfg["enabled"] and cfg["url"]:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(f"{cfg['url']}/health")
                if resp.status_code == 200:
                    health = resp.json()
        except Exception as e:
            logger.warning("Failed to read GPU config: %s", e)
    return {**cfg, "remote_health": health}


class GpuConfigUpdate(BaseModel):
    url: str | None = None
    batch_size: int | None = None
    enabled: bool | None = None


@router.post("/api/danbooru/gpu/config")
async def gpu_config_set(body: GpuConfigUpdate):
    """Update GPU inference settings."""
    cfg = _load_gpu_config()
    if body.url is not None:
        cfg["url"] = body.url.rstrip("/")
    if body.batch_size is not None:
        cfg["batch_size"] = max(1, min(64, body.batch_size))
    if body.enabled is not None:
        cfg["enabled"] = body.enabled
    _save_gpu_config(cfg)
    return cfg


# ---------------------------------------------------------------------------
# Inference Mode APIs
# ---------------------------------------------------------------------------


@router.get("/api/inference/status")
async def inference_status():
    """Get current inference mode, device info, and model status."""
    cfg = _load_gpu_config()
    cuda_avail = await asyncio.to_thread(_check_cuda_available)
    cuda = await asyncio.to_thread(_cuda_info) if cuda_avail else None
    return {
        "inference_mode": cfg.get("inference_mode", "cpu"),
        "current_device": _get_torch_device(),
        "cuda_available": cuda_avail,
        "cuda_info": cuda,
        "cnn_loaded": bool(state._models),
        "cnn_model_name": state._models[state._active_model]["model_name"]
        if state._active_model and state._active_model in state._models
        else None,
        "cnn_cv_auc": state._models[state._active_model].get("cv_auc")
        if state._active_model and state._active_model in state._models
        else None,
        "loaded_models": list(state._models.keys()),
        "loaded_in_memory": state._loaded_model_key,
        "active_model": state._active_model,
        "remote_url": cfg.get("url", ""),
        "remote_enabled": cfg.get("enabled", False),
        "remote_batch_size": cfg.get("batch_size", 16),
    }


class InferenceModeUpdate(BaseModel):
    mode: str  # "cpu", "local_gpu", "remote"


@router.post("/api/inference/mode")
async def inference_mode_set(body: InferenceModeUpdate):
    """Switch inference mode. Triggers model device migration for local modes."""
    mode = body.mode
    if mode not in ("cpu", "local_gpu", "remote"):
        raise HTTPException(status_code=400, detail="mode must be cpu, local_gpu, or remote")

    # Check CUDA availability for local_gpu
    if mode == "local_gpu":
        try:
            import torch

            if not torch.cuda.is_available():
                raise HTTPException(status_code=400, detail="CUDA 不可用，无法切换到本地 GPU 模式")
        except ImportError:
            raise HTTPException(status_code=400, detail="PyTorch 未安装 CUDA 支持")

    # Persist
    cfg = _load_gpu_config()
    cfg["inference_mode"] = mode
    # Sync legacy enabled flag
    cfg["enabled"] = mode == "remote"
    _save_gpu_config(cfg)

    # Migrate model device
    if mode == "local_gpu":
        await asyncio.to_thread(_migrate_cnn_to_device, "cuda")
    elif mode in ("cpu", "remote"):
        await asyncio.to_thread(_migrate_cnn_to_device, "cpu")

    return {
        "inference_mode": mode,
        "current_device": _get_torch_device(),
        "cuda_info": _cuda_info(),
    }


@router.post("/api/danbooru/gpu/test")
async def gpu_test():
    """Test connection to the remote GPU server."""
    cfg = _load_gpu_config()
    if not cfg["url"]:
        return {"ok": False, "error": "未设置 GPU 地址"}
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            resp = await client.get(f"{cfg['url']}/health")
            if resp.status_code == 200:
                return {"ok": True, "health": resp.json()}
            return {"ok": False, "error": f"HTTP {resp.status_code}"}
    except Exception as e:
        logger.exception("GPU server health probe failed")
        return {"ok": False, "error": str(e)}


# ---------------------------------------------------------------------------
# Helper: extract HTTPException detail strings produced by ManagedSubprocess
# ---------------------------------------------------------------------------


def _detail(exc: HTTPException) -> str:
    return str(exc.detail) if exc.detail is not None else ""


# ---------------------------------------------------------------------------
# Prefetch Candidates Process Control
# ---------------------------------------------------------------------------


@router.get("/api/danbooru/prefetch/status")
async def prefetch_status():
    """Get AI pre-screening process status."""
    mgr = state._subprocesses["prefetch"]
    running = await asyncio.to_thread(mgr.is_running)
    return {"running": running}


@router.post("/api/danbooru/prefetch/start")
async def prefetch_start(
    mode: str = Query("tag+vision", pattern="^(tag\\+vision|vision-only)$"),
    threshold: Optional[float] = Query(None, ge=0.0, le=1.0),
    model: Optional[str] = Query(None),
):
    """Start the AI pre-screening process. mode: tag+vision or vision-only."""
    mgr = state._subprocesses["prefetch"]
    if await asyncio.to_thread(mgr.is_running):
        return {"running": True, "message": "已在运行"}

    extras: dict[str, str] = {}
    _proxy = os.environ.get("PREFETCH_PROXY", "")
    if _proxy:
        extras.update(
            {
                "https_proxy": _proxy,
                "http_proxy": _proxy,
                "HTTPS_PROXY": _proxy,
                "HTTP_PROXY": _proxy,
                "no_proxy": os.environ.get("PREFETCH_NO_PROXY", "localhost,127.0.0.1"),
                "NO_PROXY": os.environ.get("PREFETCH_NO_PROXY", "localhost,127.0.0.1"),
            }
        )
    model_key = model or state._active_model
    if model_key and model_key in state._models:
        source_file = state._models[model_key].get("source_file", "")
        if source_file:
            extras["CNN_MODEL_PATH"] = str(PROJECT_ROOT / "classifier" / source_file)
    _prefetch_env = _build_subprocess_env(extras)
    cmd = [
        "taskset",
        "-c",
        "0-5",
        "systemd-run",
        "--user",
        "--scope",
        "-p",
        "MemoryMax=16G",
        "nice",
        "-n",
        "15",
        "ionice",
        "-c",
        "3",
        str(Path(__file__).parent.parent / "venv" / "bin" / "python"),
        "-u",
        str(state.PREFETCH_SCRIPT),
        "--mode",
        mode,
    ]
    if threshold is not None:
        cmd.extend(["--min-score", str(threshold)])
    try:
        await mgr.start(
            cmd,
            env=_prefetch_env,
            cwd=state.PREFETCH_SCRIPT.parent,
            append_log=True,
            wait_after=1.0,
        )
    except HTTPException as e:
        detail = _detail(e)
        if detail == "already_running":
            return {"running": True, "message": "已在运行"}
        if detail.startswith("exited:"):
            code = detail.split(":", 1)[1]
            return {"running": False, "message": f"启动失败 (exit code {code})"}
        return {"running": False, "message": f"启动失败: {detail}"}
    except Exception as e:
        logger.exception("Prefetch subprocess start failed")
        return {"running": False, "message": f"启动失败: {e}"}
    return {"running": True, "message": "已启动"}


@router.post("/api/danbooru/prefetch/stop")
async def prefetch_stop():
    """Stop the AI pre-screening process (also kills any externally-started instances)."""
    mgr = state._subprocesses["prefetch"]
    result = await mgr.stop(kill_external=True)
    return {"running": False, "stopped": result["stopped"]}


# ---------------------------------------------------------------------------
# Candidates Re-score API
# ---------------------------------------------------------------------------


@router.post("/api/danbooru/candidates/rescore")
async def candidates_rescore_start():
    """Re-score all pending candidates with the active vision model (GPU batch)."""
    mgr = state._subprocesses["rescore"]
    if await asyncio.to_thread(mgr.is_running):
        return {"status": "already_running"}

    extras: dict[str, str] = {}
    model_key = state._active_model
    if model_key and model_key in state._models:
        source_file = state._models[model_key].get("source_file", "")
        if source_file:
            extras["CNN_MODEL_PATH"] = str(PROJECT_ROOT / "classifier" / source_file)
    _rescore_env = _build_subprocess_env(extras)

    cmd = [
        str(Path(__file__).parent.parent / "venv" / "bin" / "python"),
        "-u",
        str(state.PREFETCH_SCRIPT),
        "--rescore",
    ]
    try:
        await mgr.start(
            cmd,
            env=_rescore_env,
            cwd=state.PREFETCH_SCRIPT.parent,
            append_log=False,
            header=make_header("Rescore"),
        )
    except HTTPException as e:
        detail = _detail(e)
        if detail == "already_running":
            return {"status": "already_running"}
        return {"status": "failed", "error": detail}
    except Exception as e:
        logger.exception("Candidates rescore subprocess start failed")
        return {"status": "failed", "error": str(e)}
    return {"status": "started", "model": model_key}


@router.get("/api/danbooru/candidates/rescore/status")
async def candidates_rescore_status():
    """Get re-scoring status and log."""
    mgr = state._subprocesses["rescore"]
    running = await asyncio.to_thread(mgr.is_running)
    log_content = await mgr.read_log_tail()
    return {"running": running, "log": log_content}


@router.post("/api/danbooru/candidates/rescore/stop")
async def candidates_rescore_stop():
    """Stop re-scoring."""
    mgr = state._subprocesses["rescore"]
    result = await mgr.stop()
    return {"stopped": result["stopped"]}


# ---------------------------------------------------------------------------
# ML Model Management APIs
# ---------------------------------------------------------------------------


@router.get("/api/ml/models")
async def ml_models_info():
    """Get preference classifier models info."""
    xgboost_info = None
    cnn_info = None
    if state._preference_model is not None:
        xgboost_info = {
            "loaded": True,
            "auc": state._preference_model.get("auc", 0),
            "n_samples": state._preference_model.get("n_samples", 0),
            "n_liked": state._preference_model.get("n_liked", 0),
            "n_disliked": state._preference_model.get("n_disliked", 0),
            "model_type": state._preference_model.get("model_type", "unknown"),
            "vocab_size": len(state._preference_model.get("tag_vocab", [])),
        }
    if state._cnn_model is not None:
        cnn_info = {
            "loaded": True,
            "model_name": state._cnn_model.get("model_name", "unknown"),
            "model_class": state._cnn_model.get("model_class", "timm"),
            "cv_auc": state._cnn_model.get("cv_auc", 0),
            "n_samples": state._cnn_model.get("n_samples", 0),
            "input_size": state._cnn_model.get("input_size", 224),
            "fold_aucs": state._cnn_model.get("fold_aucs", []),
        }
    # Include all vision models
    vision_models = {}
    for key, info in state._models.items():
        vision_models[key] = {
            "loaded": True,
            "model_name": info.get("model_name", "unknown"),
            "model_class": info.get("model_class", "unknown"),
            "type": info.get("type"),
            "cv_auc": info.get("cv_auc", 0),
            "n_samples": info.get("n_samples", 0),
            "input_size": info.get("input_size"),
            "fold_aucs": info.get("fold_aucs", []),
            "is_active": key == state._active_model,
        }
    return {
        "xgboost": xgboost_info,
        "cnn": cnn_info,
        "vision_models": vision_models,
        "active_model": state._active_model,
    }


# ---------------------------------------------------------------------------
# Retrain XGBoost
# ---------------------------------------------------------------------------


@router.post("/api/ml/retrain-xgboost")
async def ml_retrain_start():
    """Start XGBoost retraining."""
    mgr = state._subprocesses["retrain"]
    if await asyncio.to_thread(mgr.is_running):
        return {"status": "already_running"}
    cmd = ["bash", str(state.RETRAIN_SCRIPT)]
    try:
        await mgr.start(
            cmd,
            cwd=state.RETRAIN_SCRIPT.parent,
            append_log=False,
            header=make_header("Retrain"),
        )
    except HTTPException as e:
        detail = _detail(e)
        if detail == "already_running":
            return {"status": "already_running"}
        return {"status": "failed", "error": detail}
    except Exception as e:
        logger.exception("XGBoost retrain subprocess start failed")
        return {"status": "failed", "error": str(e)}
    return {"status": "started"}


@router.get("/api/ml/retrain-xgboost/status")
async def ml_retrain_status():
    """Get retrain status and latest log."""
    mgr = state._subprocesses["retrain"]
    running = await asyncio.to_thread(mgr.is_running)
    log_content = await mgr.read_log_tail()
    if not running and mgr.process is not None:
        exit_code = mgr.process.poll()
        if exit_code == 0:
            # Success - hot reload model
            await _reload_preference_model()
            return {"running": False, "finished": True, "exit_code": 0, "log": log_content}
        return {"running": False, "finished": True, "exit_code": exit_code, "log": log_content}
    return {"running": running, "finished": False, "exit_code": None, "log": log_content}


# ---------------------------------------------------------------------------
# Pack Dataset
# ---------------------------------------------------------------------------


@router.post("/api/ml/pack-dataset")
async def ml_pack_start(max_size: int = Query(1024, ge=0, le=4096)):
    """Start dataset packing. max_size=0 means original resolution."""
    mgr = state._subprocesses["pack"]
    if await asyncio.to_thread(mgr.is_running):
        return {"status": "already_running"}
    label = "原始分辨率" if max_size == 0 else f"{max_size}px"
    cmd = ["bash", str(state.PACK_SCRIPT), "--include-db", "--max-size", str(max_size)]
    try:
        await mgr.start(
            cmd,
            cwd=state.PACK_SCRIPT.parent,
            append_log=False,
            header=make_header("Pack", extra=label),
        )
    except HTTPException as e:
        detail = _detail(e)
        if detail == "already_running":
            return {"status": "already_running"}
        return {"status": "failed", "error": detail}
    except Exception as e:
        logger.exception("Pack dataset subprocess start failed")
        return {"status": "failed", "error": str(e)}
    return {"status": "started"}


@router.get("/api/ml/pack-dataset/status")
async def ml_pack_status():
    """Get pack status and latest log."""
    mgr = state._subprocesses["pack"]
    running = await asyncio.to_thread(mgr.is_running)
    log_content = await mgr.read_log_tail()
    if not running and mgr.process is not None:
        exit_code = mgr.process.poll()
        return {"running": False, "finished": True, "exit_code": exit_code, "log": log_content}
    return {"running": running, "finished": False, "exit_code": None, "log": log_content}


# ---------------------------------------------------------------------------
# Vision Score
# ---------------------------------------------------------------------------


class VscoreStartRequest(BaseModel):
    model: str | None = None  # model key from state._models, or "all"


@router.post("/api/ml/vision-score")
async def ml_vscore_start(req: VscoreStartRequest = VscoreStartRequest()):
    """Start vision scoring of crawler images."""
    mgr = state._subprocesses["vscore"]
    if await asyncio.to_thread(mgr.is_running):
        return {"status": "already_running"}

    cmd = [_sys.executable, str(state.VSCORE_SCRIPT)]

    # Determine which model to run
    model_key = req.model or state._active_model
    if model_key and model_key in state._models:
        info = state._models[model_key]
        model_type = "siglip2" if info.get("type") == "siglip2" else "eva02"
        source_file = info.get("source_file", "")
        if source_file:
            model_path = state.VSCORE_SCRIPT.parent.parent / "classifier" / source_file
            cmd.extend(["--model", model_type, "--model-path", str(model_path)])
        else:
            cmd.extend(["--model", model_type])
    # else: default --model all

    try:
        await mgr.start(
            cmd,
            cwd=state.VSCORE_SCRIPT.parent,
            append_log=False,
            header=make_header("Vision scoring"),
        )
    except HTTPException as e:
        detail = _detail(e)
        if detail == "already_running":
            return {"status": "already_running"}
        return {"status": "failed", "error": detail}
    except Exception as e:
        logger.exception("Vision scoring subprocess start failed")
        return {"status": "failed", "error": str(e)}
    return {"status": "started", "model": model_key}


@router.get("/api/ml/vision-score/status")
async def ml_vscore_status():
    """Get vision scoring status and latest log."""
    mgr = state._subprocesses["vscore"]
    running = await asyncio.to_thread(mgr.is_running)
    log_content = await mgr.read_log_tail()
    if not running and mgr.process is not None:
        exit_code = mgr.process.poll()
        # Invalidate vision-scores stats cache so freshly scored data is visible.
        if exit_code == 0:
            from routers.vision_scores import _vision_scores_stats_cached

            await _vision_scores_stats_cached.cache_clear()
        return {"running": False, "finished": True, "exit_code": exit_code, "log": log_content}
    return {"running": running, "finished": False, "exit_code": None, "log": log_content}


# ---------------------------------------------------------------------------
# Tag Liked Train
# ---------------------------------------------------------------------------


@router.post("/api/ml/tag-train")
async def ml_tag_train_start():
    """Start incremental sync + WD14 tagging for liked training set (GPU)."""
    mgr = state._subprocesses["tag_train"]
    if await asyncio.to_thread(mgr.is_running):
        return {"status": "already_running"}
    venv_python = PROJECT_ROOT / "backend" / "venv" / "bin" / "python"
    cmd = [str(venv_python), str(state.TAG_TRAIN_SCRIPT)]
    try:
        await mgr.start(
            cmd,
            cwd=state.TAG_TRAIN_SCRIPT.parent,
            append_log=False,
            header=make_header("Tag train"),
        )
    except HTTPException as e:
        detail = _detail(e)
        if detail == "already_running":
            return {"status": "already_running"}
        return {"status": "failed", "error": detail}
    except Exception as e:
        logger.exception("Tag train subprocess start failed")
        return {"status": "failed", "error": str(e)}
    return {"status": "started"}


@router.get("/api/ml/tag-train/status")
async def ml_tag_train_status():
    """Get tag-train status and latest log."""
    mgr = state._subprocesses["tag_train"]
    running = await asyncio.to_thread(mgr.is_running)
    log_content = await mgr.read_log_tail()
    if not running and mgr.process is not None:
        exit_code = mgr.process.poll()
        return {"running": False, "finished": True, "exit_code": exit_code, "log": log_content}
    return {"running": running, "finished": False, "exit_code": None, "log": log_content}
