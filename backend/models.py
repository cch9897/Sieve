"""ML model loading, unloading, inference device management, and scoring functions."""

import json
import logging
import sys
import threading
from pathlib import Path

import numpy as np

import state

logger = logging.getLogger(__name__)

_classifier_dir = str(Path(__file__).parent.parent / "classifier")
if _classifier_dir not in sys.path:
    sys.path.insert(0, _classifier_dir)

_model_lock = threading.Lock()

# ---------------------------------------------------------------------------
# Model loading / unloading
# ---------------------------------------------------------------------------


def _unload_model(key: str):
    """Unload model weights from memory."""
    if key in state._models and state._models[key].get("model") is not None:
        logger.info("[models] Unloading %s", key)
        state._models[key]["model"] = None
        state._models[key]["transform"] = None
        state._models[key]["processor"] = None
        if state._cnn_model and state._cnn_model.get("source_file") == state._models[key].get("source_file"):
            state._cnn_model = None
    if state._loaded_model_key == key:
        state._loaded_model_key = None
    import gc

    gc.collect()


def _load_model_weights(key: str):
    """Load model weights for a given key. Unloads any previously loaded model first."""
    with _model_lock:
        _load_model_weights_locked(key)


def _load_model_weights_locked(key: str):
    if key not in state._models:
        raise ValueError(f"Unknown model key: {key}")
    info = state._models[key]
    if info.get("model") is not None:
        state._loaded_model_key = key
        return

    # Unload previous model to save memory
    if state._loaded_model_key and state._loaded_model_key != key:
        _unload_model(state._loaded_model_key)

    import torch

    pt_path = info["_pt_path"]
    _init_device = "cpu"
    # weights_only=True is safe here: checkpoints contain only state_dicts and
    # basic metadata (model objects are rebuilt from scratch via from_pretrained
    # / timm.create_model then load_state_dict). The scan phase
    # (_scan_pt_models) already validated weights_only compatibility, so any
    # model reaching this point is known to load safely.
    checkpoint = torch.load(pt_path, map_location=_init_device, weights_only=True)
    model_class = info["model_class"]
    model_name = info["model_name"]

    if model_class == "NaFlexClassifier":
        from model_defs import NaFlexClassifier
        from transformers import AutoModel, AutoProcessor

        num_features = info.get("num_features", 1152)
        dropout = checkpoint.get("dropout", 0.2)
        hf_model = AutoModel.from_pretrained(model_name, dtype=torch.float32, local_files_only=True)
        processor = AutoProcessor.from_pretrained(model_name, local_files_only=True)
        siglip_clf = NaFlexClassifier(hf_model, num_features, dropout)
        siglip_clf.load_state_dict(checkpoint["model_state_dict"])
        siglip_clf.to(_init_device)
        siglip_clf.eval()
        info["model"] = siglip_clf
        info["processor"] = processor

    elif model_class in ("PreferenceModel", "timm"):
        import timm

        input_size = info.get("input_size", 224)
        mean = checkpoint.get("normalize_mean", [0.485, 0.456, 0.406])
        std = checkpoint.get("normalize_std", [0.229, 0.224, 0.225])

        if model_class == "PreferenceModel":
            from model_defs import PreferenceModel

            num_features = checkpoint.get("num_features", 1024)
            dropout = checkpoint.get("dropout", 0.2)
            backbone = timm.create_model(model_name, pretrained=False, num_classes=0)
            cnn = PreferenceModel(backbone, num_features, dropout)
            cnn.load_state_dict(checkpoint["model_state_dict"])
        else:
            cnn = timm.create_model(model_name, pretrained=False, num_classes=checkpoint.get("num_classes", 1))
            cnn.load_state_dict(checkpoint["model_state_dict"])

        cnn.to(_init_device)
        cnn.eval()
        from model_defs import build_timm_transform

        transform = build_timm_transform(input_size, mean, std)
        info["model"] = cnn
        info["transform"] = transform
        state._cnn_model = info
    else:
        raise ValueError(f"Unknown model_class: {model_class}")

    state._loaded_model_key = key
    logger.info("[models] Loaded weights for %s (%s), device=cpu", key, model_name)


def _ensure_model_loaded(key: str | None = None):
    """Ensure the specified (or active) model has weights loaded. Lazy-loads on first use."""
    key = key or state._active_model
    if not key or key not in state._models:
        return False
    if state._models[key].get("model") is None:
        with _model_lock:
            _load_model_weights_locked(key)
    return True


# ---------------------------------------------------------------------------
# Inference device management
# ---------------------------------------------------------------------------


def _get_torch_device() -> str:
    """Return the current torch device string."""
    return state._inference_device


