#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Preference classifier Image/Aesthetic training script - Optimized for 2D/Anime.
Fine-tunes OpenCLIP/EVA02 (ViT) or ConvNeXt on image preference data.
Supports multi-GPU training via DistributedDataParallel (DDP).

Usage:
    # Single GPU
    python train.py

    # Multi-GPU (3 cards)
    torchrun --nproc_per_node=3 train.py

    # Multi-GPU with options
    torchrun --nproc_per_node=3 train.py --model convnextv2_base.fcmae_ft_in22k_in1k --batch-size 48
"""

import argparse
import glob
import math
import os
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
from PIL import Image, ImageFile
from sklearn.model_selection import StratifiedKFold
from sklearn.metrics import classification_report, roc_auc_score

import timm

ImageFile.LOAD_TRUNCATED_IMAGES = True


# ---------------------------------------------------------------------------
# Reproducibility
# ---------------------------------------------------------------------------
def set_seed(seed=42, rank=0):
    """Set random seeds for reproducibility."""
    s = seed + rank
    random.seed(s)
    np.random.seed(s)
    torch.manual_seed(s)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(s)


# ---------------------------------------------------------------------------
# DDP helpers
# ---------------------------------------------------------------------------
def setup_ddp():
    """Initialize DDP if launched via torchrun. Returns (rank, local_rank, world_size)."""
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


def is_main_process():
    return not dist.is_initialized() or dist.get_rank() == 0


def log(msg, force=False):
    if force or is_main_process():
        print(msg, flush=True)


# ---------------------------------------------------------------------------
# Checkpoint saving + interrupt handler
# ---------------------------------------------------------------------------
def save_checkpoint(model_state_dict, path, meta=None):
    """Atomic checkpoint save: write to .tmp then rename."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    save_dict = {"model_state_dict": model_state_dict, **(meta or {})}
    tmp_path = str(path) + ".tmp"
    try:
        torch.save(save_dict, tmp_path)
        os.replace(tmp_path, path)
        return True
    except Exception as e:
        print(f"  Warning: checkpoint save failed: {e}")
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        return False


class CheckpointTracker:
    def __init__(self):
        self.last_saved_path = None
        self.output_path = None
        self.registered_pid = None

    def on_interrupt(self, signum, frame):
        if os.getpid() != self.registered_pid:
            os._exit(1)
        print(f"\n\nCtrl+C received!")
        if self.last_saved_path and os.path.exists(self.last_saved_path):
            sz = os.path.getsize(self.last_saved_path) / 1024**2
            print(f"Latest checkpoint already on disk: {self.last_saved_path} ({sz:.1f} MB)")
        else:
            print("No checkpoint saved yet.")
        print("Exiting.")
        os._exit(1)


_tracker = CheckpointTracker()


# ---------------------------------------------------------------------------
# Mixup / CutMix
# ---------------------------------------------------------------------------
def mixup_data(x, y, alpha=0.2):
    if alpha <= 0:
        return x, y, y, 1.0
    lam = np.random.beta(alpha, alpha)
    lam = max(lam, 1 - lam)
    index = torch.randperm(x.size(0), device=x.device)
    mixed_x = lam * x + (1 - lam) * x[index]
    return mixed_x, y, y[index], lam


