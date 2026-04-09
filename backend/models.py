"""ML model loading, unloading, inference device management, and scoring functions."""

import json
from pathlib import Path

import numpy as np

import state

# ---------------------------------------------------------------------------
# Model loading / unloading
# ---------------------------------------------------------------------------

def _unload_model(key: str):
    """Unload model weights from memory."""
    if key in state._models and state._models[key].get('model') is not None:
        print(f"[models] Unloading {key}")
        state._models[key]['model'] = None
        state._models[key]['transform'] = None
        state._models[key]['processor'] = None
        if state._cnn_model and state._cnn_model.get('source_file') == state._models[key].get('source_file'):
            state._cnn_model = None
    if state._loaded_model_key == key:
        state._loaded_model_key = None
    import gc
    gc.collect()


def _load_model_weights(key: str):
    """Load model weights for a given key. Unloads any previously loaded model first."""
    if key not in state._models:
        raise ValueError(f"Unknown model key: {key}")
    info = state._models[key]
    if info.get('model') is not None:
        state._loaded_model_key = key
        return  # already loaded

    # Unload previous model to save memory
    if state._loaded_model_key and state._loaded_model_key != key:
        _unload_model(state._loaded_model_key)

    import torch
    import torch.nn as tnn

    pt_path = info['_pt_path']
    _init_device = "cpu"
    checkpoint = torch.load(pt_path, map_location=_init_device, weights_only=False)
    model_class = info['model_class']
    model_name = info['model_name']

    if model_class == 'NaFlexClassifier':
        from transformers import AutoModel, AutoProcessor

        class NaFlexClassifier(tnn.Module):
            def __init__(self, hf_model, num_features, dropout=0.2):
                super().__init__()
                self.vision_model = hf_model.vision_model
                self.num_features = num_features
                hidden = 512
                self.head = tnn.Sequential(
                    tnn.LayerNorm(num_features),
                    tnn.Dropout(dropout),
                    tnn.Linear(num_features, hidden),
                    tnn.GELU(),
                    tnn.LayerNorm(hidden),
                    tnn.Dropout(dropout * 0.5),
                    tnn.Linear(hidden, 1),
                )

            def forward(self, pixel_values, pixel_attention_mask=None, spatial_shapes=None):
                kwargs = {"pixel_values": pixel_values}
                if pixel_attention_mask is not None:
                    kwargs["attention_mask"] = pixel_attention_mask
                if spatial_shapes is not None:
                    kwargs["spatial_shapes"] = spatial_shapes
                outputs = self.vision_model(**kwargs)
                feats = outputs.pooler_output
                if feats is None:
                    feats = outputs.last_hidden_state.mean(dim=1)
                return self.head(feats)

        num_features = info.get('num_features', 1152)
        dropout = checkpoint.get('dropout', 0.2)
        hf_model = AutoModel.from_pretrained(model_name, dtype=torch.float32, local_files_only=True)
        processor = AutoProcessor.from_pretrained(model_name, local_files_only=True)
        siglip_clf = NaFlexClassifier(hf_model, num_features, dropout)
        siglip_clf.load_state_dict(checkpoint['model_state_dict'])
        siglip_clf.to(_init_device)
        siglip_clf.eval()
        info['model'] = siglip_clf
        info['processor'] = processor

    elif model_class in ('PreferenceModel', 'timm'):
        import timm
        from torchvision import transforms as T

        input_size = info.get('input_size', 224)
        mean = checkpoint.get('normalize_mean', [0.485, 0.456, 0.406])
        std = checkpoint.get('normalize_std', [0.229, 0.224, 0.225])

        if model_class == 'PreferenceModel':
            class PreferenceModel(tnn.Module):
                def __init__(self, backbone, num_features, dropout=0.2):
                    super().__init__()
                    self.backbone = backbone
                    self.head = tnn.Sequential(
                        tnn.LayerNorm(num_features),
                        tnn.Dropout(p=dropout),
                        tnn.Linear(num_features, 256),
                        tnn.GELU(),
                        tnn.Dropout(p=dropout * 0.5),
                        tnn.Linear(256, 1),
                    )
                def forward(self, x):
                    feats = self.backbone(x)
                    if feats.ndim == 4:
                        feats = feats.mean(dim=(2, 3))
                    elif feats.ndim == 3:
                        feats = feats.mean(dim=1)
                    return self.head(feats)

            num_features = checkpoint.get('num_features', 1024)
            dropout = checkpoint.get('dropout', 0.2)
            backbone = timm.create_model(model_name, pretrained=False, num_classes=0)
            cnn = PreferenceModel(backbone, num_features, dropout)
            cnn.load_state_dict(checkpoint['model_state_dict'])
        else:
            cnn = timm.create_model(model_name, pretrained=False, num_classes=checkpoint.get('num_classes', 1))
            cnn.load_state_dict(checkpoint['model_state_dict'])

        cnn.to(_init_device)
        cnn.eval()
        transform = T.Compose([
            T.Resize(int(input_size * 1.14), interpolation=T.InterpolationMode.BICUBIC),
            T.CenterCrop(input_size),
            T.ToTensor(),
            T.Normalize(mean=mean, std=std),
        ])
        info['model'] = cnn
        info['transform'] = transform
        state._cnn_model = info
    else:
        raise ValueError(f"Unknown model_class: {model_class}")

    state._loaded_model_key = key
    print(f"[models] Loaded weights for {key} ({model_name}), device=cpu")


