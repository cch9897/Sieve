#!/usr/bin/env python3
"""
Copy danbooru_liked + liked images to a training folder and tag with WD14 for T2I training.
Output: sequential numbered images + matching .txt caption files.

Supports GPU inference via onnxruntime-gpu (CUDAExecutionProvider).
Tracks source→seq mapping in manifest.json for incremental updates.
"""

import json
import os
import shutil
import time
from pathlib import Path

DANBOORU_LIKED_DIR = Path("/mnt/nas_booru/danbooru_liked")
LIKED_DIR = Path("/mnt/nas_booru/liked")
DST_DIR = Path("/mnt/nas_booru/danbooru_liked_train")
MANIFEST_PATH = DST_DIR / "manifest.json"
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}

MODEL_NAME = "SwinV2_v3"
GENERAL_THRESHOLD = 0.35
CHARACTER_THRESHOLD = 0.75


def get_all_source_files() -> list[tuple[str, str]]:
    """Return sorted list of (source_key, full_path) from both dirs."""
    files = []
    for f in sorted(os.listdir(DANBOORU_LIKED_DIR)):
        if Path(f).suffix.lower() in IMAGE_EXTS:
            files.append((f"danbooru/{f}", str(DANBOORU_LIKED_DIR / f)))
    for f in sorted(os.listdir(LIKED_DIR)):
        if Path(f).suffix.lower() in IMAGE_EXTS:
            files.append((f"liked/{f}", str(LIKED_DIR / f)))
    return files


def load_manifest() -> dict:
    if MANIFEST_PATH.exists():
        with open(MANIFEST_PATH, "r") as f:
            return json.load(f)
    return {}


def save_manifest(manifest: dict):
    with open(MANIFEST_PATH, "w") as f:
        json.dump(manifest, f, indent=2)


def main():
    # Force GPU if available
    import onnxruntime
    providers = onnxruntime.get_available_providers()
    if "CUDAExecutionProvider" in providers:
        print("Using GPU (CUDAExecutionProvider)")
        os.environ["ONNXRUNTIME_PROVIDERS"] = "CUDAExecutionProvider,CPUExecutionProvider"
    else:
        print("WARNING: No GPU available, falling back to CPU")

    from imgutils.tagging import get_wd14_tags

    DST_DIR.mkdir(parents=True, exist_ok=True)

    all_files = get_all_source_files()
    total = len(all_files)
    print(f"Found {total} source images (danbooru_liked + liked)")

    # Load manifest: maps source_key -> seq number
    manifest = load_manifest()
    known_keys = set(manifest.keys())

    # Find new files
    new_files = [(k, p) for k, p in all_files if k not in known_keys]
    print(f"Already in manifest: {len(known_keys)}, New: {len(new_files)}")

    if not new_files:
        print("Nothing new to process.")
        return

    # Next sequence number
    next_seq = max((v for v in manifest.values()), default=0) + 1

    tagged = 0
    errors = 0
    start = time.time()

    for i, (source_key, src_path) in enumerate(new_files):
        seq = f"{next_seq:05d}"
        ext = Path(src_path).suffix.lower()
        dst_img = DST_DIR / f"{seq}{ext}"
        dst_txt = DST_DIR / f"{seq}.txt"

        # Copy image
        shutil.copy2(src_path, dst_img)

        # Tag with WD14
        try:
            rating, general, character = get_wd14_tags(
                str(dst_img),
                model_name=MODEL_NAME,
                general_threshold=GENERAL_THRESHOLD,
                character_threshold=CHARACTER_THRESHOLD,
            )

            tags = []
            top_rating = max(rating, key=rating.get)
            tags.append(top_rating)

            for tag, score in sorted(character.items(), key=lambda x: -x[1]):
                tags.append(tag.replace("_", " "))

            for tag, score in sorted(general.items(), key=lambda x: -x[1]):
                tags.append(tag.replace("_", " "))

            dst_txt.write_text(", ".join(tags), encoding="utf-8")
            manifest[source_key] = next_seq
            tagged += 1
            next_seq += 1

        except Exception as e:
            errors += 1
            print(f"  ERROR [{seq}] {source_key}: {e}")
            dst_img.unlink(missing_ok=True)
            continue

        if tagged % 50 == 0:
            elapsed = time.time() - start
            rate = tagged / elapsed if elapsed > 0 else 0
            remaining = len(new_files) - i - 1
            eta = remaining / rate / 60 if rate > 0 else 0
            print(f"  [{tagged}/{len(new_files)}] {rate:.1f} img/s | ETA {eta:.0f}min | errors {errors}")
            # Save manifest periodically
            save_manifest(manifest)

    save_manifest(manifest)
    elapsed = time.time() - start
    print(f"\nDone in {elapsed/60:.1f} min")
    print(f"Tagged: {tagged}, Errors: {errors}, Total in dst: {len(list(DST_DIR.glob('*.txt')))}")


if __name__ == "__main__":
    main()
