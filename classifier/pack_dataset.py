#!/usr/bin/env python3
"""
Package preference classifier dataset for GPU training.
Resizes images to 384px (longer edge) to reduce transfer size while keeping enough quality for 224 training.
Output: preference_train.tar.gz with images/ + manifest.csv + train.py + requirements.txt
"""

import csv
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

from PIL import Image

_PROJECT_ROOT = Path(__file__).parent.parent

# Load .env if available
try:
    from dotenv import load_dotenv
    load_dotenv(_PROJECT_ROOT / ".env")
except ImportError:
    pass

def _env_path(key, default):
    val = os.environ.get(key, default)
    p = Path(val)
    return p if p.is_absolute() else _PROJECT_ROOT / p

CRAWLER_DIR = _env_path("CRAWLER_DIR", "")
LABELS_DB = _env_path("LABELS_DB", "backend/labels.db")
DEDUP_DB = CRAWLER_DIR / "dedup.db"
TWITTER_DIR = Path(os.environ.get("TWITTER_DIR", ""))
DANBOORU_LABELS_DB = _PROJECT_ROOT / "backend" / "danbooru_labels.db"
DANBOORU_LIKES_DIR = _env_path("DANBOORU_LIKES_DIR", "data/danbooru_liked")
OUT_DIR = _PROJECT_ROOT / "classifier" / "_tmp_pack"
ARCHIVE = _PROJECT_ROOT / "classifier" / "preference_train.tar.gz"
MAX_SIZE = 384  # longer edge


def resize_and_save(src: str, dst: str):
    """Resize image preserving aspect ratio, save as JPEG."""
    try:
        img = Image.open(src)
        img = img.convert("RGB")
        w, h = img.size
        if max(w, h) > MAX_SIZE:
            ratio = MAX_SIZE / max(w, h)
            img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)
        img.save(dst, "JPEG", quality=85)
        return True
    except Exception as e:
        print(f"  SKIP {src}: {e}")
        return False