def cutmix_data(x, y, alpha=1.0):
    if alpha <= 0:
        return x, y, y, 1.0
    lam = np.random.beta(alpha, alpha)
    index = torch.randperm(x.size(0), device=x.device)
    _, _, h, w = x.shape
    cut_rat = np.sqrt(1.0 - lam)
    cut_w, cut_h = int(w * cut_rat), int(h * cut_rat)
    cx, cy = np.random.randint(w), np.random.randint(h)
    x1 = np.clip(cx - cut_w // 2, 0, w)
    y1 = np.clip(cy - cut_h // 2, 0, h)
    x2 = np.clip(cx + cut_w // 2, 0, w)
    y2 = np.clip(cy + cut_h // 2, 0, h)
    x_clone = x.clone()
    x_clone[:, :, y1:y2, x1:x2] = x[index, :, y1:y2, x1:x2]
    lam = 1 - ((x2 - x1) * (y2 - y1) / (w * h))
    return x_clone, y, y[index], lam


def mixup_criterion(criterion, pred, y_a, y_b, lam):
    return lam * criterion(pred, y_a) + (1 - lam) * criterion(pred, y_b)


# ---------------------------------------------------------------------------
# EMA (per-step update)
# ---------------------------------------------------------------------------
class EMA:
    def __init__(self, model, decay=0.998):
        self.decay = decay
        self.shadow = {}
        self.backup = {}
        for name, param in model.named_parameters():
            if param.requires_grad:
                self.shadow[name] = param.data.clone()

    def update(self, model):
        for name, param in model.named_parameters():
            if param.requires_grad:
                self.shadow[name].mul_(self.decay).add_(param.data, alpha=1.0 - self.decay)

    def apply_shadow(self, model):
        for name, param in model.named_parameters():
            if param.requires_grad:
                self.backup[name] = param.data.clone()
                param.data.copy_(self.shadow[name])

    def restore(self, model):
        for name, param in model.named_parameters():
            if param.requires_grad:
                param.data.copy_(self.backup[name])
        self.backup = {}


# ---------------------------------------------------------------------------
# Label Smoothing BCE
# ---------------------------------------------------------------------------
class LabelSmoothingBCEWithLogitsLoss(nn.Module):
    def __init__(self, smoothing=0.05, pos_weight=None):
        super().__init__()
        self.smoothing = smoothing
        self.pos_weight = pos_weight

    def forward(self, logits, targets):
        targets_smooth = targets * (1 - self.smoothing) + 0.5 * self.smoothing
        return F.binary_cross_entropy_with_logits(
            logits, targets_smooth, pos_weight=self.pos_weight
        )


# ---------------------------------------------------------------------------
# Dataset
# ---------------------------------------------------------------------------
class PreferenceDataset(Dataset):
    def __init__(self, df, img_dir, transform=None):
        self.df = df.reset_index(drop=True)
        self.img_dir = Path(img_dir)
        self.transform = transform

    def __len__(self):
        return len(self.df)

    def __getitem__(self, idx):
        row = self.df.iloc[idx]
        img_path = self.img_dir / row["filename"]
        try:
            img = Image.open(img_path).convert("RGB")
        except Exception:
            img = Image.new('RGB', (336, 336), color='grey')
        if self.transform:
            img = self.transform(img)
        label = torch.tensor(row["label"], dtype=torch.float32)
        return img, label


# ---------------------------------------------------------------------------
# Transforms
# ---------------------------------------------------------------------------
def get_transforms(train=True, size=336, mean=(0.485, 0.456, 0.406), std=(0.229, 0.224, 0.225)):
    if train:
        return transforms.Compose([
            transforms.RandomResizedCrop(size, scale=(0.85, 1.0), ratio=(0.85, 1.15)),
            transforms.RandomHorizontalFlip(p=0.5),
            transforms.RandomApply([
                transforms.ColorJitter(brightness=0.1, contrast=0.1, saturation=0.1, hue=0.0)
            ], p=0.3),
            transforms.ToTensor(),
            transforms.Normalize(mean=mean, std=std),
            transforms.RandomErasing(p=0.1, scale=(0.02, 0.05), ratio=(0.3, 3.3)),
        ])
    else:
        return transforms.Compose([
            transforms.Resize(int(size * 1.14), interpolation=transforms.InterpolationMode.BICUBIC),
            transforms.CenterCrop(size),
            transforms.ToTensor(),
            transforms.Normalize(mean=mean, std=std),
        ])


def get_tta_transforms(size=336, mean=(0.485, 0.456, 0.406), std=(0.229, 0.224, 0.225)):
    base_norm = transforms.Normalize(mean=mean, std=std)
    interp = transforms.InterpolationMode.BICUBIC
    return [
        transforms.Compose([
            transforms.Resize(int(size * 1.14), interpolation=interp),
            transforms.CenterCrop(size), transforms.ToTensor(), base_norm,
        ]),
        transforms.Compose([
            transforms.Resize(int(size * 1.14), interpolation=interp),
            transforms.CenterCrop(size), transforms.RandomHorizontalFlip(p=1.0),
            transforms.ToTensor(), base_norm,
        ]),
        transforms.Compose([
            transforms.Resize(int(size * 1.25), interpolation=interp),
            transforms.CenterCrop(size), transforms.ToTensor(), base_norm,
        ]),
    ]


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------
class PreferenceModel(nn.Module):
    def __init__(self, backbone, num_features, dropout=0.2):
        super().__init__()
        self.backbone = backbone
        self.head = nn.Sequential(
            nn.LayerNorm(num_features),
            nn.Dropout(p=dropout),
            nn.Linear(num_features, 256),
            nn.GELU(),
            nn.Dropout(p=dropout * 0.5),
            nn.Linear(256, 1),
        )

    def forward(self, x):
        feats = self.backbone(x)
        # Defensive: if backbone returns spatial features [B, C, H, W], pool them
        if feats.ndim == 4:
            feats = feats.mean(dim=(2, 3))
        elif feats.ndim == 3:
            # [B, N, C] token output (some ViTs without pooling) -> mean pool
            feats = feats.mean(dim=1)
        return self.head(feats)


def resolve_model_normalization(model_name):
    """Read data_config without downloading pretrained weights."""
    backbone = timm.create_model(model_name, pretrained=False, num_classes=0)
    cfg = timm.data.resolve_model_data_config(backbone)
    mean, std = cfg['mean'], cfg['std']
    del backbone
    return mean, std


def create_model(model_name, unfreeze_stages=1, dropout=0.2):
    log(f"Creating model: {model_name}...")
    backbone = timm.create_model(model_name, pretrained=True, num_classes=0)
    num_features = backbone.num_features

    for param in backbone.parameters():
        param.requires_grad = False

    if unfreeze_stages > 0:
        if hasattr(backbone, 'blocks'):
            blocks = list(backbone.blocks)
            log(f"  Backbone architecture: ViT ({len(blocks)} blocks total)")
            for i, block in enumerate(blocks[-unfreeze_stages:]):
                for param in block.parameters():
                    param.requires_grad = True
                log(f"    Block {len(blocks) - unfreeze_stages + i} -> UNFROZEN")
        elif hasattr(backbone, 'stages'):
            stages = list(backbone.stages)
            log(f"  Backbone architecture: CNN/Hierarchical ({len(stages)} stages total)")
            for i, stage in enumerate(stages[-unfreeze_stages:]):
                for param in stage.parameters():
                    param.requires_grad = True
                log(f"    Stage {len(stages) - unfreeze_stages + i} -> UNFROZEN")
        else:
            log("  Warning: Backbone structure not recognized. Freezing entirely.")

    for attr in ('norm', 'norm_pre'):
        if hasattr(backbone, attr):
            for param in getattr(backbone, attr).parameters():
                param.requires_grad = True
    if hasattr(backbone, 'head') and hasattr(backbone.head, 'norm'):
        for param in backbone.head.norm.parameters():
            param.requires_grad = True

    model = PreferenceModel(backbone, num_features, dropout=dropout)

    frozen = sum(p.numel() for p in model.parameters() if not p.requires_grad)
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    total = frozen + trainable
    log(f"  Feature dim:  {num_features}")
    log(f"  Total params: {total:,}")
    log(f"  Frozen:       {frozen:,} ({frozen / total * 100:.1f}%)")
    log(f"  Trainable:    {trainable:,} ({trainable / total * 100:.1f}%)")
    return model


def get_parameter_groups(model, lr_head, lr_backbone, weight_decay=0.01):
    head_params, head_nodecay = [], []
    backbone_params, backbone_nodecay = [], []
    for name, param in model.named_parameters():
        if not param.requires_grad:
            continue
        is_head = name.startswith('head.')
        is_nodecay = ('bias' in name or 'norm' in name.lower() or
                      'layernorm' in name.lower() or 'gamma' in name)
        if is_head:
            (head_nodecay if is_nodecay else head_params).append(param)
        else:
            (backbone_nodecay if is_nodecay else backbone_params).append(param)
    groups = []
    if head_params:
        groups.append({"params": head_params, "lr": lr_head,
                        "weight_decay": weight_decay, "label": "head"})
    if head_nodecay:
        groups.append({"params": head_nodecay, "lr": lr_head,
                        "weight_decay": 0.0, "label": "head_nodecay"})
    if backbone_params:
        groups.append({"params": backbone_params, "lr": lr_backbone,
                        "weight_decay": weight_decay, "label": "backbone"})
    if backbone_nodecay:
        groups.append({"params": backbone_nodecay, "lr": lr_backbone,
                        "weight_decay": 0.0, "label": "backbone_nodecay"})
    return groups


def _get_lr_by_label(optimizer, label_prefix):
    """Get current LR for param group whose label starts with prefix."""
    for pg in optimizer.param_groups:
        if pg.get("label", "").startswith(label_prefix):
            return pg["lr"]
    # Fallback
    return optimizer.param_groups[-1]["lr"] if optimizer.param_groups else 0.0


def _state_dict_to_cpu(model):
    return {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}


# ---------------------------------------------------------------------------
# Warmup + Cosine scheduler
# ---------------------------------------------------------------------------
class WarmupCosineScheduler:
    def __init__(self, optimizer, warmup_epochs, total_epochs, min_lr_ratio=0.01):
        self.optimizer = optimizer
        self.warmup_epochs = warmup_epochs
        self.total_epochs = total_epochs
        self.min_lr_ratio = min_lr_ratio
        self.base_lrs = [pg['lr'] for pg in optimizer.param_groups]

    def step(self, epoch):
        if epoch < self.warmup_epochs:
            alpha = (epoch + 1) / self.warmup_epochs
        else:
            progress = (epoch - self.warmup_epochs) / max(1, self.total_epochs - self.warmup_epochs)
            alpha = self.min_lr_ratio + 0.5 * (1 - self.min_lr_ratio) * (1 + math.cos(math.pi * progress))
        for pg, base_lr in zip(self.optimizer.param_groups, self.base_lrs):
            pg['lr'] = base_lr * alpha

    def get_last_lr(self):
        return [pg['lr'] for pg in self.optimizer.param_groups]


# ---------------------------------------------------------------------------
# Evaluation (single-process only – see design note below)
# ---------------------------------------------------------------------------
# DESIGN: Validation always runs on rank 0 only, using the full val set
# without DistributedSampler. This avoids the subtle bug where
# DistributedSampler reorders/pads samples and gathered predictions
# no longer align with the original sample indices.
# The cost is negligible: val sets in CV folds are small, and we only
# need a forward pass without gradients.
# ---------------------------------------------------------------------------

@torch.no_grad()
def evaluate(model, loader, criterion, device):
    """Evaluate on a single device. Returns (avg_loss, probs, labels) as numpy."""
    model.eval()
    total_loss = 0.0
    all_probs, all_labels = [], []

    for imgs, labels in loader:
        imgs = imgs.to(device, non_blocking=True)
        labels = labels.to(device, non_blocking=True)
        outputs = model(imgs).squeeze(-1)
        loss = criterion(outputs, labels)
        total_loss += loss.item() * len(labels)
        all_probs.extend(torch.sigmoid(outputs).cpu().numpy())
        all_labels.extend(labels.cpu().numpy())

    all_probs = np.array(all_probs)
    all_labels = np.array(all_labels)
    n = len(all_labels)
    return total_loss / max(n, 1), all_probs, all_labels


def compute_metrics(probs, labels):
    """Compute accuracy and AUC from numpy arrays."""
    acc = ((probs >= 0.5).astype(int) == labels).mean()
    auc = roc_auc_score(labels, probs) if len(set(labels)) > 1 else 0.0
    return acc, auc


@torch.no_grad()
def evaluate_tta(model, dataset_df, img_dir, size, mean, std, device,
                 batch_size=32, num_workers=4):
    """TTA evaluation. Runs on single GPU (the caller's device)."""
    model.eval()
    tta_tfms = get_tta_transforms(size, mean, std)
    all_probs_list = []

    for t in tta_tfms:
        ds = PreferenceDataset(dataset_df, img_dir, t)
        loader = DataLoader(ds, batch_size=batch_size, shuffle=False,
                            num_workers=num_workers, pin_memory=True,
                            persistent_workers=num_workers > 0)
        probs = []
        for imgs, _ in loader:
            imgs = imgs.to(device, non_blocking=True)
            outputs = model(imgs).squeeze(-1)
            probs.extend(torch.sigmoid(outputs).cpu().numpy())
        all_probs_list.append(np.array(probs))

    avg_probs = np.mean(all_probs_list, axis=0)
    labels = dataset_df["label"].values
    auc = roc_auc_score(labels, avg_probs) if len(set(labels)) > 1 else 0.0
    return avg_probs, auc


# ---------------------------------------------------------------------------
# Mixup / CutMix
# ---------------------------------------------------------------------------
def train_one_epoch(model, loader, criterion, optimizer, device, scaler=None,
                    mixup_alpha=0.0, cutmix_alpha=0.0, mix_prob=0.0,
                    ema=None, raw_model=None):
    model.train()
    total_loss, correct, total = 0.0, 0, 0

    for imgs, labels in loader:
        imgs = imgs.to(device, non_blocking=True)
        labels = labels.to(device, non_blocking=True)

        use_mix = np.random.random() < mix_prob and (mixup_alpha > 0 or cutmix_alpha > 0)
        if use_mix:
            if np.random.random() < 0.5:
                imgs, labels_a, labels_b, lam = mixup_data(imgs, labels, mixup_alpha)
            else:
                imgs, labels_a, labels_b, lam = cutmix_data(imgs, labels, cutmix_alpha)

        optimizer.zero_grad(set_to_none=True)

        if scaler is not None:
            with torch.amp.autocast('cuda'):
                outputs = model(imgs).squeeze(-1)
                if use_mix:
                    loss = mixup_criterion(criterion, outputs, labels_a, labels_b, lam)
                else:
                    loss = criterion(outputs, labels)
            scaler.scale(loss).backward()
            scaler.unscale_(optimizer)
            torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
            scaler.step(optimizer)
            scaler.update()
        else:
            outputs = model(imgs).squeeze(-1)
            if use_mix:
                loss = mixup_criterion(criterion, outputs, labels_a, labels_b, lam)
            else:
                loss = criterion(outputs, labels)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
            optimizer.step()

        # EMA: update every step
        if ema is not None and raw_model is not None:
            ema.update(raw_model)

        total_loss += loss.item() * len(labels)
        with torch.no_grad():
            preds = (torch.sigmoid(outputs) >= 0.5).long()
            if use_mix:
                correct += (lam * (preds == labels_a.long()).float().sum().item() +
                            (1 - lam) * (preds == labels_b.long()).float().sum().item())
            else:
                correct += (preds == labels.long()).sum().item()
        total += len(labels)

    return total_loss / max(total, 1), correct / max(total, 1)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    rank, local_rank, world_size = setup_ddp()
    ddp_enabled = world_size > 1

    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="eva02_base_patch14_clip_336.merged2b")
    parser.add_argument("--epochs", type=int, default=20)
    parser.add_argument("--batch-size", type=int, default=32,
                        help="Per-GPU batch size")
    parser.add_argument("--lr-head", type=float, default=2e-4)
    parser.add_argument("--lr-backbone", type=float, default=1e-5)
    parser.add_argument("--size", type=int, default=336)
    parser.add_argument("--unfreeze", type=int, default=1)
    parser.add_argument("--dropout", type=float, default=0.2)
    parser.add_argument("--label-smoothing", type=float, default=0.05)
    parser.add_argument("--mixup-alpha", type=float, default=0.2)
    parser.add_argument("--cutmix-alpha", type=float, default=1.0)
    parser.add_argument("--mix-prob", type=float, default=0.0)
    parser.add_argument("--warmup-epochs", type=int, default=2)
    parser.add_argument("--patience", type=int, default=5)
    parser.add_argument("--ema-decay", type=float, default=0.998)
    parser.add_argument("--weight-decay", type=float, default=0.01)
    parser.add_argument("--folds", type=int, default=5)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--data-dir", default=".")
    parser.add_argument("--output", default="model_aesthetic.pt")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--no-tta", action="store_true",
                        help="Disable TTA during validation")
    parser.add_argument("--no-cv", action="store_true", default=True,
                        help="Skip cross-validation, train on all data directly")
    parser.add_argument("--cv", action="store_false", dest="no_cv",
                        help="Run cross-validation before final training")
    parser.add_argument("--save-every", type=int, default=5,
                        help="Save checkpoint every N epochs (0=disable)")
    parser.add_argument("--save-last", type=int, default=3,
                        help="Keep last N epoch checkpoints")
    args = parser.parse_args()
    args.tta = not args.no_tta

    # Reproducibility
    set_seed(args.seed, rank)

    data_dir = Path(args.data_dir)
    img_dir = data_dir / "images"
    manifest = data_dir / "manifest.csv"

    # Ensure output directory exists
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)

    # --- Load and validate manifest ---
    log(f"Loading manifest from {manifest}")
    if not manifest.exists():
        raise FileNotFoundError(f"Manifest not found: {manifest}")
    df = pd.read_csv(manifest)

    required_cols = {"filename", "label"}
    missing_cols = required_cols - set(df.columns)
    if missing_cols:
        raise ValueError(f"Manifest missing columns: {missing_cols}. Found: {list(df.columns)}")

    df["label"] = df["label"].astype(int)
    unique_labels = set(df["label"].unique())
    if not unique_labels.issubset({0, 1}):
        raise ValueError(f"Labels must be 0 or 1, found: {unique_labels}")

    log(f"Dataset: {len(df)} images, {df['label'].sum()} liked, "
        f"{(1 - df['label']).sum():.0f} disliked")

    device = torch.device(f"cuda:{local_rank}" if torch.cuda.is_available() else "cpu")
    log(f"Device: {device} (world_size={world_size})")
    if device.type == "cuda":
        log(f"  GPU {local_rank}: {torch.cuda.get_device_name(local_rank)}")
        log(f"  VRAM: {torch.cuda.get_device_properties(local_rank).total_mem / 1024**3:.1f} GB"
            if hasattr(torch.cuda.get_device_properties(local_rank), 'total_mem')
            else f"  VRAM: {torch.cuda.get_device_properties(local_rank).total_memory / 1024**3:.1f} GB")
        if ddp_enabled:
            log(f"  Effective batch size: {args.batch_size} x {world_size} = "
                f"{args.batch_size * world_size}")

    log(f"\nHyperparameters:")
    for k, v in vars(args).items():
        log(f"  {k:20s}: {v}")

    # Interrupt handler
    _tracker.output_path = args.output
    if is_main_process():
        _tracker.registered_pid = os.getpid()
        signal.signal(signal.SIGINT, _tracker.on_interrupt)

    # Resolve normalization
    model_mean, model_std = resolve_model_normalization(args.model)
    log(f"  Native normalization => Mean: {model_mean}, Std: {model_std}")

    ckpt_meta = {
        "model_name": args.model,
        "model_class": "PreferenceModel",
        "input_size": args.size,
        "unfreeze_stages": args.unfreeze,
        "dropout": args.dropout,
        "normalize_mean": list(model_mean),
        "normalize_std": list(model_std),
        "hyperparameters": vars(args),
    }
    ckpt_dir = Path(args.output).parent
    ckpt_stem = Path(args.output).stem

    # ===================================================================
    # Cross-validation (optional)
    # Training: ALL GPUs via DDP
    # Validation: rank 0 only (avoids DistributedSampler ordering issues)
    # ===================================================================
    overall_auc = 0.0
    fold_aucs = []
    fold_stopped = []
    best_threshold = 0.5
    best_f1 = 0.0
    final_epochs = args.epochs

    if not args.no_cv:
        skf = StratifiedKFold(n_splits=args.folds, shuffle=True, random_state=args.seed)
        all_val_probs = np.zeros(len(df))

        for fold, (train_idx, val_idx) in enumerate(skf.split(df, df["label"])):
            log(f"\n{'=' * 60}")
            log(f"Fold {fold + 1}/{args.folds}")
            log(f"{'=' * 60}")

            train_df = df.iloc[train_idx]
            val_df = df.iloc[val_idx]

            train_ds = PreferenceDataset(
                train_df, img_dir,
                get_transforms(True, args.size, model_mean, model_std))
            val_ds = PreferenceDataset(
                val_df, img_dir,
                get_transforms(False, args.size, model_mean, model_std))

            # Training: DDP sampler for all ranks
            train_sampler = DistributedSampler(train_ds, shuffle=True) if ddp_enabled else None
            train_loader = DataLoader(
                train_ds, batch_size=args.batch_size,
                shuffle=(train_sampler is None), sampler=train_sampler,
                num_workers=args.workers, pin_memory=True, drop_last=True,
                persistent_workers=args.workers > 0)

            # Validation: NO DDP sampler – rank 0 evaluates the full val set
            # Other ranks skip evaluation and wait at barrier
            val_loader = DataLoader(
                val_ds, batch_size=args.batch_size,
                shuffle=False,
                num_workers=args.workers, pin_memory=True,
                persistent_workers=args.workers > 0)

            model = create_model(args.model, unfreeze_stages=args.unfreeze,
                                 dropout=args.dropout)
            model = model.to(device)
            raw_model = model
            ema = EMA(raw_model, decay=args.ema_decay) if args.ema_decay > 0 else None

            if ddp_enabled:
                model = DDP(model, device_ids=[local_rank], find_unused_parameters=False)

            n_pos = train_df["label"].sum()
            n_neg = len(train_df) - n_pos
            pos_weight = torch.tensor([n_neg / max(n_pos, 1)], device=device)

            criterion = (LabelSmoothingBCEWithLogitsLoss(args.label_smoothing, pos_weight)
                         if args.label_smoothing > 0
                         else nn.BCEWithLogitsLoss(pos_weight=pos_weight))
            val_criterion = nn.BCEWithLogitsLoss(pos_weight=pos_weight)

            param_groups = get_parameter_groups(raw_model, args.lr_head,
                                                args.lr_backbone, args.weight_decay)
            optimizer = torch.optim.AdamW(param_groups)
            scheduler = WarmupCosineScheduler(optimizer, args.warmup_epochs, args.epochs)
            scaler = torch.amp.GradScaler('cuda') if device.type == "cuda" else None

            best_auc = -1.0
            best_probs = None
            best_state = None
            patience_counter = 0
            stopped_epoch = args.epochs

            for epoch in range(args.epochs):
                if train_sampler is not None:
                    train_sampler.set_epoch(epoch)

                t0 = time.time()
                scheduler.step(epoch)

                train_loss, train_acc = train_one_epoch(
                    model, train_loader, criterion, optimizer, device, scaler,
                    args.mixup_alpha, args.cutmix_alpha, args.mix_prob,
                    ema=ema, raw_model=raw_model)

                # --- Validation: rank 0 only ---
                val_loss, val_acc, val_auc = 0.0, 0.0, 0.0
                gathered_probs = None

                if ema:
                    ema.apply_shadow(raw_model)

                if is_main_process():
                    val_loss, local_probs, local_labels = evaluate(
                        raw_model, val_loader, val_criterion, device)
                    val_acc, val_auc = compute_metrics(local_probs, local_labels)
                    gathered_probs = local_probs.copy()

                if ema:
                    ema.restore(raw_model)

                # Broadcast val metrics to all ranks for early stopping decisions
                if ddp_enabled:
                    bcast_vals = [val_loss, val_acc, val_auc]
                    dist.broadcast_object_list(bcast_vals, src=0)
                    val_loss, val_acc, val_auc = bcast_vals

                elapsed = time.time() - t0
                lr_h = _get_lr_by_label(optimizer, "head")
                lr_b = _get_lr_by_label(optimizer, "backbone")

                log(f"  Epoch {epoch + 1:2d}/{args.epochs} ({elapsed:.0f}s) | "
                    f"Train loss={train_loss:.4f} acc={train_acc:.3f} | "
                    f"Val loss={val_loss:.4f} acc={val_acc:.3f} AUC={val_auc:.4f} | "
                    f"LR_Head={lr_h:.1e} LR_Back={lr_b:.1e}")

                if val_auc > best_auc:
                    best_auc = val_auc
                    if is_main_process():
                        best_probs = gathered_probs.copy()
                    patience_counter = 0
                    if ema:
                        ema.apply_shadow(raw_model)
                        best_state = _state_dict_to_cpu(raw_model)
                        ema.restore(raw_model)
                    else:
                        best_state = _state_dict_to_cpu(raw_model)
                    if is_main_process():
                        ckpt_path = ckpt_dir / f"{ckpt_stem}_fold{fold + 1}_best.pt"
                        meta = {**ckpt_meta, "fold": fold + 1, "epoch": epoch + 1,
                                "val_auc": val_auc}
                        if save_checkpoint(best_state, ckpt_path, meta):
                            _tracker.last_saved_path = str(ckpt_path)
                else:
                    patience_counter += 1
                    if patience_counter >= args.patience:
                        stopped_epoch = epoch + 1
                        log(f"  Early stopping at epoch {stopped_epoch}")
                        break

            fold_stopped.append(stopped_epoch)

            # --- TTA: rank 0 only ---
            tta_improved = False
            tta_auc_val = -1.0
            tta_probs_result = None

            if args.tta and best_state is not None:
                if is_main_process():
                    raw_model_eval = raw_model.module if hasattr(raw_model, 'module') else raw_model
                    raw_model_eval.load_state_dict(best_state)
                    raw_model_eval = raw_model_eval.to(device)
                    tta_probs_result, tta_auc_val = evaluate_tta(
                        raw_model_eval, val_df, img_dir, args.size, model_mean,
                        model_std, device, args.batch_size, args.workers)
                    tta_improved = tta_auc_val > best_auc

                if ddp_enabled:
                    bcast = [tta_improved, tta_auc_val]
                    dist.broadcast_object_list(bcast, src=0)
                    tta_improved, tta_auc_val = bcast

                if tta_improved:
                    log(f"  TTA improved AUC: {best_auc:.4f} -> {tta_auc_val:.4f}")
                    best_auc = tta_auc_val
                    if is_main_process() and tta_probs_result is not None:
                        best_probs = tta_probs_result.copy()
                else:
                    log(f"  TTA AUC: {tta_auc_val:.4f} (no improvement over {best_auc:.4f})")

            # Write OOF predictions (rank 0 only, probs are in correct order)
            if is_main_process() and best_probs is not None:
                all_val_probs[val_idx] = best_probs

            fold_aucs.append(best_auc)
            log(f"  Best Val AUC: {best_auc:.4f} (stopped at epoch {stopped_epoch})")

            # Cleanup
            del model, raw_model, ema, optimizer, scaler
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            if ddp_enabled:
                dist.barrier()

        # --- CV Summary (rank 0 only) ---
        if is_main_process():
            overall_auc = roc_auc_score(df["label"].values, all_val_probs)
            overall_preds = (all_val_probs >= 0.5).astype(int)
            log(f"\n{'=' * 60}")
            log(f"Cross-Validation Results")
            log(f"{'=' * 60}")
            log(f"Fold AUCs:    {[f'{a:.4f}' for a in fold_aucs]}")
            log(f"Fold stopped: {fold_stopped}")
            log(f"Mean AUC:     {np.mean(fold_aucs):.4f} +/- {np.std(fold_aucs):.4f}")
            log(f"Overall AUC:  {overall_auc:.4f}")
            log(classification_report(df["label"].values, overall_preds,
                                      target_names=["disliked", "liked"],
                                      zero_division=0))

            for t in np.arange(0.30, 0.70, 0.01):
                preds_t = (all_val_probs >= t).astype(int)
                tp = ((preds_t == 1) & (df["label"].values == 1)).sum()
                fp = ((preds_t == 1) & (df["label"].values == 0)).sum()
                fn = ((preds_t == 0) & (df["label"].values == 1)).sum()
                prec = tp / max(tp + fp, 1)
                rec = tp / max(tp + fn, 1)
                f1 = 2 * prec * rec / max(prec + rec, 1e-8)
                if f1 > best_f1:
                    best_f1, best_threshold = f1, t
            log(f"Optimal threshold: {best_threshold:.2f} (F1={best_f1:.4f})")

        # Broadcast CV-derived values to all ranks
        avg_stop = int(np.mean(fold_stopped))
        final_epochs = min(avg_stop + 2, args.epochs)

        if ddp_enabled:
            bcast = [final_epochs, best_threshold, overall_auc]
            dist.broadcast_object_list(bcast, src=0)
            final_epochs, best_threshold, overall_auc = bcast
    else:
        log(f"\nSkipping cross-validation (--no-cv). Training directly on all data.")

    # ===================================================================
    # Final model: train on ALL data (all GPUs)
    # ===================================================================
    log(f"\nTraining final model on ALL data for {final_epochs} epochs...")

    full_ds = PreferenceDataset(
        df, img_dir, get_transforms(True, args.size, model_mean, model_std))
    full_sampler = DistributedSampler(full_ds, shuffle=True) if ddp_enabled else None
    full_loader = DataLoader(
        full_ds, batch_size=args.batch_size,
        shuffle=(full_sampler is None), sampler=full_sampler,
        num_workers=args.workers, pin_memory=True, drop_last=True,
        persistent_workers=args.workers > 0)

    model = create_model(args.model, unfreeze_stages=args.unfreeze, dropout=args.dropout)
    model = model.to(device)
    raw_model = model
    ema = EMA(raw_model, decay=args.ema_decay) if args.ema_decay > 0 else None

    if ddp_enabled:
        model = DDP(model, device_ids=[local_rank], find_unused_parameters=False)

    n_pos = df["label"].sum()
    n_neg = len(df) - n_pos
    pos_weight = torch.tensor([n_neg / max(n_pos, 1)], device=device)
    criterion = (LabelSmoothingBCEWithLogitsLoss(args.label_smoothing, pos_weight)
                 if args.label_smoothing > 0
                 else nn.BCEWithLogitsLoss(pos_weight=pos_weight))

    param_groups = get_parameter_groups(raw_model, args.lr_head, args.lr_backbone,
                                        args.weight_decay)
    optimizer = torch.optim.AdamW(param_groups)
    scheduler = WarmupCosineScheduler(optimizer, args.warmup_epochs, final_epochs)
    scaler = torch.amp.GradScaler('cuda') if device.type == "cuda" else None

    for epoch in range(final_epochs):
        if full_sampler is not None:
            full_sampler.set_epoch(epoch)

        t0 = time.time()
        scheduler.step(epoch)
        train_loss, train_acc = train_one_epoch(
            model, full_loader, criterion, optimizer, device, scaler,
            args.mixup_alpha, args.cutmix_alpha, args.mix_prob,
            ema=ema, raw_model=raw_model)

        lr_now = optimizer.param_groups[0]['lr']
        log(f"  Epoch {epoch + 1:2d}/{final_epochs} ({time.time() - t0:.0f}s) | "
            f"loss={train_loss:.4f} acc={train_acc:.3f} | LR={lr_now:.2e}")

        # Periodic checkpoint saving
        cur_epoch = epoch + 1
        should_save = ((args.save_every > 0 and cur_epoch % args.save_every == 0)
                       or cur_epoch == final_epochs)
        if should_save and is_main_process():
            if ema:
                ema.apply_shadow(raw_model)
                epoch_state = _state_dict_to_cpu(raw_model)
                ema.restore(raw_model)
            else:
                epoch_state = _state_dict_to_cpu(raw_model)

            ckpt_path = ckpt_dir / f"{ckpt_stem}_epoch{cur_epoch}.pt"
            meta = {**ckpt_meta, "phase": "final", "epoch": cur_epoch,
                    "total_epochs": final_epochs}
            if save_checkpoint(epoch_state, ckpt_path, meta):
                _tracker.last_saved_path = str(ckpt_path)
                log(f"    Checkpoint saved: {ckpt_path}")

            latest_path = ckpt_dir / f"{ckpt_stem}_latest.pt"
            save_checkpoint(epoch_state, latest_path, meta)

            if args.save_last > 0:
                existing = sorted(glob.glob(str(ckpt_dir / f"{ckpt_stem}_epoch*.pt")))
                while len(existing) > args.save_last:
                    old = existing.pop(0)
                    try:
                        os.remove(old)
                        log(f"    Removed old checkpoint: {old}")
                    except OSError:
                        pass

    # Apply EMA for final save
    if ema:
        ema.apply_shadow(raw_model)

    # --- Save final model (rank 0 only, atomic write) ---
    if is_main_process():
        output_path = Path(args.output)
        final_state = _state_dict_to_cpu(raw_model)
        save_dict = {
            "model_state_dict": final_state,
            "model_name": args.model,
            "model_class": "PreferenceModel",
            "num_classes": 1,
            "num_features": raw_model.backbone.num_features,
            "head_hidden_dim": 256,
            "unfreeze_stages": args.unfreeze,
            "dropout": args.dropout,
            "input_size": args.size,
            "optimal_threshold": float(best_threshold),
            "cv_auc": float(overall_auc) if overall_auc > 0 else None,
            "fold_aucs": fold_aucs if fold_aucs else None,
            "fold_stopped_epochs": fold_stopped if fold_stopped else None,
            "final_epochs_trained": final_epochs,
            "n_samples": len(df),
            "n_liked": int(df["label"].sum()),
            "n_disliked": int((1 - df["label"]).sum()),
            "normalize_mean": list(model_mean),
            "normalize_std": list(model_std),
            "hyperparameters": vars(args),
        }
        # Use atomic save
        tmp_path = str(output_path) + ".tmp"
        try:
            torch.save(save_dict, tmp_path)
            os.replace(tmp_path, output_path)
        except Exception:
            torch.save(save_dict, output_path)

        sz = output_path.stat().st_size / 1024**2
        log(f"\nModel saved to {output_path} ({sz:.1f} MB)")
        if overall_auc > 0:
            log(f"CV AUC: {overall_auc:.4f}")
        log(f"Optimal threshold: {best_threshold:.2f}")

    cleanup_ddp()


if __name__ == "__main__":
    main()