def _migrate_cnn_to_device(device: str):
    """Move all loaded models to a different device (cpu/cuda).

    Migrates first, then commits ``state._inference_device`` only on success.
    On failure the device is rolled back so inference doesn't target a device
    the models were never moved to.
    """
    with _model_lock:
        if not state._models:
            state._inference_device = device
            return
        old_device = state._inference_device
        try:
            import torch

            target = torch.device(device)
            for key, info in state._models.items():
                if info.get("model") is None:
                    continue
                info["model"] = info["model"].to(target)
                info["model"].eval()
            state._inference_device = device
            logger.info("[inference] All models (%s) migrated to %s", list(state._models.keys()), device)
        except Exception as e:
            logger.error("[inference] Failed to migrate models to %s: %s (staying on %s)", device, e, old_device)


def _check_cuda_available() -> bool:
    """Check CUDA availability (cached after first call)."""
    if state._cuda_available_cached is None:
        try:
            import torch

            state._cuda_available_cached = torch.cuda.is_available()
        except Exception:
            state._cuda_available_cached = False
    return state._cuda_available_cached


def _cuda_info() -> dict | None:
    """Return CUDA device info or None if unavailable."""
    if not _check_cuda_available():
        return None
    try:
        import torch

        idx = 0
        if not torch.cuda.is_initialized():
            torch.cuda.init()
        props = torch.cuda.get_device_properties(idx)
        mem_alloc = torch.cuda.memory_allocated(idx) / 1024 / 1024
        mem_total = getattr(props, "total_memory", getattr(props, "total_mem", 0)) / 1024 / 1024
        return {
            "device_name": props.name,
            "total_memory_mb": round(mem_total),
            "allocated_mb": round(mem_alloc),
            "device_count": torch.cuda.device_count(),
        }
    except Exception as e:
        logger.warning("[inference] _cuda_info error: %s", e)
        return None


# ---------------------------------------------------------------------------
# GPU config (persisted to disk)
# ---------------------------------------------------------------------------


def _load_gpu_config() -> dict:
    """Load GPU inference config from disk."""
    defaults = {"url": "", "batch_size": 16, "enabled": False, "inference_mode": "cpu"}
    if state.GPU_CONFIG_PATH.exists():
        try:
            with open(state.GPU_CONFIG_PATH) as f:
                data = json.load(f)
            merged = {**defaults, **data}
            if merged["inference_mode"] == "cpu" and merged.get("enabled") and merged.get("url"):
                merged["inference_mode"] = "remote"
            return merged
        except Exception:
            pass
    return defaults


def _save_gpu_config(cfg: dict):
    """Persist GPU inference config."""
    with open(state.GPU_CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)


# ---------------------------------------------------------------------------
# Image scoring functions
# ---------------------------------------------------------------------------


def _score_image_with_model(image_path: str | Path, model_key: str | None = None) -> float | None:
    """Score a single image using the specified model (or active model). Returns probability."""
    key = model_key or state._active_model
    if not key or key not in state._models:
        return None
    _ensure_model_loaded(key)
    info = state._models[key]
    if info.get("model") is None:
        return None
    try:
        import torch
        from PIL import Image as PILImage

        device = torch.device(_get_torch_device())
        img = PILImage.open(image_path).convert("RGB")

        if info["type"] == "siglip2" and info.get("processor"):
            inputs = info["processor"](images=img, return_tensors="pt")
            inputs = {k: v.to(device) for k, v in inputs.items()}
            with torch.no_grad():
                logit = info["model"](**inputs).squeeze()
                prob = torch.sigmoid(logit).item()
        else:
            tensor = info["transform"](img).unsqueeze(0).to(device)
            with torch.no_grad():
                logit = info["model"](tensor).squeeze()
                prob = torch.sigmoid(logit).item()
        return prob
    except Exception as e:
        logger.warning("[models] Failed to score %s: %s", image_path, e)
        return None


def _cnn_score_image(image_path: str | Path) -> float | None:
    """Score using active model. Backward compat wrapper."""
    return _score_image_with_model(image_path)


def _fused_score(tag_score: float, cnn_score: float | None, tag_weight: float = 0.5) -> float:
    """Fuse XGBoost tag score and CNN image score."""
    if cnn_score is None:
        return tag_score
    return tag_weight * tag_score + (1 - tag_weight) * cnn_score


def _build_preference_features(tags_str: str, rating: str, model_data: dict) -> np.ndarray:
    """Build feature vector for a Danbooru image (matches train_classifier.py logic)."""
    from feature_utils import build_tag_features

    return build_tag_features(tags_str, rating, model_data)


async def _reload_preference_model():
    """Hot-reload XGBoost model after retrain."""
    import asyncio

    from config import PREFERENCE_MODEL_PATH

    if PREFERENCE_MODEL_PATH.exists():
        try:
            import joblib

            new_model = await asyncio.to_thread(joblib.load, PREFERENCE_MODEL_PATH)
            state._preference_model = new_model
            logger.info("[ml] XGBoost hot-reloaded: AUC=%.4f", new_model.get("auc", 0))
        except Exception as e:
            logger.error("[ml] Failed to hot-reload XGBoost: %s", e)
