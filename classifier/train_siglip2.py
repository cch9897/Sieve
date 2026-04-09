#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SigLIP2 Preference Classifier Training Script
Fine-tunes SigLIP2 on image preference data.

Supports two backbone families:
  1. timm: vit_large_patch16_siglip_{256,384,512}.v2_webli (fixed resolution)
     - 303M params, 1024-dim features, 24 transformer blocks
  2. NaFlex: google/siglip2-so400m-patch16-naflex (HuggingFace transformers)
     - 400M params, 1152-dim features, 27 transformer blocks
     - Variable resolution with native aspect ratio preservation
     - Processor handles dynamic patching (max_num_patches configurable)

Usage:
    # Single GPU - timm backbone (384)
    python train_siglip2.py

    # Single GPU - NaFlex backbone (variable resolution)
    python train_siglip2.py --naflex

    # NaFlex with custom max patches (higher = more detail, more VRAM)
    python train_siglip2.py --naflex --max-patches 512

    # Single GPU (512, more VRAM)
    python train_siglip2.py --size 512

    # Multi-GPU (3 cards)
    torchrun --nproc_per_node=3 train_siglip2.py --naflex

    # Progressive: pretrain 384, finetune 512
    python train_siglip2.py --size 384 --output model_siglip2_384.pt
    python train_siglip2.py --size 512 --init-from model_siglip2_384.pt --lr-head 5e-5 --lr-backbone 2e-6 --epochs 10

    # True resume (interrupted training)
    python train_siglip2.py --resume checkpoint_latest.pt

    # Full options
    torchrun --nproc_per_node=3 train_siglip2.py \\
        --naflex --unfreeze 2 --batch-size 32 --epochs 20 \\
        --lr-head 2e-4 --lr-backbone 1e-5 --mix-prob 0.3 \\
        --output model_siglip2_naflex.pt
"""

import argparse
import glob
import math
import os
import re
import random
import signal
import time
from pathlib import Path

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.distributed as dist
from torch.nn.parallel import DistributedDataParallel as DDP
from torch.utils.data import Dataset, DataLoader
from torch.utils.data.distributed import DistributedSampler
from torchvision import transforms
import warnings
from PIL import Image, ImageFile
warnings.filterwarnings("ignore", category=UserWarning, module="PIL")
warnings.filterwarnings("ignore", category=Image.DecompressionBombWarning)
Image.MAX_IMAGE_PIXELS = None  # disable decompression bomb check
from sklearn.model_selection import StratifiedKFold
from sklearn.metrics import classification_report, roc_auc_score

import timm

ImageFile.LOAD_TRUNCATED_IMAGES = True

# Optional: transformers for NaFlex
try:
    import transformers as _tf
    from transformers import AutoModel, AutoProcessor
    HAS_TRANSFORMERS = True
except ImportError:
    HAS_TRANSFORMERS = False

# ---------------------------------------------------------------------------
# SigLIP2 model registry
# ---------------------------------------------------------------------------
SIGLIP2_MODELS = {
    384: "vit_large_patch16_siglip_384.v2_webli",
    512: "vit_large_patch16_siglip_512.v2_webli",
    256: "vit_large_patch16_siglip_256.v2_webli",
}
NAFLEX_CHECKPOINT = "google/siglip2-so400m-patch16-naflex"
SIGLIP2_MEAN = (0.5, 0.5, 0.5)
SIGLIP2_STD = (0.5, 0.5, 0.5)


# ---------------------------------------------------------------------------
# Reproducibility
# ---------------------------------------------------------------------------
def _worker_init_fn(worker_id):
    """Per-worker seed for DataLoader reproducibility."""
    seed = torch.initial_seed() % 2**32
    np.random.seed(seed)
    random.seed(seed)


def set_seed(seed=42, rank=0, deterministic=False):
    s = seed + rank
    random.seed(s)
    np.random.seed(s)
    torch.manual_seed(s)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(s)
    if deterministic:
        torch.backends.cudnn.deterministic = True
        torch.backends.cudnn.benchmark = False
    else:
        torch.backends.cudnn.benchmark = True


# ---------------------------------------------------------------------------
# DDP helpers
# ---------------------------------------------------------------------------
def setup_ddp():
    if "RANK" in os.environ:
        backend = "nccl" if torch.cuda.is_available() else "gloo"
        dist.init_process_group(backend=backend)
        rank = dist.get_rank()
        local_rank = int(os.environ["LOCAL_RANK"])
        world_size = dist.get_world_size()
        if torch.cuda.is_available():
            torch.cuda.set_device(local_rank)
        return rank, local_rank, world_size
    return 0, 0, 1


def cleanup_ddp():
    if dist.is_initialized():
        dist.destroy_process_group()


def is_main():
    return not dist.is_initialized() or dist.get_rank() == 0


def log(msg, force=False):
    if force or is_main():
        print(msg, flush=True)


# ---------------------------------------------------------------------------
# Checkpoint
# ---------------------------------------------------------------------------
def save_checkpoint(state_dict, path, meta=None):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    save_dict = {"model_state_dict": state_dict, **(meta or {})}
    tmp = str(path) + ".tmp"
    try:
        torch.save(save_dict, tmp)
        os.replace(tmp, path)
        return True
    except Exception as e:
        print(f"  Warning: checkpoint save failed: {e}")
        if os.path.exists(tmp):
            os.remove(tmp)
        return False


def save_full_checkpoint(path, model, optimizer, scheduler_epoch, scaler, ema, epoch, meta=None):
    """Save everything needed for true resume."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    save_dict = {
        "model_state_dict": {k: v.detach().cpu().clone() for k, v in model.state_dict().items()},
        "optimizer_state_dict": optimizer.state_dict(),
        "scheduler_epoch": scheduler_epoch,
        "scaler_state_dict": scaler.state_dict() if scaler is not None else None,
        "ema_shadow": {k: v.cpu().clone() for k, v in ema.shadow.items()} if ema is not None else None,
        "epoch": epoch,
        **(meta or {}),
    }
    tmp = str(path) + ".tmp"
    try:
        torch.save(save_dict, tmp)
        os.replace(tmp, path)
        return True
    except Exception as e:
        print(f"  Warning: full checkpoint save failed: {e}")
        if os.path.exists(tmp):
            os.remove(tmp)
        return False


def _epoch_num_from_path(path):
    """Extract epoch number from checkpoint filename for correct numeric sorting."""
    m = re.search(r"_epoch(\d+)\.pt$", str(path))
    return int(m.group(1)) if m else -1


class _InterruptHandler:
    def __init__(self):
        self.last_ckpt = None
        self.pid = None

    def handle(self, signum, frame):
        if os.getpid() != self.pid:
            os._exit(1)
        print(f"\n\nInterrupted!")
        if self.last_ckpt and os.path.exists(self.last_ckpt):
            sz = os.path.getsize(self.last_ckpt) / 1024**2
            print(f"Latest checkpoint: {self.last_ckpt} ({sz:.1f} MB)")
        os._exit(1)


_handler = _InterruptHandler()


# ---------------------------------------------------------------------------
# Augmentation: Mixup / CutMix
# ---------------------------------------------------------------------------
def mixup_data(x, y, alpha=0.2):
    if alpha <= 0:
        return x, y, y, 1.0
    lam = max(l := np.random.beta(alpha, alpha), 1 - l)
    idx = torch.randperm(x.size(0), device=x.device)
    return lam * x + (1 - lam) * x[idx], y, y[idx], lam


