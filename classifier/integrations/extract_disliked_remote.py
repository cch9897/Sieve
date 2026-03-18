#!/usr/bin/env python3
"""
Extract disliked images from tar archives (DanbooruFinder) on a remote server.
This is a Sieve-specific integration script — only needed if you have a
DanbooruFinder backend with tar-indexed image archives.

Usage:
    python extract_disliked_remote.py <labels_db_path>

Environment:
    TAR_INDEX_DB   Path to DanbooruFinder tar_index.db
    DANBOORU_DISLIKED_DIR  Output directory for extracted images
"""

import os
import sqlite3
import sys

TAR_INDEX_DB = os.environ.get("TAR_INDEX_DB", "")
LABELS_DB_PATH = sys.argv[1] if len(sys.argv) > 1 else ""
OUT_DIR = os.environ.get("DANBOORU_DISLIKED_DIR", "/tmp/danbooru_disliked")

if not LABELS_DB_PATH:
    print("Usage: python extract_disliked_remote.py <labels_db_path>")
    print("Set TAR_INDEX_DB to your DanbooruFinder tar_index.db path")
    sys.exit(1)

if not TAR_INDEX_DB or not os.path.exists(TAR_INDEX_DB):
    print(f"TAR_INDEX_DB not set or not found: {TAR_INDEX_DB!r}")
    print("This script requires a DanbooruFinder tar index database.")
    sys.exit(1)

os.makedirs(OUT_DIR, exist_ok=True)

conn_labels = sqlite3.connect(LABELS_DB_PATH)
cur_labels = conn_labels.cursor()
cur_labels.execute('SELECT image_id, ext FROM labels WHERE verdict = "disliked"')
disliked = cur_labels.fetchall()
conn_labels.close()

print(f"Disliked images: {len(disliked)}")

conn_tar = sqlite3.connect(TAR_INDEX_DB)
cur_tar = conn_tar.cursor()

extracted = 0
missing = 0
errors = 0

for image_id, ext in disliked:
    out_path = os.path.join(OUT_DIR, f"{image_id}.{ext}")
    if os.path.exists(out_path):
        extracted += 1
        continue

    fname1 = f"{image_id}.{ext}"
    fname2 = f"./{image_id}.{ext}"
    cur_tar.execute(
        "SELECT tar_path, offset, size FROM tar_index WHERE file_name=? OR file_name=? LIMIT 1",
        (fname1, fname2),
    )
    row = cur_tar.fetchone()
    if not row:
        missing += 1
        continue

    tar_path, offset, size = row
    try:
        fd = os.open(tar_path, os.O_RDONLY)
        data = os.pread(fd, size, offset)
        os.close(fd)
        with open(out_path, "wb") as f:
            f.write(data)
        extracted += 1
    except Exception as e:
        print(f"  Error extracting {image_id}: {e}")
        errors += 1

    if extracted % 100 == 0 and extracted > 0:
        print(f"  Extracted {extracted}...")

conn_tar.close()
print(f"Done: {extracted} extracted, {missing} missing, {errors} errors")
