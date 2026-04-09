import asyncio
import os
import signal
import subprocess
import time
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

router = APIRouter()


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
        except Exception:
            pass
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
        "cnn_model_name": state._models[state._active_model]['model_name'] if state._active_model and state._active_model in state._models else None,
        "cnn_cv_auc": state._models[state._active_model].get('cv_auc') if state._active_model and state._active_model in state._models else None,
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
        return {"ok": False, "error": str(e)}


# ---------------------------------------------------------------------------
# Prefetch Candidates Process Control
# ---------------------------------------------------------------------------

def _is_prefetch_running() -> bool:
    """Check if the prefetch_candidates process is running (ours or any)."""
    if state._prefetch_process is not None:
        ret = state._prefetch_process.poll()
        if ret is None:
            return True
        state._prefetch_process = None
    try:
        result = subprocess.run(
            ["pgrep", "-f", "prefetch_candidates.py"],
            capture_output=True, timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return False


@router.get("/api/danbooru/prefetch/status")
async def prefetch_status():
    """Get AI pre-screening process status."""
    running = await asyncio.to_thread(_is_prefetch_running)
    return {"running": running}


@router.post("/api/danbooru/prefetch/start")
async def prefetch_start(
    mode: str = Query("tag+vision", regex="^(tag\\+vision|vision-only)$"),
    threshold: Optional[float] = Query(None, ge=0.0, le=1.0),
    model: Optional[str] = Query(None),
):
    """Start the AI pre-screening process. mode: tag+vision or vision-only."""
    async with state._prefetch_lock:
        if _is_prefetch_running():
            return {"running": True, "message": "已在运行"}
        try:
            _prefetch_log = open(Path(__file__).parent.parent / "prefetch.log", "a")
            _prefetch_env = os.environ.copy()
            _prefetch_env.update({
                "OMP_NUM_THREADS": "6",
                "MKL_NUM_THREADS": "6",
                "TORCH_NUM_THREADS": "6",
                "OPENBLAS_NUM_THREADS": "6",
                "https_proxy": "socks5://192.168.50.10:7891",
                "http_proxy": "socks5://192.168.50.10:7891",
                "HTTPS_PROXY": "socks5://192.168.50.10:7891",
                "HTTP_PROXY": "socks5://192.168.50.10:7891",
                "no_proxy": "localhost,127.0.0.1,192.168.50.0/24",
                "NO_PROXY": "localhost,127.0.0.1,192.168.50.0/24",
            })
            # Pass GPU/inference config as env vars
            gpu_cfg = _load_gpu_config()
            inf_mode = gpu_cfg.get("inference_mode", "cpu")
            _prefetch_env["INFERENCE_MODE"] = inf_mode
            if inf_mode == "remote" and gpu_cfg.get("url"):
                _prefetch_env["GPU_INFERENCE_URL"] = gpu_cfg["url"]
                _prefetch_env["GPU_BATCH_SIZE"] = str(gpu_cfg["batch_size"])
            else:
                _prefetch_env.pop("GPU_INFERENCE_URL", None)
                _prefetch_env.pop("GPU_BATCH_SIZE", None)
            if inf_mode == "local_gpu":
                _prefetch_env["CUDA_VISIBLE_DEVICES"] = "0"
            # Pass active vision model path
            model_key = model or state._active_model
            if model_key and model_key in state._models:
                source_file = state._models[model_key].get('source_file', '')
                if source_file:
                    _prefetch_env["CNN_MODEL_PATH"] = str(PROJECT_ROOT / "classifier" / source_file)
            cmd = [
                    "taskset", "-c", "0-5",
                    "systemd-run", "--user", "--scope",
                    "-p", "MemoryMax=16G",
                    "nice", "-n", "15",
                    "ionice", "-c", "3",
                    str(Path(__file__).parent.parent / "venv" / "bin" / "python"),
                    "-u",
                    str(state.PREFETCH_SCRIPT),
                    "--mode", mode,
            ]
            if threshold is not None:
                cmd.extend(["--min-score", str(threshold)])
            state._prefetch_process = subprocess.Popen(
                cmd,
                cwd=str(state.PREFETCH_SCRIPT.parent),
                stdout=_prefetch_log,
                stderr=_prefetch_log,
                start_new_session=True,
                env=_prefetch_env,
            )
            await asyncio.sleep(1.0)
            if state._prefetch_process.poll() is not None:
                code = state._prefetch_process.returncode
                state._prefetch_process = None
                return {"running": False, "message": f"启动失败 (exit code {code})"}
            return {"running": True, "message": "已启动"}
        except Exception as e:
            return {"running": False, "message": f"启动失败: {e}"}


@router.post("/api/danbooru/prefetch/stop")
async def prefetch_stop():
    """Stop the AI pre-screening process."""
    async with state._prefetch_lock:
        killed = False
        if state._prefetch_process is not None and state._prefetch_process.poll() is None:
            try:
                os.killpg(os.getpgid(state._prefetch_process.pid), signal.SIGTERM)
                state._prefetch_process.wait(timeout=10)  # give time to save progress
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(os.getpgid(state._prefetch_process.pid), signal.SIGKILL)
                except Exception:
                    pass
            except Exception:
                pass
            state._prefetch_process = None
            killed = True
        # Also kill any externally-started prefetch
        try:
            subprocess.run(["pkill", "-f", "prefetch_candidates.py"], timeout=5)
            killed = True
        except Exception:
            pass
        return {"running": False, "stopped": killed}


# ---------------------------------------------------------------------------
# Candidates Re-score API
# ---------------------------------------------------------------------------

def _is_rescore_running() -> bool:
    if state._rescore_process is not None:
        ret = state._rescore_process.poll()
        if ret is None:
            return True
        state._rescore_process = None
    try:
        result = subprocess.run(
            ["pgrep", "-f", "prefetch_candidates.py.*--rescore"],
            capture_output=True, timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return False


@router.post("/api/danbooru/candidates/rescore")
async def candidates_rescore_start():
    """Re-score all pending candidates with the active vision model (GPU batch)."""
    async with state._rescore_lock:
        if _is_rescore_running():
            return {"status": "already_running"}
        state.RESCORE_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(state.RESCORE_LOG_PATH, "w") as log_f:
            log_f.write(f"=== Rescore started at {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
        try:
            _rescore_env = os.environ.copy()
            # Pass active model
            model_key = state._active_model
            if model_key and model_key in state._models:
                source_file = state._models[model_key].get('source_file', '')
                if source_file:
                    _rescore_env["CNN_MODEL_PATH"] = str(PROJECT_ROOT / "classifier" / source_file)
            # Pass GPU config
            gpu_cfg = _load_gpu_config()
            inf_mode = gpu_cfg.get("inference_mode", "cpu")
            _rescore_env["INFERENCE_MODE"] = inf_mode
            if inf_mode == "remote" and gpu_cfg.get("url"):
                _rescore_env["GPU_INFERENCE_URL"] = gpu_cfg["url"]
                _rescore_env["GPU_BATCH_SIZE"] = str(gpu_cfg["batch_size"])
            else:
                _rescore_env.pop("GPU_INFERENCE_URL", None)
                _rescore_env.pop("GPU_BATCH_SIZE", None)
            if inf_mode == "local_gpu":
                _rescore_env["CUDA_VISIBLE_DEVICES"] = "0"

            _rescore_env.update({
                "OMP_NUM_THREADS": "6", "MKL_NUM_THREADS": "6",
                "TORCH_NUM_THREADS": "6", "OPENBLAS_NUM_THREADS": "6",
            })

            cmd = [
                str(Path(__file__).parent.parent / "venv" / "bin" / "python"), "-u",
                str(state.PREFETCH_SCRIPT), "--rescore",
            ]
            state._rescore_process = subprocess.Popen(
                cmd,
                cwd=str(state.PREFETCH_SCRIPT.parent),
                stdout=open(state.RESCORE_LOG_PATH, "a"),
                stderr=subprocess.STDOUT,
                start_new_session=True,
                env=_rescore_env,
            )
            return {"status": "started", "model": model_key}
        except Exception as e:
            return {"status": "failed", "error": str(e)}


@router.get("/api/danbooru/candidates/rescore/status")
async def candidates_rescore_status():
    """Get re-scoring status and log."""
    running = await asyncio.to_thread(_is_rescore_running)
    log_content = ""
    if state.RESCORE_LOG_PATH.exists():
        try:
            with open(state.RESCORE_LOG_PATH, "r") as f:
                log_content = f.read()[-5000:]
        except Exception:
            pass
    return {"running": running, "log": log_content}


@router.post("/api/danbooru/candidates/rescore/stop")
async def candidates_rescore_stop():
    """Stop re-scoring."""
    async with state._rescore_lock:
        killed = False
        if state._rescore_process is not None and state._rescore_process.poll() is None:
            try:
                os.killpg(os.getpgid(state._rescore_process.pid), signal.SIGTERM)
                state._rescore_process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(os.getpgid(state._rescore_process.pid), signal.SIGKILL)
                except Exception:
                    pass
            except Exception:
                pass
            state._rescore_process = None
            killed = True
        return {"stopped": killed}


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
    return {"xgboost": xgboost_info, "cnn": cnn_info, "vision_models": vision_models, "active_model": state._active_model}


# ---------------------------------------------------------------------------
# Retrain XGBoost
# ---------------------------------------------------------------------------

def _is_retrain_running() -> bool:
    """Check if retrain script is running."""
    if state._retrain_process is not None:
        ret = state._retrain_process.poll()
        if ret is None:
            return True
        state._retrain_process = None
    try:
        result = subprocess.run(
            ["pgrep", "-f", "retrain.sh"],
            capture_output=True, timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return False


@router.post("/api/ml/retrain-xgboost")
async def ml_retrain_start():
    """Start XGBoost retraining."""
    async with state._retrain_lock:
        if _is_retrain_running():
            return {"status": "already_running"}
        state.RETRAIN_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(state.RETRAIN_LOG_PATH, "w") as log_f:
            log_f.write(f"=== Retrain started at {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
        try:
            state._retrain_process = subprocess.Popen(
                ["bash", str(state.RETRAIN_SCRIPT)],
                cwd=str(state.RETRAIN_SCRIPT.parent),
                stdout=open(state.RETRAIN_LOG_PATH, "a"),
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            return {"status": "started"}
        except Exception as e:
            return {"status": "failed", "error": str(e)}


@router.get("/api/ml/retrain-xgboost/status")
async def ml_retrain_status():
    """Get retrain status and latest log."""
    running = await asyncio.to_thread(_is_retrain_running)
    log_content = ""
    if state.RETRAIN_LOG_PATH.exists():
        try:
            with open(state.RETRAIN_LOG_PATH, "r") as f:
                log_content = f.read()[-5000:]  # Last 5KB
        except Exception:
            pass
    if not running and state._retrain_process is not None:
        exit_code = state._retrain_process.poll()
        if exit_code == 0:
            # Success - hot reload model
            await _reload_preference_model()
            return {"running": False, "finished": True, "exit_code": 0, "log": log_content}
        return {"running": False, "finished": True, "exit_code": exit_code, "log": log_content}
    return {"running": running, "finished": False, "exit_code": None, "log": log_content}


# ---------------------------------------------------------------------------
# Pack Dataset
# ---------------------------------------------------------------------------

def _is_pack_running() -> bool:
    """Check if pack script is running."""
    if state._pack_process is not None:
        ret = state._pack_process.poll()
        if ret is None:
            return True
        state._pack_process = None
    try:
        result = subprocess.run(
            ["pgrep", "-f", "pack_pipeline.sh"],
            capture_output=True, timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return False


@router.post("/api/ml/pack-dataset")
async def ml_pack_start(max_size: int = Query(1024, ge=0, le=4096)):
    """Start dataset packing. max_size=0 means original resolution."""
    async with state._pack_lock:
        if _is_pack_running():
            return {"status": "already_running"}
        state.PACK_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(state.PACK_LOG_PATH, "w") as log_f:
            label = "原始分辨率" if max_size == 0 else f"{max_size}px"
            log_f.write(f"=== Pack started at {time.strftime('%Y-%m-%d %H:%M:%S')} ({label}) ===\n")
        try:
            cmd = ["bash", str(state.PACK_SCRIPT), "--include-db", "--max-size", str(max_size)]
            state._pack_process = subprocess.Popen(
                cmd,
                cwd=str(state.PACK_SCRIPT.parent),
                stdout=open(state.PACK_LOG_PATH, "a"),
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            return {"status": "started"}
        except Exception as e:
            return {"status": "failed", "error": str(e)}


@router.get("/api/ml/pack-dataset/status")
async def ml_pack_status():
    """Get pack status and latest log."""
    running = await asyncio.to_thread(_is_pack_running)
    log_content = ""
    if state.PACK_LOG_PATH.exists():
        try:
            with open(state.PACK_LOG_PATH, "r") as f:
                log_content = f.read()[-5000:]  # Last 5KB
        except Exception:
            pass
    if not running and state._pack_process is not None:
        exit_code = state._pack_process.poll()
        return {"running": False, "finished": True, "exit_code": exit_code, "log": log_content}
    return {"running": running, "finished": False, "exit_code": None, "log": log_content}


# ---------------------------------------------------------------------------
# Vision Score
# ---------------------------------------------------------------------------

def _is_vscore_running() -> bool:
    if state._vscore_process is not None:
        ret = state._vscore_process.poll()
        if ret is None:
            return True
        state._vscore_process = None
    try:
        result = subprocess.run(
            ["pgrep", "-f", "score_crawler.py"],
            capture_output=True, timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return False


class VscoreStartRequest(BaseModel):
    model: str | None = None  # model key from state._models, or "all"

@router.post("/api/ml/vision-score")
async def ml_vscore_start(req: VscoreStartRequest = VscoreStartRequest()):
    """Start vision scoring of crawler images."""
    async with state._vscore_lock:
        if _is_vscore_running():
            return {"status": "already_running"}
        state.VSCORE_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(state.VSCORE_LOG_PATH, "w") as log_f:
            log_f.write(f"=== Vision scoring started at {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
        try:
            import sys as _sys
            cmd = [_sys.executable, str(state.VSCORE_SCRIPT)]

            # Determine which model to run
            model_key = req.model or state._active_model
            if model_key and model_key in state._models:
                info = state._models[model_key]
                model_type = "siglip2" if info.get('type') == 'siglip2' else "eva02"
                source_file = info.get('source_file', '')
                if source_file:
                    model_path = state.VSCORE_SCRIPT.parent.parent / "classifier" / source_file
                    cmd.extend(["--model", model_type, "--model-path", str(model_path)])
                else:
                    cmd.extend(["--model", model_type])
            # else: default --model all

            state._vscore_process = subprocess.Popen(
                cmd,
                cwd=str(state.VSCORE_SCRIPT.parent),
                stdout=open(state.VSCORE_LOG_PATH, "a"),
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            return {"status": "started", "model": model_key}
        except Exception as e:
            return {"status": "failed", "error": str(e)}


@router.get("/api/ml/vision-score/status")
async def ml_vscore_status():
    """Get vision scoring status and latest log."""
    running = await asyncio.to_thread(_is_vscore_running)
    log_content = ""
    if state.VSCORE_LOG_PATH.exists():
        try:
            with open(state.VSCORE_LOG_PATH, "r") as f:
                log_content = f.read()[-5000:]
        except Exception:
            pass
    if not running and state._vscore_process is not None:
        exit_code = state._vscore_process.poll()
        return {"running": False, "finished": True, "exit_code": exit_code, "log": log_content}
    return {"running": running, "finished": False, "exit_code": None, "log": log_content}


# ---------------------------------------------------------------------------
# Tag Liked Train
# ---------------------------------------------------------------------------

def _is_tag_train_running() -> bool:
    if state._tag_train_process is not None:
        ret = state._tag_train_process.poll()
        if ret is None:
            return True
        state._tag_train_process = None
    try:
        result = subprocess.run(
            ["pgrep", "-f", "tag_liked_t2i.py"],
            capture_output=True, timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return False


@router.post("/api/ml/tag-train")
async def ml_tag_train_start():
    """Start incremental sync + WD14 tagging for liked training set (GPU)."""
    async with state._tag_train_lock:
        if _is_tag_train_running():
            return {"status": "already_running"}
        state.TAG_TRAIN_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(state.TAG_TRAIN_LOG_PATH, "w") as log_f:
            log_f.write(f"=== Tag train started at {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
        try:
            venv_python = PROJECT_ROOT / "backend" / "venv" / "bin" / "python"
            state._tag_train_process = subprocess.Popen(
                [str(venv_python), str(state.TAG_TRAIN_SCRIPT)],
                cwd=str(state.TAG_TRAIN_SCRIPT.parent),
                stdout=open(state.TAG_TRAIN_LOG_PATH, "a"),
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            return {"status": "started"}
        except Exception as e:
            return {"status": "failed", "error": str(e)}


@router.get("/api/ml/tag-train/status")
async def ml_tag_train_status():
    """Get tag-train status and latest log."""
    running = await asyncio.to_thread(_is_tag_train_running)
    log_content = ""
    if state.TAG_TRAIN_LOG_PATH.exists():
        try:
            with open(state.TAG_TRAIN_LOG_PATH, "r") as f:
                log_content = f.read()[-5000:]
        except Exception:
            pass
    if not running and state._tag_train_process is not None:
        exit_code = state._tag_train_process.poll()
        return {"running": False, "finished": True, "exit_code": exit_code, "log": log_content}
    return {"running": running, "finished": False, "exit_code": None, "log": log_content}