def _ensure_model_loaded(key: str | None = None):
    """Ensure the specified (or active) model has weights loaded. Lazy-loads on first use."""
    key = key or state._active_model
    if not key or key not in state._models:
        return False
    if state._models[key].get('model') is None:
        _load_model_weights(key)
    return True


# ---------------------------------------------------------------------------
# Inference device management
# ---------------------------------------------------------------------------

def _get_torch_device() -> str:
    """Return the current torch device string."""
    return state._inference_device


def _migrate_cnn_to_device(device: str):
    """Move all loaded models to a different device (cpu/cuda)."""
    state._inference_device = device
    if not state._models:
        return
    try:
        import torch
        target = torch.device(device)
        for key, info in state._models.items():
            if info.get('model') is None:
                continue
            info['model'] = info['model'].to(target)
            info['model'].eval()
        print(f"[inference] All models ({list(state._models.keys())}) migrated to {device}")
    except Exception as e:
        print(f"[inference] Failed to migrate models to {device}: {e}")


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
        mem_total = getattr(props, 'total_memory', getattr(props, 'total_mem', 0)) / 1024 / 1024
        return {
            "device_name": props.name,
            "total_memory_mb": round(mem_total),
            "allocated_mb": round(mem_alloc),
            "device_count": torch.cuda.device_count(),
        }
    except Exception as e:
        print(f"[inference] _cuda_info error: {e}")
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
    if info.get('model') is None:
        return None
    try:
        import torch
        from PIL import Image as PILImage
        device = torch.device(_get_torch_device())
        img = PILImage.open(image_path).convert('RGB')

        if info['type'] == 'siglip2' and info.get('processor'):
            inputs = info['processor'](images=img, return_tensors="pt")
            inputs = {k: v.to(device) for k, v in inputs.items()}
            with torch.no_grad():
                logit = info['model'](**inputs).squeeze()
                prob = torch.sigmoid(logit).item()
        else:
            tensor = info['transform'](img).unsqueeze(0).to(device)
            with torch.no_grad():
                logit = info['model'](tensor).squeeze()
                prob = torch.sigmoid(logit).item()
        return prob
    except Exception:
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
    tag_vocab = model_data['tag_vocab']
    feature_names = model_data['feature_names']
    n_features = len(feature_names)

    x = np.zeros(n_features, dtype=np.float32)
    raw_tags = [t.strip().strip(',') for t in tags_str.split()] if tags_str else []
    image_tags = set()
    for t in raw_tags:
        image_tags.add(t)
        image_tags.add(t.replace('_', ' '))

    tag_to_idx = {t: i for i, t in enumerate(tag_vocab)}
    matched = 0
    for tag in image_tags:
        if tag in tag_to_idx:
            x[tag_to_idx[tag]] = 1.0
            matched += 1

    n_tags = len(tag_vocab)
    rating_map = {'general': 0, 'sensitive': 1, 'questionable': 2, 'explicit': 3}
    rating_full = {'g': 'general', 's': 'sensitive', 'q': 'questionable', 'e': 'explicit'}
    rating_name = rating_full.get(rating, '')
    if rating_name in rating_map:
        x[n_tags + rating_map[rating_name]] = 1.0

    x[n_tags + 4] = len(raw_tags)
    x[n_tags + 5] = 1.0
    return x


async def _reload_preference_model():
    """Hot-reload XGBoost model after retrain."""
    from config import PREFERENCE_MODEL_PATH
    if PREFERENCE_MODEL_PATH.exists():
        try:
            import joblib
            new_model = joblib.load(PREFERENCE_MODEL_PATH)
            state._preference_model = new_model
            print(f"[ml] XGBoost hot-reloaded: AUC={new_model.get('auc', 0):.4f}")
        except Exception as e:
            print(f"[ml] Failed to hot-reload XGBoost: {e}")
