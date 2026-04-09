#!/usr/bin/env python3
"""
Package preference classifier dataset for GPU training.

Supports two input modes:
  1. Folder-based (universal):
       python pack_dataset.py --liked ~/liked_imgs --disliked ~/disliked_imgs
       python pack_dataset.py --data-dir ~/data  (expects liked/ + disliked/ subdirs)

  2. DB-based (Sieve-specific, activated by env vars or flags):
       Reads from labels.db, dedup.db, twitter dir, danbooru labels etc.
       Configure via .env or environment variables.

Output: preference_train.tar.gz with images/ + manifest.csv + train.py + requirements.txt
"""

import argparse
import csv
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from PIL import Image

Image.MAX_IMAGE_PIXELS = None  # allow large images (some booru images exceed default limit)

_PROJECT_ROOT = Path(__file__).parent.parent

# Load .env if available
try:
    from dotenv import load_dotenv
    load_dotenv(_PROJECT_ROOT / ".env")
except ImportError:
    pass

DEFAULT_MAX_SIZE = 1024
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tiff"}
VIDEO_EXTS = {".mp4", ".webm", ".avi", ".mov", ".mkv", ".flv"}


def _env_path(key, default):
    val = os.environ.get(key, default)
    if not val:
        return None
    p = Path(val)
    return p if p.is_absolute() else _PROJECT_ROOT / p


def resize_and_save(src: str, dst: str, max_size: int):
    """Resize image preserving aspect ratio, save as JPEG. max_size=0 means raw copy."""
    # Pre-check: skip videos that slipped through
    if is_video(src):
        print(f"  SKIP (video) {src}")
        return False
    if max_size == 0:
        # Original resolution: raw copy, no re-encoding
        try:
            shutil.copy2(src, dst)
            return True
        except Exception as e:
            print(f"  SKIP (copy) {Path(src).name}: {e}")
            return False
    try:
        img = Image.open(src)
        img.load()  # force full decode to catch truncated files early
        img = img.convert("RGB")
        w, h = img.size
        if max(w, h) > max_size:
            ratio = max_size / max(w, h)
            img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)
        img.save(dst, "JPEG", quality=85)
        return True
    except Exception as e:
        ext = Path(src).suffix.lower()
        reason = "corrupt/truncated" if "identify" in str(e) or "truncated" in str(e) else str(e)
        print(f"  SKIP ({ext}) {Path(src).name}: {reason}")
        return False


# ---------------------------------------------------------------------------
# Incremental cache
# ---------------------------------------------------------------------------