def main():
    # Clean
    if OUT_DIR.exists():
        shutil.rmtree(OUT_DIR)
    (OUT_DIR / "images").mkdir(parents=True)

    manifest = []

    # --- Booru data ---
    print("Loading booru labels...")
    conn_l = sqlite3.connect(str(LABELS_DB))
    cur_l = conn_l.cursor()
    cur_l.execute('SELECT image_id, verdict FROM labels WHERE verdict IN ("liked", "disliked")')
    labels = {r[0]: r[1] for r in cur_l.fetchall()}
    conn_l.close()

    conn_d = sqlite3.connect(str(DEDUP_DB))
    cur_d = conn_d.cursor()
    ids = list(labels.keys())
    placeholders = ",".join("?" * len(ids))
    cur_d.execute(f"SELECT id, file_path FROM images WHERE id IN ({placeholders})", ids)
    booru_rows = cur_d.fetchall()
    conn_d.close()

    print(f"Booru: {len(booru_rows)} images ({sum(1 for v in labels.values() if v=='liked')} liked, {sum(1 for v in labels.values() if v=='disliked')} disliked)")

    # --- Twitter data ---
    twitter_files = sorted([
        f for f in TWITTER_DIR.iterdir()
        if f.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp", ".gif")
    ])
    print(f"Twitter: {len(twitter_files)} images (all liked)")

    # --- Danbooru (DanbooruFinder) labeled data ---
    danbooru_labels = {}
    if DANBOORU_LABELS_DB.exists():
        conn_dl = sqlite3.connect(str(DANBOORU_LABELS_DB))
        cur_dl = conn_dl.cursor()
        cur_dl.execute('SELECT image_id, ext, verdict FROM labels WHERE verdict IN ("liked", "disliked")')
        for row in cur_dl.fetchall():
            danbooru_labels[row[0]] = (row[1], row[2])
        conn_dl.close()
        n_liked = sum(1 for v in danbooru_labels.values() if v[1] == 'liked')
        n_disliked = sum(1 for v in danbooru_labels.values() if v[1] == 'disliked')
        print(f"Danbooru: {len(danbooru_labels)} images ({n_liked} liked, {n_disliked} disliked)")
    else:
        print("Danbooru labels DB not found, skipping")

    # --- Resolve Danbooru image paths ---
    # Liked images are saved in DANBOORU_LIKES_DIR
    # Disliked images: check /tmp/danbooru_disliked/ (pre-downloaded)
    DANBOORU_DISLIKED_DIR = Path(os.environ.get("DANBOORU_DISLIKED_DIR", "/tmp/danbooru_disliked"))
    danbooru_tasks = []
    danbooru_found = 0
    danbooru_missing = 0
    for img_id, (ext, verdict) in danbooru_labels.items():
        label = 1 if verdict == "liked" else 0
        if verdict == "liked":
            src = DANBOORU_LIKES_DIR / f"{img_id}.{ext}"
        else:
            src = DANBOORU_DISLIKED_DIR / f"{img_id}.{ext}"
        if src.exists() and src.stat().st_size > 100:
            danbooru_tasks.append((str(src), img_id, ext, label))
            danbooru_found += 1
        else:
            danbooru_missing += 1
    n_dl = sum(1 for _, _, _, l in danbooru_tasks if l == 1)
    n_dd = sum(1 for _, _, _, l in danbooru_tasks if l == 0)
    print(f"Danbooru resolved: {danbooru_found} found ({n_dl} liked, {n_dd} disliked), {danbooru_missing} missing")

    # --- Process with thread pool ---
    tasks = []
    for img_id, fp in booru_rows:
        src = str(CRAWLER_DIR / fp)
        dst = str(OUT_DIR / "images" / f"booru_{img_id}.jpg")
        verdict = labels[img_id]
        tasks.append((src, dst, 1 if verdict == "liked" else 0, f"booru_{img_id}.jpg"))

    for tf in twitter_files:
        dst_name = f"twitter_{tf.stem}.jpg"
        dst = str(OUT_DIR / "images" / dst_name)
        tasks.append((str(tf), dst, 1, dst_name))

    for src, img_id, ext, label in danbooru_tasks:
        dst_name = f"danbooru_{img_id}.jpg"
        dst = str(OUT_DIR / "images" / dst_name)
        tasks.append((src, dst, label, dst_name))

    print(f"\nResizing {len(tasks)} images to {MAX_SIZE}px...")
    done = 0
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(resize_and_save, src, dst): (dst_name, label) for src, dst, label, dst_name in tasks}
        for fut in as_completed(futures):
            dst_name, label = futures[fut]
            if fut.result():
                manifest.append((dst_name, label))
                done += 1
            if done % 200 == 0:
                print(f"  {done}/{len(tasks)}")

    print(f"  Done: {done}/{len(tasks)}")

    # --- Write manifest ---
    manifest_path = OUT_DIR / "manifest.csv"
    with open(manifest_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["filename", "label"])
        for name, label in sorted(manifest):
            w.writerow([name, label])
    print(f"Manifest: {len(manifest)} entries")

    # --- Copy training script ---
    train_script = OUT_DIR / "train.py"
    train_script.write_text(TRAIN_SCRIPT)
    (OUT_DIR / "requirements.txt").write_text(REQUIREMENTS)
    print("Added train.py + requirements.txt")

    # --- Compress ---
    print(f"\nCompressing to {ARCHIVE}...")
    subprocess.run(
        ["tar", "czf", str(ARCHIVE), "-C", str(OUT_DIR.parent), OUT_DIR.name],
        check=True,
    )
    size_mb = ARCHIVE.stat().st_size / 1024 / 1024
    print(f"Archive: {size_mb:.0f} MB")
    print(f"\nDone! Transfer {ARCHIVE} to your GPU machine and run:")
    print(f"  tar xzf preference_train.tar.gz")
    print(f"  cd preference_train")
    print(f"  pip install -r requirements.txt")
    print(f"  python train.py")

    # Cleanup
    shutil.rmtree(OUT_DIR)


REQUIREMENTS = """\
torch>=2.0
torchvision>=0.15
timm>=0.9
pillow>=9.0
scikit-learn>=1.3
pandas
"""