def cutmix_data(x, y, alpha=1.0):
    if alpha <= 0:
        return x, y, y, 1.0
    lam = np.random.beta(alpha, alpha)
    idx = torch.randperm(x.size(0), device=x.device)
    _, _, h, w = x.shape
    r = np.sqrt(1.0 - lam)
    cw, ch = int(w * r), int(h * r)
    cx, cy = np.random.randint(w), np.random.randint(h)
    x1, y1 = np.clip(cx - cw // 2, 0, w), np.clip(cy - ch // 2, 0, h)
    x2, y2 = np.clip(cx + cw // 2, 0, w), np.clip(cy + ch // 2, 0, h)
    out = x.clone()
    out[:, :, y1:y2, x1:x2] = x[idx, :, y1:y2, x1:x2]
    lam = 1 - ((x2 - x1) * (y2 - y1) / (w * h))
    return out, y, y[idx], lam


def mix_criterion(criterion, pred, ya, yb, lam):
    return lam * criterion(pred, ya) + (1 - lam) * criterion(pred, yb)


# ---------------------------------------------------------------------------
# EMA
# ---------------------------------------------------------------------------
class EMA:
    def __init__(self, model, decay=0.998):
        self.decay = decay
        self.shadow = {n: p.data.clone() for n, p in model.named_parameters() if p.requires_grad}
        self.backup = {}

    def update(self, model):
        for n, p in model.named_parameters():
            if p.requires_grad and n in self.shadow:
                self.shadow[n].mul_(self.decay).add_(p.data, alpha=1 - self.decay)

    def apply(self, model):
        for n, p in model.named_parameters():
            if p.requires_grad and n in self.shadow:
                self.backup[n] = p.data.clone()
                p.data.copy_(self.shadow[n])

    def restore(self, model):
        for n, p in model.named_parameters():
            if n in self.backup:
                p.data.copy_(self.backup[n])
        self.backup = {}

    def load_shadow(self, shadow_dict, device=None):
        """Restore EMA shadow from saved checkpoint."""
        for k, v in shadow_dict.items():
            if k in self.shadow:
                self.shadow[k] = v.to(device) if device else v


# ---------------------------------------------------------------------------
# Label Smoothing BCE
# ---------------------------------------------------------------------------
class SmoothBCEWithLogits(nn.Module):
    def __init__(self, smoothing=0.05, pos_weight=None):
        super().__init__()
        self.s = smoothing
        self.pos_weight = pos_weight

    def forward(self, logits, targets):
        t = targets * (1 - self.s) + 0.5 * self.s
        return F.binary_cross_entropy_with_logits(logits, t, pos_weight=self.pos_weight)


# ---------------------------------------------------------------------------
# Dataset
# ---------------------------------------------------------------------------
class PrefDataset(Dataset):
    _global_bad_count = 0
    _global_bad_limit = 50

    def __init__(self, df, img_dir, transform=None, fallback_size=384):
        self.filenames = df["filename"].tolist()
        self.labels = df["label"].tolist()
        self.img_dir = Path(img_dir)
        self.transform = transform
        self.fallback_size = fallback_size

    def __len__(self):
        return len(self.filenames)

    def __getitem__(self, idx):
        fname = self.filenames[idx]
        label = self.labels[idx]
        path = self.img_dir / fname
        try:
            with Image.open(path) as im:
                img = im.convert("RGB")
        except Exception as e:
            if PrefDataset._global_bad_count < PrefDataset._global_bad_limit:
                print(f"  [Dataset] Failed to load {path}: {e}", flush=True)
                PrefDataset._global_bad_count += 1
                if PrefDataset._global_bad_count == PrefDataset._global_bad_limit:
                    print(f"  [Dataset] Suppressing further warnings...", flush=True)
            img = Image.new("RGB", (self.fallback_size, self.fallback_size), color="grey")
        if self.transform:
            img = self.transform(img)
        return img, torch.tensor(label, dtype=torch.float32)


# ---------------------------------------------------------------------------
# NaFlex preprocessing cache
# ---------------------------------------------------------------------------
def preprocess_naflex_cache(df, img_dir, processor, cache_dir, max_patches=None):
    """Pre-process all images with NaFlex processor and cache to disk.

    Only processes images that are not yet cached (incremental).
    Returns the cache_dir path.
    """
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    filenames = df["filename"].tolist()
    img_dir = Path(img_dir)

    # Check which files need processing
    to_process = []
    for fname in filenames:
        cache_path = cache_dir / (fname + ".pt")
        if not cache_path.exists():
            to_process.append(fname)

    if not to_process:
        log(f"  NaFlex cache: all {len(filenames)} files already cached")
        return cache_dir

    log(f"  NaFlex cache: {len(to_process)} files to process ({len(filenames) - len(to_process)} cached)")

    bad_count = 0
    for i, fname in enumerate(to_process):
        if i % 500 == 0 and i > 0:
            log(f"    Processed {i}/{len(to_process)}...")
        path = img_dir / fname
        try:
            with Image.open(path) as im:
                img = im.convert("RGB")
        except Exception as e:
            if bad_count < 50:
                print(f"  [Cache] Failed to load {path}: {e}", flush=True)
                bad_count += 1
            img = Image.new("RGB", (256, 256), color="grey")

        inputs = processor(images=img, return_tensors="pt", padding="max_length")
        data = {"pixel_values": inputs["pixel_values"].squeeze(0)}
        if "pixel_attention_mask" in inputs:
            data["pixel_attention_mask"] = inputs["pixel_attention_mask"].squeeze(0)
        if "spatial_shapes" in inputs:
            data["spatial_shapes"] = inputs["spatial_shapes"].squeeze(0)

        cache_path = cache_dir / (fname + ".pt")
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        torch.save(data, cache_path)

    log(f"  NaFlex cache: done ({len(to_process)} files processed)")
    return cache_dir


# ---------------------------------------------------------------------------
# NaFlex Dataset (variable resolution via HuggingFace processor)
# ---------------------------------------------------------------------------
class NaFlexPrefDataset(Dataset):
    """Dataset that loads pre-cached NaFlex tensors from disk.

    If cache_dir is provided, loads from cache (fast, low memory).
    Otherwise falls back to on-the-fly processor (slow, high memory).
    """
    _global_bad_count = 0
    _global_bad_limit = 50

    def __init__(self, df, img_dir, processor, augment=False, cache_dir=None):
        self.filenames = df["filename"].tolist()
        self.labels = df["label"].tolist()
        self.img_dir = Path(img_dir)
        self.processor = processor
        self.augment = augment
        self.cache_dir = Path(cache_dir) if cache_dir is not None else None
        # Simple augmentations that don't change image size (NaFlex handles sizing)
        self.aug_transforms = transforms.Compose([
            transforms.RandomHorizontalFlip(0.5),
            transforms.RandomApply([
                transforms.ColorJitter(brightness=0.15, contrast=0.15, saturation=0.1, hue=0.02),
            ], p=0.3),
            transforms.RandomApply([
                transforms.GaussianBlur(kernel_size=5, sigma=(0.1, 1.0)),
            ], p=0.1),
        ]) if augment else None

    def __len__(self):
        return len(self.filenames)

    def __getitem__(self, idx):
        fname = self.filenames[idx]
        label = self.labels[idx]

        # Fast path: load from cache
        if self.cache_dir is not None:
            cache_path = self.cache_dir / (fname + ".pt")
            if cache_path.exists():
                data = torch.load(cache_path, weights_only=True)
                # Apply tensor-level augmentation (random horizontal flip)
                if self.augment and random.random() < 0.5:
                    pv = data["pixel_values"]
                    if pv.ndim == 3:  # (C, H, W)
                        data["pixel_values"] = pv.flip(-1)
                    elif pv.ndim == 2:  # (N, patch_dim) flattened patches — skip flip
                        pass
                data["label"] = torch.tensor(label, dtype=torch.float32)
                return data

        # Slow path: on-the-fly processing
        path = self.img_dir / fname
        try:
            with Image.open(path) as im:
                img = im.convert("RGB")
        except Exception as e:
            if NaFlexPrefDataset._global_bad_count < NaFlexPrefDataset._global_bad_limit:
                print(f"  [Dataset] Failed to load {path}: {e}", flush=True)
                NaFlexPrefDataset._global_bad_count += 1
                if NaFlexPrefDataset._global_bad_count == NaFlexPrefDataset._global_bad_limit:
                    print(f"  [Dataset] Suppressing further warnings...", flush=True)
            img = Image.new("RGB", (256, 256), color="grey")

        if self.aug_transforms:
            img = self.aug_transforms(img)

        # Processor returns dict with pixel_values, possibly pixel_attention_mask etc.
        inputs = self.processor(images=img, return_tensors="pt", padding="max_length")
        # Squeeze batch dim (processor adds it)
        pixel_values = inputs["pixel_values"].squeeze(0)

        result = {"pixel_values": pixel_values, "label": torch.tensor(label, dtype=torch.float32)}

        # NaFlex processor may return attention mask for variable-length sequences
        if "pixel_attention_mask" in inputs:
            result["pixel_attention_mask"] = inputs["pixel_attention_mask"].squeeze(0)

        # spatial_shapes is required by Siglip2VisionTransformer for positional embedding interpolation
        if "spatial_shapes" in inputs:
            result["spatial_shapes"] = inputs["spatial_shapes"].squeeze(0)

        return result


def naflex_collate_fn(batch):
    """Custom collate for NaFlex: pad pixel_values to max seq len in batch."""
    labels = torch.stack([b["label"] for b in batch])
    pixel_values = [b["pixel_values"] for b in batch]

    # If all same shape, simple stack
    shapes = [pv.shape for pv in pixel_values]
    if len(set(shapes)) == 1:
        pv_batch = torch.stack(pixel_values)
        result = {"pixel_values": pv_batch, "labels": labels}
        if "pixel_attention_mask" in batch[0]:
            result["pixel_attention_mask"] = torch.stack([b["pixel_attention_mask"] for b in batch])
        if "spatial_shapes" in batch[0]:
            result["spatial_shapes"] = torch.stack([b["spatial_shapes"] for b in batch])
        return result

    # Variable shapes: pad to max
    # pixel_values shape: (C, H, W) for image or (C, N) for flattened patches
    ndim = pixel_values[0].ndim
    if ndim == 3:
        # (C, H, W) - pad H and W
        max_h = max(pv.shape[1] for pv in pixel_values)
        max_w = max(pv.shape[2] for pv in pixel_values)
        c = pixel_values[0].shape[0]
        pv_batch = torch.zeros(len(batch), c, max_h, max_w, dtype=pixel_values[0].dtype)
        attn_mask = torch.zeros(len(batch), max_h, max_w, dtype=torch.bool)
        for i, pv in enumerate(pixel_values):
            h, w = pv.shape[1], pv.shape[2]
            pv_batch[i, :, :h, :w] = pv
            attn_mask[i, :h, :w] = True
        result = {"pixel_values": pv_batch, "pixel_attention_mask": attn_mask, "labels": labels}
        if "spatial_shapes" in batch[0]:
            result["spatial_shapes"] = torch.stack([b["spatial_shapes"] for b in batch])
        return result
    else:
        # Fallback: just stack (should not happen with image processor)
        pv_batch = torch.stack(pixel_values)
        result = {"pixel_values": pv_batch, "labels": labels}
        if "pixel_attention_mask" in batch[0]:
            result["pixel_attention_mask"] = torch.stack([b["pixel_attention_mask"] for b in batch])
        if "spatial_shapes" in batch[0]:
            result["spatial_shapes"] = torch.stack([b["spatial_shapes"] for b in batch])
        return result


def validate_manifest(df, img_dir, max_check=None):
    """Pre-flight check: scan manifest for missing/unreadable images."""
    img_dir = Path(img_dir)
    missing, unreadable, ok = [], [], 0
    filenames = df["filename"].tolist()
    to_check = filenames if max_check is None else filenames[:max_check]
    for fname in to_check:
        path = img_dir / fname
        if not path.exists():
            missing.append(fname)
            continue
        try:
            with Image.open(path) as im:
                im.verify()
            ok += 1
        except Exception:
            unreadable.append(fname)
    return ok, missing, unreadable


# ---------------------------------------------------------------------------
# Transforms (tuned for anime/illustration)
# ---------------------------------------------------------------------------
def train_transform(size, mean=SIGLIP2_MEAN, std=SIGLIP2_STD):
    return transforms.Compose([
        transforms.RandomResizedCrop(size, scale=(0.80, 1.0), ratio=(0.75, 1.33)),
        transforms.RandomHorizontalFlip(0.5),
        transforms.RandomApply([
            transforms.ColorJitter(brightness=0.15, contrast=0.15, saturation=0.1, hue=0.02),
        ], p=0.3),
        transforms.RandomApply([
            transforms.GaussianBlur(kernel_size=5, sigma=(0.1, 1.0)),
        ], p=0.1),
        transforms.ToTensor(),
        transforms.Normalize(mean, std),
        transforms.RandomErasing(p=0.1, scale=(0.02, 0.08)),
    ])


def val_transform(size, mean=SIGLIP2_MEAN, std=SIGLIP2_STD):
    return transforms.Compose([
        transforms.Resize(int(size * 1.14), interpolation=transforms.InterpolationMode.BICUBIC),
        transforms.CenterCrop(size),
        transforms.ToTensor(),
        transforms.Normalize(mean, std),
    ])


def tta_transforms(size, mean=SIGLIP2_MEAN, std=SIGLIP2_STD):
    interp = transforms.InterpolationMode.BICUBIC
    norm = transforms.Normalize(mean, std)
    return [
        transforms.Compose([
            transforms.Resize(int(size * 1.14), interpolation=interp),
            transforms.CenterCrop(size), transforms.ToTensor(), norm,
        ]),
        transforms.Compose([
            transforms.Resize(int(size * 1.14), interpolation=interp),
            transforms.CenterCrop(size), transforms.RandomHorizontalFlip(p=1.0),
            transforms.ToTensor(), norm,
        ]),
        transforms.Compose([
            transforms.Resize(int(size * 1.25), interpolation=interp),
            transforms.CenterCrop(size), transforms.ToTensor(), norm,
        ]),
        transforms.Compose([
            transforms.Resize(int(size * 1.0), interpolation=interp),
            transforms.CenterCrop(size), transforms.ToTensor(), norm,
        ]),
    ]


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------
class SigLIP2Classifier(nn.Module):
    """SigLIP2 backbone + classification head with GELU activation."""

    def __init__(self, backbone, num_features, dropout=0.2):
        super().__init__()
        self.backbone = backbone
        hidden = 512
        self.head = nn.Sequential(
            nn.LayerNorm(num_features),
            nn.Dropout(dropout),
            nn.Linear(num_features, hidden),
            nn.GELU(),
            nn.LayerNorm(hidden),
            nn.Dropout(dropout * 0.5),
            nn.Linear(hidden, 1),
        )

    def forward(self, x):
        feats = self.backbone(x)
        if feats.ndim == 4:
            feats = feats.mean(dim=(2, 3))
        elif feats.ndim == 3:
            feats = feats.mean(dim=1)
        return self.head(feats)


# ---------------------------------------------------------------------------
# NaFlex Classifier (HuggingFace transformers backbone)
# ---------------------------------------------------------------------------
class NaFlexClassifier(nn.Module):
    """NaFlex SigLIP2 vision encoder + classification head.

    Uses the vision_model from google/siglip2-so400m-patch16-naflex.
    Features are extracted via the model's built-in pooling (MAP head).
    """

    def __init__(self, hf_model, num_features, dropout=0.2):
        super().__init__()
        # Extract just the vision model
        self.vision_model = hf_model.vision_model
        self.num_features = num_features
        hidden = 512
        self.head = nn.Sequential(
            nn.LayerNorm(num_features),
            nn.Dropout(dropout),
            nn.Linear(num_features, hidden),
            nn.GELU(),
            nn.LayerNorm(hidden),
            nn.Dropout(dropout * 0.5),
            nn.Linear(hidden, 1),
        )

    def forward(self, pixel_values, pixel_attention_mask=None, spatial_shapes=None):
        # vision_model (Siglip2VisionTransformer) expects attention_mask + spatial_shapes
        kwargs = {"pixel_values": pixel_values}
        if pixel_attention_mask is not None:
            kwargs["attention_mask"] = pixel_attention_mask
        if spatial_shapes is not None:
            kwargs["spatial_shapes"] = spatial_shapes
        outputs = self.vision_model(**kwargs)
        # pooler_output is the MAP-head pooled representation
        feats = outputs.pooler_output
        if feats is None:
            # Fallback: mean pool the last hidden state
            feats = outputs.last_hidden_state.mean(dim=1)
        return self.head(feats)


def create_naflex_model(checkpoint, unfreeze_stages=2, dropout=0.2, max_patches=None):
    """Create NaFlex-based classifier from HuggingFace checkpoint."""
    if not HAS_TRANSFORMERS:
        raise ImportError("transformers library required for NaFlex. Install: pip install transformers")

    log(f"Creating NaFlex backbone: {checkpoint}")
    log(f"  transformers: {_tf.__version__}")

    hf_model = AutoModel.from_pretrained(checkpoint, dtype=torch.float32)
    num_features = hf_model.config.vision_config.hidden_size
    num_layers = hf_model.config.vision_config.num_hidden_layers

    # Build classifier
    model = NaFlexClassifier(hf_model, num_features, dropout)

    # Freeze all vision params first
    for p in model.vision_model.parameters():
        p.requires_grad = False

    # Unfreeze last N encoder layers
    if unfreeze_stages > 0:
        layers = list(model.vision_model.encoder.layers)
        n_unfreeze = min(unfreeze_stages, len(layers))
        log(f"  Encoder layers: {len(layers)}, unfreezing last {n_unfreeze}")
        for i, layer in enumerate(layers[-n_unfreeze:]):
            for p in layer.parameters():
                p.requires_grad = True
            log(f"    Layer {len(layers) - n_unfreeze + i} → UNFROZEN")

    # Always unfreeze final layernorm and pooler (MAP head)
    if hasattr(model.vision_model, "post_layernorm"):
        for p in model.vision_model.post_layernorm.parameters():
            p.requires_grad = True
    if hasattr(model.vision_model, "head"):
        for p in model.vision_model.head.parameters():
            p.requires_grad = True

    total = sum(p.numel() for p in model.parameters())
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    log(f"  Features: {num_features}, Layers: {num_layers}")
    log(f"  Total: {total:,}, Trainable: {trainable:,} ({trainable/total*100:.1f}%)")

    # Load processor
    processor = AutoProcessor.from_pretrained(checkpoint)
    if max_patches is not None and hasattr(processor, "image_processor"):
        ip = processor.image_processor
        if hasattr(ip, "max_num_patches"):
            old_val = ip.max_num_patches
            ip.max_num_patches = max_patches
            log(f"  max_num_patches: {old_val} → {max_patches}")

    return model, processor


def verify_model_available(model_name):
    """Check that the requested model exists in timm's registry."""
    available = timm.list_models(pretrained=True)
    if model_name not in available:
        # Also try without pretrained filter
        all_models = timm.list_models()
        if model_name in all_models:
            log(f"  Warning: {model_name} exists but has no pretrained weights in this timm version.")
        else:
            similar = [m for m in all_models if "siglip" in m.lower()]
            raise ValueError(
                f"Model '{model_name}' not found in timm (version {timm.__version__}). "
                f"Available siglip models: {similar[:10]}"
            )


def create_model(model_name, unfreeze_stages=2, dropout=0.2, pretrained=True):
    log(f"Creating backbone: {model_name}")
    backbone = timm.create_model(model_name, pretrained=pretrained, num_classes=0)
    num_features = backbone.num_features

    # Freeze all first
    for p in backbone.parameters():
        p.requires_grad = False

    # Unfreeze last N blocks
    if unfreeze_stages > 0 and hasattr(backbone, "blocks"):
        blocks = list(backbone.blocks)
        n_unfreeze = min(unfreeze_stages, len(blocks))
        log(f"  ViT blocks: {len(blocks)}, unfreezing last {n_unfreeze}")
        for i, blk in enumerate(blocks[-n_unfreeze:]):
            for p in blk.parameters():
                p.requires_grad = True
            log(f"    Block {len(blocks) - n_unfreeze + i} → UNFROZEN")
    elif unfreeze_stages > 0:
        log(f"  Warning: backbone has no 'blocks' attribute, cannot unfreeze stages")

    # Always unfreeze final norm
    for attr in ("norm", "norm_pre", "fc_norm"):
        if hasattr(backbone, attr):
            for p in getattr(backbone, attr).parameters():
                p.requires_grad = True

    model = SigLIP2Classifier(backbone, num_features, dropout)

    total = sum(p.numel() for p in model.parameters())
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    log(f"  Features: {num_features}, Total: {total:,}, Trainable: {trainable:,} ({trainable/total*100:.1f}%)")
    return model


# ---------------------------------------------------------------------------
# Optimizer & Scheduler
# ---------------------------------------------------------------------------
def make_param_groups(model, lr_head, lr_backbone, wd=0.01):
    groups = {"head": [], "head_nd": [], "back": [], "back_nd": []}
    for name, p in model.named_parameters():
        if not p.requires_grad:
            continue
        is_head = name.startswith("head.")
        no_decay = any(k in name.lower() for k in ("bias", "norm", "layernorm", "gamma"))
        if is_head:
            (groups["head_nd"] if no_decay else groups["head"]).append(p)
        else:
            (groups["back_nd"] if no_decay else groups["back"]).append(p)
    return [
        {"params": groups["head"], "lr": lr_head, "weight_decay": wd, "label": "head"},
        {"params": groups["head_nd"], "lr": lr_head, "weight_decay": 0.0, "label": "head_nd"},
        {"params": groups["back"], "lr": lr_backbone, "weight_decay": wd, "label": "back"},
        {"params": groups["back_nd"], "lr": lr_backbone, "weight_decay": 0.0, "label": "back_nd"},
    ]


class WarmupCosine:
    def __init__(self, optimizer, warmup, total, min_ratio=0.01):
        self.opt = optimizer
        self.warmup = warmup
        self.total = total
        self.min_ratio = min_ratio
        self.base_lrs = [g["lr"] for g in optimizer.param_groups]

    def step(self, epoch):
        if epoch < self.warmup:
            alpha = (epoch + 1) / self.warmup
        else:
            t = (epoch - self.warmup) / max(1, self.total - self.warmup)
            alpha = self.min_ratio + 0.5 * (1 - self.min_ratio) * (1 + math.cos(math.pi * t))
        for g, base in zip(self.opt.param_groups, self.base_lrs):
            g["lr"] = base * alpha


# ---------------------------------------------------------------------------
# Training loop
# ---------------------------------------------------------------------------
def _unpack_batch(batch, device, naflex=False):
    """Unpack a batch from DataLoader, handling both standard and NaFlex formats."""
    if naflex:
        pixel_values = batch["pixel_values"].to(device, non_blocking=True)
        labels = batch["labels"].to(device, non_blocking=True)
        mask = batch.get("pixel_attention_mask")
        if mask is not None:
            mask = mask.to(device, non_blocking=True)
        spatial_shapes = batch.get("spatial_shapes")
        if spatial_shapes is not None:
            spatial_shapes = spatial_shapes.to(device, non_blocking=True)
        return pixel_values, labels, mask, spatial_shapes
    else:
        imgs, labels = batch
        return imgs.to(device, non_blocking=True), labels.to(device, non_blocking=True), None, None


def _forward_model(model, imgs, mask=None, spatial_shapes=None):
    """Forward pass handling both standard and NaFlex models."""
    if mask is not None:
        return model(imgs, pixel_attention_mask=mask, spatial_shapes=spatial_shapes).squeeze(-1)
    else:
        return model(imgs).squeeze(-1)


def train_one_epoch(model, loader, criterion, optimizer, device, scaler,
                    mixup_a=0.0, cutmix_a=0.0, mix_prob=0.0,
                    ema=None, raw_model=None, naflex=False):
    model.train()
    total_loss, correct, total = 0.0, 0, 0

    for batch in loader:
        imgs, labels, mask, spatial_shapes = _unpack_batch(batch, device, naflex)

        # Mixup/CutMix only for fixed-resolution (not NaFlex variable shapes)
        use_mix = (not naflex) and np.random.random() < mix_prob and (mixup_a > 0 or cutmix_a > 0)
        ya, yb, lam = labels, labels, 1.0
        if use_mix:
            if np.random.random() < 0.5:
                imgs, ya, yb, lam = mixup_data(imgs, labels, mixup_a)
            else:
                imgs, ya, yb, lam = cutmix_data(imgs, labels, cutmix_a)

        optimizer.zero_grad(set_to_none=True)

        if scaler is not None:
            with torch.amp.autocast("cuda"):
                out = _forward_model(model, imgs, mask, spatial_shapes)
                loss = mix_criterion(criterion, out, ya, yb, lam) if use_mix else criterion(out, labels)
            scaler.scale(loss).backward()
            scaler.unscale_(optimizer)
            torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
            scaler.step(optimizer)
            scaler.update()
        else:
            out = _forward_model(model, imgs, mask, spatial_shapes)
            loss = mix_criterion(criterion, out, ya, yb, lam) if use_mix else criterion(out, labels)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
            optimizer.step()

        if ema and raw_model:
            ema.update(raw_model)

        total_loss += loss.item() * len(labels)
        with torch.no_grad():
            preds = (torch.sigmoid(out) >= 0.5).long()
            if use_mix:
                correct += (lam * (preds == ya.long()).float().sum().item() +
                            (1 - lam) * (preds == yb.long()).float().sum().item())
            else:
                correct += (preds == labels.long()).sum().item()
        total += len(labels)

    return total_loss / max(total, 1), correct / max(total, 1)


@torch.no_grad()
def evaluate(model, loader, criterion, device, naflex=False):
    model.eval()
    total_loss = 0.0
    all_probs, all_labels = [], []
    use_amp = device.type == "cuda"
    for batch in loader:
        imgs, labels, mask, spatial_shapes = _unpack_batch(batch, device, naflex)
        if use_amp:
            with torch.amp.autocast("cuda"):
                out = _forward_model(model, imgs, mask, spatial_shapes)
        else:
            out = _forward_model(model, imgs, mask, spatial_shapes)
        # Loss in float32 for stability
        out_f32 = out.float()
        total_loss += criterion(out_f32, labels).item() * len(labels)
        all_probs.extend(torch.sigmoid(out_f32).cpu().numpy())
        all_labels.extend(labels.cpu().numpy())
    probs, labels = np.array(all_probs), np.array(all_labels)
    return total_loss / max(len(labels), 1), probs, labels


@torch.no_grad()
def evaluate_tta(model, df, img_dir, size, device, bs=32, workers=4,
                 naflex=False, processor=None, cache_dir=None):
    model.eval()
    use_amp = device.type == "cuda"

    if naflex:
        # NaFlex: single pass (variable resolution already preserves aspect ratio)
        ds = NaFlexPrefDataset(df, img_dir, processor, augment=False, cache_dir=cache_dir)
        loader = DataLoader(ds, batch_size=bs, shuffle=False, num_workers=workers,
                            pin_memory=True, persistent_workers=workers > 0,
                            worker_init_fn=_worker_init_fn,
                            collate_fn=naflex_collate_fn)
        probs = []
        for batch in loader:
            imgs, labels, mask, spatial_shapes = _unpack_batch(batch, device, naflex=True)
            if use_amp:
                with torch.amp.autocast("cuda"):
                    out = _forward_model(model, imgs, mask, spatial_shapes)
            else:
                out = _forward_model(model, imgs, mask, spatial_shapes)
            probs.extend(torch.sigmoid(out.float()).cpu().numpy())
        avg = np.array(probs)
    else:
        all_runs = []
        for t in tta_transforms(size):
            ds = PrefDataset(df, img_dir, t, fallback_size=size)
            loader = DataLoader(ds, batch_size=bs, shuffle=False, num_workers=workers,
                                pin_memory=True, persistent_workers=workers > 0,
                                worker_init_fn=_worker_init_fn)
            probs = []
            for imgs, _ in loader:
                imgs = imgs.to(device, non_blocking=True)
                if use_amp:
                    with torch.amp.autocast("cuda"):
                        out = model(imgs).squeeze(-1)
                else:
                    out = model(imgs).squeeze(-1)
                probs.extend(torch.sigmoid(out.float()).cpu().numpy())
            all_runs.append(np.array(probs))
        avg = np.mean(all_runs, axis=0)

    labels = df["label"].values
    auc = roc_auc_score(labels, avg) if len(set(labels)) > 1 else 0.0
    return avg, auc


def _cpu_state(model):
    return {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}


def _cleanup_old_checkpoints(ckpt_dir, ckpt_stem, keep_last):
    """Remove old epoch checkpoints, keeping the most recent `keep_last` by epoch number."""
    if keep_last <= 0:
        return
    existing = sorted(
        glob.glob(str(ckpt_dir / f"{ckpt_stem}_epoch*.pt")),
        key=_epoch_num_from_path,
    )
    while len(existing) > keep_last:
        old = existing.pop(0)
        try:
            os.remove(old)
            log(f"    Removed old checkpoint: {old}")
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    rank, local_rank, world_size = setup_ddp()
    ddp = world_size > 1

    p = argparse.ArgumentParser(description="SigLIP2 Preference Classifier Training")
    p.add_argument("--naflex", action="store_true",
                   help="Use NaFlex backbone (google/siglip2-so400m-patch16-naflex) with variable resolution")
    p.add_argument("--naflex-checkpoint", default=NAFLEX_CHECKPOINT,
                   help="HuggingFace checkpoint for NaFlex model")
    p.add_argument("--max-patches", type=int, default=None,
                   help="Max number of patches for NaFlex (default: model default 256, try 512 for more detail)")
    p.add_argument("--size", type=int, default=384, choices=[256, 384, 512],
                   help="Input resolution for timm backbone (ignored with --naflex)")
    p.add_argument("--epochs", type=int, default=20)
    p.add_argument("--batch-size", type=int, default=32, help="Per-GPU batch size")
    p.add_argument("--lr-head", type=float, default=2e-4)
    p.add_argument("--lr-backbone", type=float, default=1e-5)
    p.add_argument("--unfreeze", type=int, default=2,
                   help="Unfreeze last N transformer blocks (default 2 for SigLIP2)")
    p.add_argument("--dropout", type=float, default=0.2)
    p.add_argument("--label-smoothing", type=float, default=0.05)
    p.add_argument("--mixup-alpha", type=float, default=0.2)
    p.add_argument("--cutmix-alpha", type=float, default=1.0)
    p.add_argument("--mix-prob", type=float, default=0.3,
                   help="Probability of applying mixup/cutmix (0.3 default for anime)")
    p.add_argument("--warmup-epochs", type=int, default=2)
    p.add_argument("--patience", type=int, default=5)
    p.add_argument("--ema-decay", type=float, default=0.998)
    p.add_argument("--weight-decay", type=float, default=0.01)
    p.add_argument("--folds", type=int, default=5)
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--cache-dir", default=None,
                   help="Directory to cache NaFlex preprocessed tensors. "
                        "If not set, defaults to <data-dir>/_naflex_cache. "
                        "Use --no-cache to disable caching entirely.")
    p.add_argument("--no-cache", action="store_true",
                   help="Disable NaFlex preprocessing cache (process on-the-fly)")
    p.add_argument("--cache-only", action="store_true",
                   help="Only build NaFlex preprocessing cache, then exit (no training)")
    p.add_argument("--data-dir", default=".")
    p.add_argument("--output", default="model_siglip2.pt")
    p.add_argument("--init-from", default=None,
                   help="Initialize weights from checkpoint (progressive training, e.g. 384→512)")
    p.add_argument("--resume", default=None,
                   help="Resume interrupted training (restores optimizer, scheduler, EMA, epoch)")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--deterministic", action="store_true",
                   help="Enable cudnn deterministic mode (slower but reproducible)")
    p.add_argument("--no-tta", action="store_true")
    p.add_argument("--cv", action="store_true", help="Enable cross-validation before final training")
    p.add_argument("--save-every", type=int, default=5)
    p.add_argument("--save-last", type=int, default=3)
    p.add_argument("--validate-data", action="store_true",
                   help="Scan all images before training to report missing/corrupt files")
    args = p.parse_args()
    args.tta = not args.no_tta

    if args.init_from and args.resume:
        p.error("--init-from and --resume are mutually exclusive")

    set_seed(args.seed, rank, args.deterministic)

    # Resolve model name
    naflex_processor = None
    if args.naflex:
        model_name = args.naflex_checkpoint
        log(f"Using NaFlex backbone: {model_name}")
    else:
        model_name = SIGLIP2_MODELS.get(args.size)
        if model_name is None:
            raise ValueError(f"No SigLIP2 model for size {args.size}. Available: {list(SIGLIP2_MODELS.keys())}")
        # Verify model exists in timm
        if is_main():
            verify_model_available(model_name)

    data_dir = Path(args.data_dir)
    img_dir = data_dir / "images"
    manifest = data_dir / "manifest.csv"
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)

    log(f"\n{'='*60}")
    log(f"SigLIP2 Preference Classifier Training")
    log(f"{'='*60}")
    log(f"Model:      {model_name}")
    if args.naflex:
        log(f"Resolution: variable (NaFlex, max_patches={args.max_patches or 'default'})")
        if HAS_TRANSFORMERS:
            log(f"transformers: {_tf.__version__}")
    else:
        log(f"Resolution: {args.size}x{args.size}")
        log(f"Normalize:  mean={SIGLIP2_MEAN}, std={SIGLIP2_STD}")
        log(f"timm:       {timm.__version__}")

    # Load manifest
    if not manifest.exists():
        raise FileNotFoundError(f"Manifest not found: {manifest}")
    df = pd.read_csv(manifest)
    assert {"filename", "label"}.issubset(df.columns), "Need 'filename' and 'label' columns"
    df["label"] = df["label"].astype(int)
    assert set(df["label"].unique()).issubset({0, 1}), f"Labels must be 0/1, got {df['label'].unique()}"

    n_liked = int(df["label"].sum())
    n_disliked = len(df) - n_liked
    log(f"Dataset:    {len(df)} images ({n_liked} liked / {n_disliked} disliked)")

    # Optional data validation
    if args.validate_data and is_main():
        log(f"\nValidating images...")
        ok, missing, unreadable = validate_manifest(df, img_dir)
        log(f"  OK: {ok}, Missing: {len(missing)}, Unreadable: {len(unreadable)}")
        if missing:
            log(f"  First missing: {missing[:5]}")
        if unreadable:
            log(f"  First unreadable: {unreadable[:5]}")
        bad_total = len(missing) + len(unreadable)
        bad_pct = bad_total / len(df) * 100
        if bad_pct > 10:
            raise RuntimeError(
                f"{bad_total}/{len(df)} images ({bad_pct:.1f}%) are missing or corrupt. "
                f"Fix your dataset before training."
            )
        elif bad_total > 0:
            log(f"  Warning: {bad_total} bad images ({bad_pct:.1f}%) — will use grey fallback")

    device = torch.device(f"cuda:{local_rank}" if torch.cuda.is_available() else "cpu")
    log(f"Device:     {device} (world_size={world_size})")
    if device.type == "cuda":
        log(f"  GPU: {torch.cuda.get_device_name(local_rank)}")
        mem = torch.cuda.get_device_properties(local_rank).total_memory / 1024**3
        log(f"  VRAM: {mem:.1f} GB")
        if ddp:
            log(f"  Effective batch: {args.batch_size} x {world_size} = {args.batch_size * world_size}")

    log(f"\nHyperparameters:")
    for k, v in vars(args).items():
        log(f"  {k:20s}: {v}")

    # Interrupt handler
    if is_main():
        _handler.pid = os.getpid()
        signal.signal(signal.SIGINT, _handler.handle)

    ckpt_meta = {
        "model_name": model_name,
        "model_class": "NaFlexClassifier" if args.naflex else "SigLIP2Classifier",
        "backbone_family": "siglip2_naflex" if args.naflex else "siglip2",
        "input_size": "variable" if args.naflex else args.size,
        "max_num_patches": args.max_patches,
        "unfreeze_stages": args.unfreeze,
        "dropout": args.dropout,
        "normalize_mean": list(SIGLIP2_MEAN),
        "normalize_std": list(SIGLIP2_STD),
        "hyperparameters": vars(args),
    }
    ckpt_dir = Path(args.output).parent
    ckpt_stem = Path(args.output).stem

    # Pre-create NaFlex processor if needed (shared across folds/final training)
    if args.naflex and naflex_processor is None:
        if not HAS_TRANSFORMERS:
            raise ImportError("transformers library required for NaFlex. Install: pip install transformers")
        naflex_processor = AutoProcessor.from_pretrained(args.naflex_checkpoint)
        if args.max_patches is not None and hasattr(naflex_processor, "image_processor"):
            ip = naflex_processor.image_processor
            if hasattr(ip, "max_num_patches"):
                ip.max_num_patches = args.max_patches
                log(f"  NaFlex max_num_patches set to {args.max_patches}")

    # ===================================================================
    # NaFlex preprocessing cache
    # ===================================================================
    naflex_cache_dir = None
    if args.naflex and not args.no_cache:
        naflex_cache_dir = Path(args.cache_dir) if args.cache_dir else Path(args.data_dir) / "_naflex_cache"
        log(f"NaFlex cache dir: {naflex_cache_dir}")
        preprocess_naflex_cache(df, img_dir, naflex_processor, naflex_cache_dir, args.max_patches)

    if args.cache_only:
        log("--cache-only: cache built, exiting.")
        if ddp:
            dist.destroy_process_group()
        return

    # ===================================================================
    # Cross-Validation (optional)
    # ===================================================================
    overall_auc = 0.0
    fold_aucs = []
    fold_stopped = []
    best_threshold = 0.5
    best_f1 = 0.0
    final_epochs = args.epochs

    if args.cv:
        # Validate we have enough samples per class
        if min(n_liked, n_disliked) < args.folds:
            raise ValueError(
                f"Not enough samples for {args.folds}-fold CV: "
                f"liked={n_liked}, disliked={n_disliked}. "
                f"Need at least {args.folds} samples in each class."
            )

        skf = StratifiedKFold(n_splits=args.folds, shuffle=True, random_state=args.seed)
        oof_probs = np.zeros(len(df))

        for fold, (train_idx, val_idx) in enumerate(skf.split(df, df["label"])):
            log(f"\n{'='*60}")
            log(f"Fold {fold+1}/{args.folds}")
            log(f"{'='*60}")

            train_df, val_df = df.iloc[train_idx], df.iloc[val_idx]

            if args.naflex:
                train_ds = NaFlexPrefDataset(train_df, img_dir, naflex_processor, augment=True, cache_dir=naflex_cache_dir)
                val_ds = NaFlexPrefDataset(val_df, img_dir, naflex_processor, augment=False, cache_dir=naflex_cache_dir)
                collate = naflex_collate_fn
            else:
                train_ds = PrefDataset(train_df, img_dir, train_transform(args.size), fallback_size=args.size)
                val_ds = PrefDataset(val_df, img_dir, val_transform(args.size), fallback_size=args.size)
                collate = None

            train_sampler = DistributedSampler(train_ds, shuffle=True) if ddp else None
            train_loader = DataLoader(
                train_ds, batch_size=args.batch_size,
                shuffle=(train_sampler is None), sampler=train_sampler,
                num_workers=args.workers, pin_memory=True, drop_last=True,
                persistent_workers=args.workers > 0,
                worker_init_fn=_worker_init_fn,
                collate_fn=collate)
            val_loader = DataLoader(
                val_ds, batch_size=args.batch_size, shuffle=False,
                num_workers=args.workers, pin_memory=True,
                persistent_workers=args.workers > 0,
                worker_init_fn=_worker_init_fn,
                collate_fn=collate)

            if args.naflex:
                model, naflex_processor = create_naflex_model(
                    args.naflex_checkpoint, args.unfreeze, args.dropout, args.max_patches)
            else:
                model = create_model(model_name, args.unfreeze, args.dropout)
            model = model.to(device)
            raw_model = model
            ema = EMA(raw_model, args.ema_decay) if args.ema_decay > 0 else None

            if ddp:
                model = DDP(model, device_ids=[local_rank], find_unused_parameters=False)

            n_pos = int(train_df["label"].sum())
            pw = torch.tensor([max(len(train_df) - n_pos, 1) / max(n_pos, 1)], device=device)

            criterion = (SmoothBCEWithLogits(args.label_smoothing, pw)
                         if args.label_smoothing > 0
                         else nn.BCEWithLogitsLoss(pos_weight=pw))
            val_criterion = nn.BCEWithLogitsLoss(pos_weight=pw)

            optimizer = torch.optim.AdamW(
                make_param_groups(raw_model, args.lr_head, args.lr_backbone, args.weight_decay))
            scheduler = WarmupCosine(optimizer, args.warmup_epochs, args.epochs)
            scaler = torch.amp.GradScaler("cuda") if device.type == "cuda" else None

            best_auc, best_probs, best_state = -1.0, None, None
            patience_ctr = 0
            stopped_epoch = args.epochs

            for epoch in range(args.epochs):
                if train_sampler:
                    train_sampler.set_epoch(epoch)
                t0 = time.time()
                scheduler.step(epoch)

                tr_loss, tr_acc = train_one_epoch(
                    model, train_loader, criterion, optimizer, device, scaler,
                    args.mixup_alpha, args.cutmix_alpha, args.mix_prob,
                    ema=ema, raw_model=raw_model, naflex=args.naflex)

                v_loss, v_acc, v_auc = 0.0, 0.0, 0.0
                probs_now = None

                if ema:
                    ema.apply(raw_model)

                if is_main():
                    v_loss, probs_now, vlabels = evaluate(raw_model, val_loader, val_criterion, device, naflex=args.naflex)
                    v_acc = ((probs_now >= 0.5).astype(int) == vlabels).mean()
                    v_auc = roc_auc_score(vlabels, probs_now) if len(set(vlabels)) > 1 else 0.0

                if ema:
                    ema.restore(raw_model)

                if ddp:
                    bcast = [v_loss, v_acc, v_auc]
                    dist.broadcast_object_list(bcast, src=0)
                    v_loss, v_acc, v_auc = bcast

                lr_h = next((g["lr"] for g in optimizer.param_groups if g.get("label") == "head"), 0)
                lr_b = next((g["lr"] for g in optimizer.param_groups if g.get("label") == "back"), 0)
                log(f"  E{epoch+1:02d}/{args.epochs} ({time.time()-t0:.0f}s) | "
                    f"tr loss={tr_loss:.4f} acc={tr_acc:.3f} | "
                    f"val loss={v_loss:.4f} acc={v_acc:.3f} AUC={v_auc:.4f} | "
                    f"lr_h={lr_h:.1e} lr_b={lr_b:.1e}")

                if v_auc > best_auc:
                    best_auc = v_auc
                    patience_ctr = 0
                    if is_main():
                        best_probs = probs_now.copy()
                    if ema:
                        ema.apply(raw_model)
                        best_state = _cpu_state(raw_model)
                        ema.restore(raw_model)
                    else:
                        best_state = _cpu_state(raw_model)
                    if is_main():
                        path = ckpt_dir / f"{ckpt_stem}_fold{fold+1}_best.pt"
                        meta = {**ckpt_meta, "fold": fold+1, "epoch": epoch+1, "val_auc": v_auc}
                        if save_checkpoint(best_state, path, meta):
                            _handler.last_ckpt = str(path)
                else:
                    patience_ctr += 1
                    if patience_ctr >= args.patience:
                        stopped_epoch = epoch + 1
                        log(f"  Early stopping at epoch {stopped_epoch}")
                        break

            fold_stopped.append(stopped_epoch)

            # TTA
            if args.tta and best_state and is_main():
                rm = raw_model.module if hasattr(raw_model, "module") else raw_model
                rm.load_state_dict(best_state)
                rm = rm.to(device)
                tta_probs, tta_auc = evaluate_tta(rm, val_df, img_dir, args.size, device,
                                                   args.batch_size, args.workers,
                                                   naflex=args.naflex, processor=naflex_processor,
                                                   cache_dir=naflex_cache_dir)
                if tta_auc > best_auc:
                    log(f"  TTA improved: {best_auc:.4f} → {tta_auc:.4f}")
                    best_auc = tta_auc
                    best_probs = tta_probs.copy()
                else:
                    log(f"  TTA: {tta_auc:.4f} (no improvement)")

            if is_main() and best_probs is not None:
                oof_probs[val_idx] = best_probs

            fold_aucs.append(best_auc)
            log(f"  Best AUC: {best_auc:.4f} (stopped epoch {stopped_epoch})")

            del model, raw_model, ema, optimizer, scaler
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            if ddp:
                dist.barrier()

        # CV summary
        if is_main():
            overall_auc = roc_auc_score(df["label"].values, oof_probs)
            log(f"\n{'='*60}")
            log(f"CV Results")
            log(f"{'='*60}")
            log(f"Fold AUCs:   {[f'{a:.4f}' for a in fold_aucs]}")
            log(f"Mean AUC:    {np.mean(fold_aucs):.4f} ± {np.std(fold_aucs):.4f}")
            log(f"Overall AUC: {overall_auc:.4f}")
            log(classification_report(df["label"].values, (oof_probs >= 0.5).astype(int),
                                      target_names=["disliked", "liked"], zero_division=0))
            for t in np.arange(0.30, 0.70, 0.01):
                preds = (oof_probs >= t).astype(int)
                tp = ((preds == 1) & (df["label"].values == 1)).sum()
                fp = ((preds == 1) & (df["label"].values == 0)).sum()
                fn = ((preds == 0) & (df["label"].values == 1)).sum()
                prec = tp / max(tp + fp, 1)
                rec = tp / max(tp + fn, 1)
                f1 = 2 * prec * rec / max(prec + rec, 1e-8)
                if f1 > best_f1:
                    best_f1, best_threshold = f1, t
            log(f"Optimal threshold: {best_threshold:.2f} (F1={best_f1:.4f})")

        avg_stop = int(np.mean(fold_stopped))
        final_epochs = min(avg_stop + 2, args.epochs)
        if ddp:
            bcast = [final_epochs, best_threshold, overall_auc]
            dist.broadcast_object_list(bcast, src=0)
            final_epochs, best_threshold, overall_auc = bcast
    else:
        log(f"\nSkipping CV. Training on all data for {final_epochs} epochs.")

    # ===================================================================
    # Final training on all data
    # ===================================================================
    log(f"\n{'='*60}")
    log(f"Final training: {final_epochs} epochs on all {len(df)} images")
    log(f"{'='*60}")

    if args.naflex:
        full_ds = NaFlexPrefDataset(df, img_dir, naflex_processor, augment=True, cache_dir=naflex_cache_dir)
        collate = naflex_collate_fn
    else:
        full_ds = PrefDataset(df, img_dir, train_transform(args.size), fallback_size=args.size)
        collate = None
    full_sampler = DistributedSampler(full_ds, shuffle=True) if ddp else None
    full_loader = DataLoader(
        full_ds, batch_size=args.batch_size,
        shuffle=(full_sampler is None), sampler=full_sampler,
        num_workers=args.workers, pin_memory=True, drop_last=True,
        persistent_workers=args.workers > 0,
        worker_init_fn=_worker_init_fn,
        collate_fn=collate)

    if args.naflex:
        model, naflex_processor = create_naflex_model(
            args.naflex_checkpoint, args.unfreeze, args.dropout, args.max_patches)
    else:
        model = create_model(model_name, args.unfreeze, args.dropout)
    model = model.to(device)
    raw_model = model

    # --init-from: load weights only (progressive training 384→512)
    if args.init_from:
        log(f"Initializing weights from: {args.init_from}")
        ckpt = torch.load(args.init_from, map_location="cpu", weights_only=False)
        state = ckpt.get("model_state_dict", ckpt)
        model_state = raw_model.state_dict()
        filtered = {}
        for k, v in state.items():
            if k in model_state:
                if v.shape == model_state[k].shape:
                    filtered[k] = v
                else:
                    log(f"  Skipping {k}: shape mismatch {v.shape} vs {model_state[k].shape}")
            else:
                log(f"  Skipping {k}: not in current model")
        missing, unexpected = raw_model.load_state_dict(filtered, strict=False)
        if missing:
            log(f"  Missing keys: {len(missing)} (pos_embed etc. will use init values)")
        log(f"  Loaded {len(filtered)}/{len(state)} parameters")

    ema = EMA(raw_model, args.ema_decay) if args.ema_decay > 0 else None

    if ddp:
        model = DDP(model, device_ids=[local_rank], find_unused_parameters=False)

    pw = torch.tensor([n_disliked / max(n_liked, 1)], device=device)
    criterion = (SmoothBCEWithLogits(args.label_smoothing, pw)
                 if args.label_smoothing > 0
                 else nn.BCEWithLogitsLoss(pos_weight=pw))

    optimizer = torch.optim.AdamW(
        make_param_groups(raw_model, args.lr_head, args.lr_backbone, args.weight_decay))
    scheduler = WarmupCosine(optimizer, args.warmup_epochs, final_epochs)
    scaler = torch.amp.GradScaler("cuda") if device.type == "cuda" else None

    start_epoch = 0

    # --resume: full state restore
    if args.resume:
        log(f"Resuming training from: {args.resume}")
        ckpt = torch.load(args.resume, map_location="cpu", weights_only=False)

        # Model
        state = ckpt.get("model_state_dict", ckpt)
        missing, unexpected = raw_model.load_state_dict(state, strict=False)
        if missing:
            log(f"  Warning: {len(missing)} missing keys in model")
        if unexpected:
            log(f"  Warning: {len(unexpected)} unexpected keys in model")

        # Optimizer
        if "optimizer_state_dict" in ckpt:
            try:
                optimizer.load_state_dict(ckpt["optimizer_state_dict"])
                # Move optimizer state to correct device
                for state_val in optimizer.state.values():
                    for k, v in state_val.items():
                        if isinstance(v, torch.Tensor):
                            state_val[k] = v.to(device)
                log(f"  Restored optimizer state")
            except Exception as e:
                log(f"  Warning: could not restore optimizer: {e}")

        # Scaler
        if scaler is not None and ckpt.get("scaler_state_dict") is not None:
            try:
                scaler.load_state_dict(ckpt["scaler_state_dict"])
                log(f"  Restored GradScaler state")
            except Exception as e:
                log(f"  Warning: could not restore scaler: {e}")

        # EMA
        if ema is not None and ckpt.get("ema_shadow") is not None:
            try:
                ema.load_shadow(ckpt["ema_shadow"], device=device)
                log(f"  Restored EMA shadow")
            except Exception as e:
                log(f"  Warning: could not restore EMA: {e}")

        # Epoch
        if "epoch" in ckpt:
            start_epoch = ckpt["epoch"]
            log(f"  Resuming from epoch {start_epoch}")

        # Scheduler: step through past epochs
        if "scheduler_epoch" in ckpt:
            sched_epoch = ckpt["scheduler_epoch"]
            log(f"  Restoring scheduler to epoch {sched_epoch}")
        else:
            sched_epoch = start_epoch
        # Re-apply scheduler state by stepping
        for e in range(sched_epoch):
            scheduler.step(e)

        log(f"  Resume complete. Will train epochs {start_epoch+1} to {final_epochs}")

    for epoch in range(start_epoch, final_epochs):
        if full_sampler:
            full_sampler.set_epoch(epoch)
        t0 = time.time()
        scheduler.step(epoch)

        tr_loss, tr_acc = train_one_epoch(
            model, full_loader, criterion, optimizer, device, scaler,
            args.mixup_alpha, args.cutmix_alpha, args.mix_prob,
            ema=ema, raw_model=raw_model, naflex=args.naflex)

        lr_now = optimizer.param_groups[0]["lr"]
        log(f"  E{epoch+1:02d}/{final_epochs} ({time.time()-t0:.0f}s) | "
            f"loss={tr_loss:.4f} acc={tr_acc:.3f} | lr={lr_now:.2e}")

        cur = epoch + 1
        should_save = (args.save_every > 0 and cur % args.save_every == 0) or cur == final_epochs

        if should_save and is_main():
            if ema:
                ema.apply(raw_model)
                state = _cpu_state(raw_model)
                ema.restore(raw_model)
            else:
                state = _cpu_state(raw_model)

            ep_path = ckpt_dir / f"{ckpt_stem}_epoch{cur}.pt"
            meta = {**ckpt_meta, "phase": "final", "epoch": cur, "total_epochs": final_epochs}
            if save_checkpoint(state, ep_path, meta):
                _handler.last_ckpt = str(ep_path)
                log(f"    Checkpoint: {ep_path}")

            # Save full resumable checkpoint (always overwrite latest)
            latest_path = ckpt_dir / f"{ckpt_stem}_latest.pt"
            save_full_checkpoint(
                latest_path, raw_model, optimizer,
                scheduler_epoch=cur,
                scaler=scaler, ema=ema, epoch=cur,
                meta={**ckpt_meta, "phase": "final", "total_epochs": final_epochs},
            )
            _handler.last_ckpt = str(latest_path)

            _cleanup_old_checkpoints(ckpt_dir, ckpt_stem, args.save_last)

    # Final save
    if ema:
        ema.apply(raw_model)

    if is_main():
        output = Path(args.output)
        final_state = _cpu_state(raw_model)
        save_dict = {
            "model_state_dict": final_state,
            "model_name": model_name,
            "model_class": "NaFlexClassifier" if args.naflex else "SigLIP2Classifier",
            "backbone_family": "siglip2_naflex" if args.naflex else "siglip2",
            "num_classes": 1,
            "num_features": raw_model.num_features if args.naflex else raw_model.backbone.num_features,
            "head_hidden_dim": 512,
            "unfreeze_stages": args.unfreeze,
            "dropout": args.dropout,
            "input_size": "variable" if args.naflex else args.size,
            "naflex_checkpoint": args.naflex_checkpoint if args.naflex else None,
            "max_num_patches": args.max_patches if args.naflex else None,
            "optimal_threshold": float(best_threshold),
            "cv_auc": float(overall_auc) if overall_auc > 0 else None,
            "fold_aucs": fold_aucs or None,
            "final_epochs_trained": final_epochs,
            "n_samples": len(df),
            "n_liked": int(n_liked),
            "n_disliked": int(n_disliked),
            "normalize_mean": list(SIGLIP2_MEAN),
            "normalize_std": list(SIGLIP2_STD),
            "hyperparameters": vars(args),
        }
        tmp = str(output) + ".tmp"
        try:
            torch.save(save_dict, tmp)
            os.replace(tmp, output)
        except Exception:
            torch.save(save_dict, output)

        sz = output.stat().st_size / 1024**2
        log(f"\n{'='*60}")
        log(f"Model saved: {output} ({sz:.1f} MB)")
        if overall_auc > 0:
            log(f"CV AUC: {overall_auc:.4f}")
        log(f"Threshold: {best_threshold:.2f}")
        log(f"{'='*60}")


if __name__ == "__main__":
    try:
        main()
    finally:
        cleanup_ddp()