class ResizeCache:
    """Persistent cache for resized images. Tracks source mtime+size to detect changes."""

    def __init__(self, cache_dir: Path, max_size: int):
        self.cache_dir = cache_dir
        self.images_dir = cache_dir / "images"
        self.images_dir.mkdir(parents=True, exist_ok=True)
        self.max_size = max_size
        self.db_path = cache_dir / "cache_index.db"
        self._init_db()

    def _init_db(self):
        self.conn = sqlite3.connect(str(self.db_path), timeout=30)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=30000")
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS cache (
                dest_name TEXT PRIMARY KEY,
                src_path TEXT,
                src_mtime REAL,
                src_size INTEGER,
                max_size INTEGER
            )
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS failed (
                dest_name TEXT PRIMARY KEY,
                src_path TEXT,
                src_mtime REAL,
                src_size INTEGER
            )
        """)
        self.conn.commit()

    def is_cached(self, src: str, dest_name: str) -> bool:
        """Check if source file is already cached and unchanged."""
        try:
            st = os.stat(src)
        except OSError:
            return False
        row = self.conn.execute(
            "SELECT src_mtime, src_size, max_size FROM cache WHERE dest_name = ?",
            (dest_name,),
        ).fetchone()
        if row is None:
            return False
        cached_mtime, cached_size, cached_max = row
        # Check source unchanged AND cached file still exists
        if cached_mtime == st.st_mtime and cached_size == st.st_size and cached_max == self.max_size:
            return (self.images_dir / dest_name).exists()
        return False

    def is_known_failed(self, src: str, dest_name: str) -> bool:
        """Check if this source was previously known to fail."""
        try:
            st = os.stat(src)
        except OSError:
            return True  # file gone = effectively failed
        row = self.conn.execute(
            "SELECT src_mtime, src_size FROM failed WHERE dest_name = ?",
            (dest_name,),
        ).fetchone()
        if row and row[0] == st.st_mtime and row[1] == st.st_size:
            return True
        return False

    def record(self, src: str, dest_name: str):
        """Record a successfully cached file."""
        try:
            st = os.stat(src)
            self.conn.execute(
                "INSERT OR REPLACE INTO cache VALUES (?, ?, ?, ?, ?)",
                (dest_name, src, st.st_mtime, st.st_size, self.max_size),
            )
            self.conn.execute("DELETE FROM failed WHERE dest_name = ?", (dest_name,))
        except OSError:
            pass

    def record_failed(self, src: str, dest_name: str):
        """Record a file that failed to resize."""
        try:
            st = os.stat(src)
            self.conn.execute(
                "INSERT OR REPLACE INTO failed VALUES (?, ?, ?, ?)",
                (dest_name, src, st.st_mtime, st.st_size),
            )
        except OSError:
            pass

    def commit(self):
        self.conn.commit()

    def prune(self, valid_names: set[str]):
        """Remove cache entries not in valid_names (deleted/relabeled images)."""
        all_cached = {r[0] for r in self.conn.execute("SELECT dest_name FROM cache").fetchall()}
        stale = all_cached - valid_names
        if stale:
            for name in stale:
                cached_file = self.images_dir / name
                if cached_file.exists():
                    cached_file.unlink()
            ph = ",".join("?" * len(stale))
            self.conn.execute(f"DELETE FROM cache WHERE dest_name IN ({ph})", list(stale))
            self.conn.commit()
            print(f"  Pruned {len(stale)} stale cache entries")

    def close(self):
        self.conn.close()


def is_image(filename: str) -> bool:
    return Path(filename).suffix.lower() in IMAGE_EXTS


def is_video(filename: str) -> bool:
    return Path(filename).suffix.lower() in VIDEO_EXTS


# ---------------------------------------------------------------------------
# Data source: folders
# ---------------------------------------------------------------------------

def collect_from_folders(liked_dirs: list[Path], disliked_dirs: list[Path]) -> list[tuple]:
    """Collect (source_path, dest_name, label) from liked/disliked directories."""
    tasks = []
    seen_names = set()

    def _add_dir(directory: Path, label: int, prefix: str):
        if not directory.is_dir():
            print(f"  Warning: {directory} not found, skipping")
            return 0
        count = 0
        for f in sorted(directory.iterdir()):
            if f.is_file() and is_image(f.name):
                # Ensure unique dest names
                stem = f.stem
                name = f"{prefix}_{stem}.jpg"
                if name in seen_names:
                    i = 1
                    while f"{prefix}_{stem}_{i}.jpg" in seen_names:
                        i += 1
                    name = f"{prefix}_{stem}_{i}.jpg"
                seen_names.add(name)
                tasks.append((str(f), name, label))
                count += 1
        return count

    for i, d in enumerate(liked_dirs):
        prefix = f"liked{i}" if len(liked_dirs) > 1 else "liked"
        n = _add_dir(d, 1, prefix)
        print(f"  Liked dir {d}: {n} images")

    for i, d in enumerate(disliked_dirs):
        prefix = f"disliked{i}" if len(disliked_dirs) > 1 else "disliked"
        n = _add_dir(d, 0, prefix)
        print(f"  Disliked dir {d}: {n} images")

    return tasks


# ---------------------------------------------------------------------------
# Data source: Sieve databases (optional)
# ---------------------------------------------------------------------------

def collect_from_sieve_dbs() -> list[tuple]:
    """Collect from Sieve's label DB + crawler DB + Twitter + Danbooru.
    Returns empty list if required DBs are not configured."""
    tasks = []

    # --- Booru crawler data ---
    labels_db = _env_path("LABELS_DB", "backend/labels.db")
    crawler_dir = _env_path("CRAWLER_DIR", "")

    if labels_db and labels_db.exists() and crawler_dir and crawler_dir.exists():
        dedup_db = crawler_dir / "dedup.db"
        if dedup_db.exists():
            conn_l = sqlite3.connect(str(labels_db))
            cur = conn_l.cursor()
            cur.execute('SELECT image_id, verdict FROM labels WHERE verdict IN ("liked", "disliked")')
            labels = {r[0]: r[1] for r in cur.fetchall()}
            conn_l.close()

            conn_d = sqlite3.connect(str(dedup_db))
            cur = conn_d.cursor()
            ids = list(labels.keys())
            if ids:
                ph = ",".join("?" * len(ids))
                cur.execute(f"SELECT id, file_path FROM images WHERE id IN ({ph})", ids)
                n_skipped_video = 0
                for img_id, fp in cur.fetchall():
                    if is_video(fp):
                        n_skipped_video += 1
                        continue
                    src = str(crawler_dir / fp)
                    label = 1 if labels[img_id] == "liked" else 0
                    tasks.append((src, f"booru_{img_id}.jpg", label))
            conn_d.close()
            n_liked = sum(1 for t in tasks if t[2] == 1)
            n_disliked = sum(1 for t in tasks if t[2] == 0)
            msg = f"  Booru: {len(tasks)} ({n_liked} liked, {n_disliked} disliked)"
            if n_skipped_video:
                msg += f", {n_skipped_video} videos skipped"
            print(msg)

    # --- Twitter data ---
    twitter_dir = os.environ.get("TWITTER_DIR", "")
    if twitter_dir and Path(twitter_dir).is_dir():
        count = 0
        for f in sorted(Path(twitter_dir).iterdir()):
            if f.is_file() and is_image(f.name):
                tasks.append((str(f), f"twitter_{f.stem}.jpg", 1))
                count += 1
        if count:
            print(f"  Twitter: {count} images (all liked)")

    # --- Danbooru labeled data ---
    danbooru_labels_db = _PROJECT_ROOT / "backend" / "danbooru_labels.db"
    danbooru_likes_dir = _env_path("DANBOORU_LIKES_DIR", "data/danbooru_liked")
    danbooru_disliked_dir = Path(os.environ.get("DANBOORU_DISLIKED_DIR", "/tmp/danbooru_disliked"))
    danbooru_api = os.environ.get("DANBOORU_API", "")

    if danbooru_labels_db.exists():
        conn = sqlite3.connect(str(danbooru_labels_db))
        cur = conn.cursor()
        cur.execute('SELECT image_id, ext, verdict FROM labels WHERE verdict IN ("liked", "disliked")')
        n_liked = n_disliked = n_missing = n_video = 0
        need_download: list[tuple[int, str, int]] = []  # (img_id, ext, label)
        for img_id, ext, verdict in cur.fetchall():
            if ext and f".{ext}" in VIDEO_EXTS:
                n_video += 1
                continue
            label = 1 if verdict == "liked" else 0
            # Try local files first
            local_path = None
            if verdict == "liked" and danbooru_likes_dir:
                lp = danbooru_likes_dir / f"{img_id}.{ext}"
                if lp.exists() and lp.stat().st_size > 100:
                    local_path = str(lp)
            if local_path is None and danbooru_disliked_dir:
                lp = danbooru_disliked_dir / f"{img_id}.{ext}"
                if lp.exists() and lp.stat().st_size > 100:
                    local_path = str(lp)
            if local_path:
                tasks.append((local_path, f"danbooru_{img_id}.jpg", label))
                if label == 1:
                    n_liked += 1
                else:
                    n_disliked += 1
            else:
                need_download.append((img_id, ext or "jpg", label))
        conn.close()

        # Download missing images from DanbooruFinder API
        if need_download and danbooru_api:
            os.makedirs(str(danbooru_disliked_dir), exist_ok=True)
            print(f"  Danbooru: downloading {len(need_download)} missing images from API...")
            n_downloaded = 0
            n_dl_fail = 0
            try:
                import requests
                # Clear proxy env vars to avoid routing internal requests through proxy
                sess = requests.Session()
                sess.trust_env = False  # ignore *_PROXY env vars
                for i, (img_id, ext, label) in enumerate(need_download):
                    out_path = danbooru_disliked_dir / f"{img_id}.{ext}"
                    # Skip if already downloaded successfully
                    if out_path.exists() and out_path.stat().st_size > 100:
                        tasks.append((str(out_path), f"danbooru_{img_id}.jpg", label))
                        if label == 1:
                            n_liked += 1
                        else:
                            n_disliked += 1
                        n_downloaded += 1
                        continue
                    # Remove stale empty files from previous failed runs
                    if out_path.exists() and out_path.stat().st_size <= 100:
                        out_path.unlink(missing_ok=True)
                    try:
                        resp = sess.get(f"{danbooru_api}/preview/{img_id}.{ext}", timeout=30)
                        if resp.status_code == 200 and len(resp.content) > 100:
                            out_path.write_bytes(resp.content)
                            # Verify write succeeded
                            if out_path.exists() and out_path.stat().st_size > 100:
                                tasks.append((str(out_path), f"danbooru_{img_id}.jpg", label))
                                if label == 1:
                                    n_liked += 1
                                else:
                                    n_disliked += 1
                                n_downloaded += 1
                            else:
                                out_path.unlink(missing_ok=True)
                                n_dl_fail += 1
                        else:
                            n_dl_fail += 1
                    except OSError as e:
                        # Disk full or write error - clean up and abort
                        out_path.unlink(missing_ok=True)
                        print(f"  Disk error, aborting downloads: {e}")
                        n_dl_fail += len(need_download) - i
                        break
                    except Exception:
                        out_path.unlink(missing_ok=True)
                        n_dl_fail += 1
                    if (i + 1) % 200 == 0:
                        print(f"    {i + 1}/{len(need_download)} downloaded...")
                sess.close()
            except ImportError:
                print("  Warning: requests not installed, cannot download missing images")
                n_dl_fail = len(need_download)
            n_missing = n_dl_fail
            print(f"  Danbooru: downloaded {n_downloaded}, failed {n_dl_fail}")
        elif need_download:
            n_missing = len(need_download)

        if n_liked + n_disliked > 0:
            msg = f"  Danbooru: {n_liked + n_disliked} ({n_liked} liked, {n_disliked} disliked, {n_missing} missing)"
            if n_video:
                msg += f", {n_video} videos skipped"
            print(msg)

    return tasks


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Pack image preference dataset for training",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  # From liked/disliked folders:
  python pack_dataset.py --liked ~/liked --disliked ~/disliked

  # From a data directory with liked/ and disliked/ subdirs:
  python pack_dataset.py --data-dir ~/preference_data

  # Multiple source directories:
  python pack_dataset.py --liked ~/pixiv_fav ~/twitter_fav --disliked ~/disliked

  # Include Sieve DB sources (requires configured .env):
  python pack_dataset.py --liked ~/extra_liked --include-db

  # DB-only mode (Sieve users):
  python pack_dataset.py --include-db
""",
    )
    parser.add_argument("--liked", nargs="*", type=Path, help="Directories of liked images")
    parser.add_argument("--disliked", nargs="*", type=Path, help="Directories of disliked images")
    parser.add_argument("--data-dir", type=Path, help="Directory with liked/ and disliked/ subdirs")
    parser.add_argument("--include-db", action="store_true",
                        help="Also include images from Sieve databases (labels.db, twitter, danbooru)")
    parser.add_argument("--max-size", type=int, default=DEFAULT_MAX_SIZE,
                        help=f"Resize longer edge to this (default: {DEFAULT_MAX_SIZE})")
    parser.add_argument("--output", type=Path, default=None,
                        help="Output archive path (default: classifier/preference_train.tar.gz)")
    parser.add_argument("--workers", type=int, default=8, help="Parallel resize workers")
    parser.add_argument("--no-train-script", action="store_true", help="Don't bundle train.py")
    parser.add_argument("--cache-dir", type=Path, default=None,
                        help="Persistent cache dir for resized images (default: classifier/_resize_cache)")
    parser.add_argument("--no-cache", action="store_true", help="Force full rebuild, ignore cache")
    args = parser.parse_args()

    # Determine output path
    archive = args.output or (_PROJECT_ROOT / "classifier" / "preference_train.tar.gz")
    out_dir = archive.parent / "_tmp_pack"

    # Collect tasks from all sources
    all_tasks = []  # [(src_path, dest_name, label), ...]

    # Folder-based sources
    liked_dirs = list(args.liked or [])
    disliked_dirs = list(args.disliked or [])

    if args.data_dir:
        d = args.data_dir
        if (d / "liked").is_dir():
            liked_dirs.append(d / "liked")
        if (d / "disliked").is_dir():
            disliked_dirs.append(d / "disliked")
        if not (d / "liked").is_dir() and not (d / "disliked").is_dir():
            print(f"Error: --data-dir {d} has no liked/ or disliked/ subdirectory")
            sys.exit(1)

    if liked_dirs or disliked_dirs:
        print("Collecting from directories...")
        all_tasks.extend(collect_from_folders(liked_dirs, disliked_dirs))

    # DB-based sources (opt-in or fallback when no folders given)
    if args.include_db or (not liked_dirs and not disliked_dirs):
        if not liked_dirs and not disliked_dirs and not args.include_db:
            # Auto-detect: try DB sources
            print("No directories specified, trying Sieve database sources...")
        else:
            print("Including Sieve database sources...")
        db_tasks = collect_from_sieve_dbs()
        if db_tasks:
            all_tasks.extend(db_tasks)
        elif not liked_dirs and not disliked_dirs:
            print("\nNo data sources found. Use --liked/--disliked or --data-dir to specify image directories.")
            print("See --help for examples.")
            sys.exit(1)

    n_liked = sum(1 for t in all_tasks if t[2] == 1)
    n_disliked = sum(1 for t in all_tasks if t[2] == 0)
    print(f"\nTotal: {len(all_tasks)} images ({n_liked} liked, {n_disliked} disliked)")

    if len(all_tasks) == 0:
        print("No images found, nothing to pack.")
        sys.exit(1)

    # Incremental cache setup
    cache_dir = args.cache_dir or (archive.parent / "_resize_cache")
    use_cache = not args.no_cache

    if args.no_cache and cache_dir.exists():
        shutil.rmtree(cache_dir)

    cache = ResizeCache(cache_dir, args.max_size) if use_cache else None

    # Resize images (incremental: skip already-cached)
    print(f"Resizing to {args.max_size}px...")
    manifest = []
    n_cached = 0
    n_resized = 0
    n_failed = 0
    all_dest_names = {t[1] for t in all_tasks}

    # Prune stale entries from cache
    if cache:
        cache.prune(all_dest_names)

    # Separate cached vs need-resize
    to_resize = []
    n_skip_failed = 0
    for src, dst_name, label in all_tasks:
        if cache and cache.is_cached(src, dst_name):
            manifest.append((dst_name, label))
            n_cached += 1
        elif cache and cache.is_known_failed(src, dst_name):
            n_skip_failed += 1
        else:
            to_resize.append((src, dst_name, label))

    if n_cached or n_skip_failed:
        parts = []
        if n_cached:
            parts.append(f"{n_cached} cached")
        if n_skip_failed:
            parts.append(f"{n_skip_failed} known-failed")
        print(f"  Skipped: {' + '.join(parts)} / {len(all_tasks)}")

    if to_resize:
        img_dir = cache.images_dir if cache else None
        if not cache:
            # No cache: use temp dir
            out_dir = archive.parent / "_tmp_pack"
            if out_dir.exists():
                shutil.rmtree(out_dir)
            (out_dir / "images").mkdir(parents=True)
            img_dir = out_dir / "images"

        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {}
            for src, dst_name, label in to_resize:
                dst = str(img_dir / dst_name)
                futures[pool.submit(resize_and_save, src, dst, args.max_size)] = (src, dst_name, label)
            for fut in as_completed(futures):
                src, dst_name, label = futures[fut]
                if fut.result():
                    manifest.append((dst_name, label))
                    n_resized += 1
                    if cache:
                        cache.record(src, dst_name)
                else:
                    n_failed += 1
                    if cache:
                        src_path = futures[fut][0]
                        cache.record_failed(src_path, futures[fut][1])
                if (n_resized + n_failed) % 500 == 0 and (n_resized + n_failed) > 0:
                    print(f"  {n_resized + n_failed}/{len(to_resize)}")

        if cache:
            cache.commit()

    total_failed = n_failed + n_skip_failed
    print(f"  Done: {n_cached} cached + {n_resized} resized + {total_failed} failed = {len(manifest)} total")

    # Write manifest
    # Determine the images directory for the archive
    if cache:
        pack_img_dir = cache.images_dir
    else:
        pack_img_dir = out_dir / "images"

    # Build the archive staging area
    out_dir = archive.parent / "_tmp_pack"
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)

    # Symlink images dir from cache (fast!) or it's already there
    if cache:
        os.symlink(str(cache.images_dir), str(out_dir / "images"))
    else:
        # images are already in out_dir/images from resize step
        pass

    manifest_path = out_dir / "manifest.csv"
    with open(manifest_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["filename", "label"])
        for name, label in sorted(manifest):
            w.writerow([name, label])
    print(f"Manifest: {len(manifest)} entries")

    # Bundle training script
    if not args.no_train_script:
        (out_dir / "train.py").write_text(TRAIN_SCRIPT)
        (out_dir / "requirements.txt").write_text(REQUIREMENTS)
        print("Added train.py + requirements.txt")

    # Compress (--dereference to follow the symlink)
    print(f"Compressing to {archive}...")
    subprocess.run(
        ["tar", "czf", str(archive), "--dereference", "-C", str(out_dir.parent), out_dir.name],
        check=True,
    )
    size_mb = archive.stat().st_size / 1024 / 1024
    print(f"Archive: {size_mb:.0f} MB")
    print(f"\nDone! Transfer {archive} to your GPU machine and run:")
    print(f"  tar xzf {archive.name}")
    print(f"  cd {out_dir.name}")
    print(f"  pip install -r requirements.txt")
    print(f"  python train.py")

    # Cleanup staging (keep cache!)
    shutil.rmtree(out_dir)
    if cache:
        cache.close()


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

    for param in model.parameters():
        param.requires_grad = False

    if hasattr(model, 'head'):
        for param in model.head.parameters():
            param.requires_grad = True
    elif hasattr(model, 'classifier'):
        for param in model.classifier.parameters():
            param.requires_grad = True
    elif hasattr(model, 'fc'):
        for param in model.fc.parameters():
            param.requires_grad = True

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

    skf = StratifiedKFold(n_splits=args.folds, shuffle=True, random_state=42)
    all_val_probs = np.zeros(len(df))
    fold_aucs = []

    for fold, (train_idx, val_idx) in enumerate(skf.split(df, df["label"])):
        print(f"\n{'='*60}")
        print(f"Fold {fold+1}/{args.folds}")
        print(f"{'='*60}")

        train_df = df.iloc[train_idx]
        val_df = df.iloc[val_idx]

        train_ds = PreferenceDataset(train_df, img_dir, get_transforms(True, args.size))
        val_ds = PreferenceDataset(val_df, img_dir, get_transforms(False, args.size))
        train_loader = DataLoader(train_ds, batch_size=args.batch_size, shuffle=True, num_workers=args.workers, pin_memory=True)
        val_loader = DataLoader(val_ds, batch_size=args.batch_size, shuffle=False, num_workers=args.workers, pin_memory=True)

        model = create_model(args.model, num_classes=1, unfreeze_stages=args.unfreeze)
        model = model.to(device)

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

    overall_auc = roc_auc_score(df["label"].values, all_val_probs)
    print(f"\n{'='*60}")
    print(f"Cross-Validation Results")
    print(f"{'='*60}")
    print(f"Fold AUCs: {[f'{a:.4f}' for a in fold_aucs]}")
    print(f"Mean AUC:  {np.mean(fold_aucs):.4f} ± {np.std(fold_aucs):.4f}")
    print(f"Overall AUC: {overall_auc:.4f}")
    print(classification_report(df["label"].values, (all_val_probs >= 0.5).astype(int),
                                target_names=["disliked", "liked"]))

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


if __name__ == "__main__":
    main()
'''


if __name__ == "__main__":
    main()