TRAIN_SCRIPT = r'''#!/usr/bin/env python3
"""
Preference classifier CNN training script.
Fine-tunes ConvNeXt-Tiny on image preference data.

Usage:
    python train.py                      # default settings
    python train.py --epochs 10          # more epochs
    python train.py --model convnext_small.fb_in22k_ft_in1k  # larger model
    python train.py --unfreeze 2         # unfreeze last N backbone stages
"""

import argparse
import csv
import os
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader
from torchvision import transforms
from PIL import Image
from sklearn.model_selection import StratifiedKFold
from sklearn.metrics import classification_report, roc_auc_score

import timm


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
        img = Image.open(img_path).convert("RGB")
        if self.transform:
            img = self.transform(img)
        label = torch.tensor(row["label"], dtype=torch.float32)
        return img, label


def get_transforms(train=True, size=224):
    if train:
        return transforms.Compose([
            transforms.RandomResizedCrop(size, scale=(0.8, 1.0)),
            transforms.RandomHorizontalFlip(),
            transforms.ColorJitter(brightness=0.2, contrast=0.2, saturation=0.1),
            transforms.ToTensor(),
            transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
        ])
    else:
        return transforms.Compose([
            transforms.Resize(int(size * 1.14)),
            transforms.CenterCrop(size),
            transforms.ToTensor(),
            transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
        ])


def create_model(model_name, num_classes=1, unfreeze_stages=0):
    model = timm.create_model(model_name, pretrained=True, num_classes=num_classes)

    # Freeze backbone
    for param in model.parameters():
        param.requires_grad = False

    # Unfreeze classifier head
    if hasattr(model, 'head'):
        # timm ConvNeXt / EfficientNet style
        for param in model.head.parameters():
            param.requires_grad = True
    elif hasattr(model, 'classifier'):
        for param in model.classifier.parameters():
            param.requires_grad = True
    elif hasattr(model, 'fc'):
        for param in model.fc.parameters():
            param.requires_grad = True

    # Optionally unfreeze last N stages
    if unfreeze_stages > 0 and hasattr(model, 'stages'):
        stages = list(model.stages)
        for stage in stages[-unfreeze_stages:]:
            for param in stage.parameters():
                param.requires_grad = True

    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    total = sum(p.numel() for p in model.parameters())
    print(f"Model: {model_name}")
    print(f"  Total params: {total:,}")
    print(f"  Trainable:    {trainable:,} ({trainable/total*100:.1f}%)")

    return model


def train_one_epoch(model, loader, criterion, optimizer, device, scaler=None):
    model.train()
    total_loss = 0
    correct = 0
    total = 0

    for imgs, labels in loader:
        imgs, labels = imgs.to(device), labels.to(device)
        optimizer.zero_grad()

        if scaler:
            with torch.cuda.amp.autocast():
                outputs = model(imgs).squeeze(-1)
                loss = criterion(outputs, labels)
            scaler.scale(loss).backward()
            scaler.step(optimizer)
            scaler.update()
        else:
            outputs = model(imgs).squeeze(-1)
            loss = criterion(outputs, labels)
            loss.backward()
            optimizer.step()

        total_loss += loss.item() * len(labels)
        preds = (torch.sigmoid(outputs) >= 0.5).long()
        correct += (preds == labels.long()).sum().item()
        total += len(labels)

    return total_loss / total, correct / total


@torch.no_grad()
def evaluate(model, loader, criterion, device):
    model.eval()
    total_loss = 0
    all_probs = []
    all_labels = []

    for imgs, labels in loader:
        imgs, labels = imgs.to(device), labels.to(device)
        outputs = model(imgs).squeeze(-1)
        loss = criterion(outputs, labels)
        total_loss += loss.item() * len(labels)
        probs = torch.sigmoid(outputs).cpu().numpy()
        all_probs.extend(probs)
        all_labels.extend(labels.cpu().numpy())

    all_probs = np.array(all_probs)
    all_labels = np.array(all_labels)
    preds = (all_probs >= 0.5).astype(int)

    acc = (preds == all_labels).mean()
    auc = roc_auc_score(all_labels, all_probs) if len(set(all_labels)) > 1 else 0
    return total_loss / len(all_labels), acc, auc, all_probs, all_labels


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="convnext_tiny.fb_in22k_ft_in1k")
    parser.add_argument("--epochs", type=int, default=8)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--size", type=int, default=224)
    parser.add_argument("--unfreeze", type=int, default=0, help="Unfreeze last N backbone stages")
    parser.add_argument("--folds", type=int, default=5)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--data-dir", default=".")
    parser.add_argument("--output", default="model_cnn.pt")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    img_dir = data_dir / "images"
    manifest = data_dir / "manifest.csv"

    print(f"Loading manifest from {manifest}")
    df = pd.read_csv(manifest)
    print(f"Dataset: {len(df)} images, {df['label'].sum()} liked, {(1-df['label']).sum():.0f} disliked")

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Device: {device}")
    if device.type == "cuda":
        print(f"  GPU: {torch.cuda.get_device_name()}")
        print(f"  VRAM: {torch.cuda.get_device_properties(0).total_mem / 1024**3:.1f} GB")

    # --- Cross-validation ---
    skf = StratifiedKFold(n_splits=args.folds, shuffle=True, random_state=42)
    all_val_probs = np.zeros(len(df))
    fold_aucs = []

    for fold, (train_idx, val_idx) in enumerate(skf.split(df, df["label"])):
        print(f"\n{'='*60}")
        print(f"Fold {fold+1}/{args.folds}")
        print(f"{'='*60}")

        train_df = df.iloc[train_idx]
        val_df = df.iloc[val_idx]
        print(f"  Train: {len(train_df)} ({train_df['label'].sum()} liked)")
        print(f"  Val:   {len(val_df)} ({val_df['label'].sum()} liked)")

        train_ds = PreferenceDataset(train_df, img_dir, get_transforms(True, args.size))
        val_ds = PreferenceDataset(val_df, img_dir, get_transforms(False, args.size))
        train_loader = DataLoader(train_ds, batch_size=args.batch_size, shuffle=True, num_workers=args.workers, pin_memory=True)
        val_loader = DataLoader(val_ds, batch_size=args.batch_size, shuffle=False, num_workers=args.workers, pin_memory=True)

        model = create_model(args.model, num_classes=1, unfreeze_stages=args.unfreeze)
        model = model.to(device)

        # Handle class imbalance
        n_pos = train_df["label"].sum()
        n_neg = len(train_df) - n_pos
        pos_weight = torch.tensor([n_neg / max(n_pos, 1)], device=device)
        criterion = nn.BCEWithLogitsLoss(pos_weight=pos_weight)

        optimizer = torch.optim.AdamW(
            filter(lambda p: p.requires_grad, model.parameters()),
            lr=args.lr, weight_decay=0.01,
        )
        scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=args.epochs)
        scaler = torch.cuda.amp.GradScaler() if device.type == "cuda" else None

        best_auc = 0
        for epoch in range(args.epochs):
            t0 = time.time()
            train_loss, train_acc = train_one_epoch(model, train_loader, criterion, optimizer, device, scaler)
            val_loss, val_acc, val_auc, val_probs, val_labels = evaluate(model, val_loader, criterion, device)
            scheduler.step()
            elapsed = time.time() - t0

            print(f"  Epoch {epoch+1:2d}/{args.epochs} ({elapsed:.0f}s) | "
                  f"Train loss={train_loss:.4f} acc={train_acc:.3f} | "
                  f"Val loss={val_loss:.4f} acc={val_acc:.3f} AUC={val_auc:.4f}")

            if val_auc > best_auc:
                best_auc = val_auc
                best_probs = val_probs

        all_val_probs[val_idx] = best_probs
        fold_aucs.append(best_auc)
        print(f"  Best Val AUC: {best_auc:.4f}")

    # --- Overall CV results ---
    overall_auc = roc_auc_score(df["label"].values, all_val_probs)
    overall_preds = (all_val_probs >= 0.5).astype(int)
    print(f"\n{'='*60}")
    print(f"Cross-Validation Results")
    print(f"{'='*60}")
    print(f"Fold AUCs: {[f'{a:.4f}' for a in fold_aucs]}")
    print(f"Mean AUC:  {np.mean(fold_aucs):.4f} ± {np.std(fold_aucs):.4f}")
    print(f"Overall AUC: {overall_auc:.4f}")
    print(classification_report(df["label"].values, overall_preds, target_names=["disliked", "liked"]))

    # --- Train final model on all data ---
    print(f"\nTraining final model on all data...")
    full_ds = PreferenceDataset(df, img_dir, get_transforms(True, args.size))
    full_loader = DataLoader(full_ds, batch_size=args.batch_size, shuffle=True, num_workers=args.workers, pin_memory=True)

    model = create_model(args.model, num_classes=1, unfreeze_stages=args.unfreeze)
    model = model.to(device)

    n_pos = df["label"].sum()
    n_neg = len(df) - n_pos
    pos_weight = torch.tensor([n_neg / max(n_pos, 1)], device=device)
    criterion = nn.BCEWithLogitsLoss(pos_weight=pos_weight)
    optimizer = torch.optim.AdamW(
        filter(lambda p: p.requires_grad, model.parameters()),
        lr=args.lr, weight_decay=0.01,
    )
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=args.epochs)
    scaler = torch.cuda.amp.GradScaler() if device.type == "cuda" else None

    for epoch in range(args.epochs):
        t0 = time.time()
        train_loss, train_acc = train_one_epoch(model, full_loader, criterion, optimizer, device, scaler)
        scheduler.step()
        print(f"  Epoch {epoch+1:2d}/{args.epochs} ({time.time()-t0:.0f}s) | loss={train_loss:.4f} acc={train_acc:.3f}")

    # --- Save ---
    output_path = Path(args.output)
    save_dict = {
        "model_state_dict": model.cpu().state_dict(),
        "model_name": args.model,
        "num_classes": 1,
        "unfreeze_stages": args.unfreeze,
        "input_size": args.size,
        "cv_auc": overall_auc,
        "fold_aucs": fold_aucs,
        "n_samples": len(df),
        "n_liked": int(df["label"].sum()),
        "n_disliked": int((1 - df["label"]).sum()),
        "normalize_mean": [0.485, 0.456, 0.406],
        "normalize_std": [0.229, 0.224, 0.225],
    }
    torch.save(save_dict, output_path)
    print(f"\nModel saved to {output_path} ({output_path.stat().st_size / 1024 / 1024:.1f} MB)")
    print(f"CV AUC: {overall_auc:.4f}")
    print(f"\nDone! Upload {output_path} back to your server.")


if __name__ == "__main__":
    main()
'''


if __name__ == "__main__":
    main()
