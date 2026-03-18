#!/usr/bin/env python3
"""Extract disliked danbooru images from tar archives on remote server.

This script is meant to run on the remote server (ToyServer) where
the DanbooruFinder tar archives are stored. It reads a labels DB
and extracts disliked images directly from tar files.

Environment variables:
    TAR_INDEX_DB: path to tar_index.db on the remote server
"""
import os
import sqlite3
import sys

TAR_INDEX_DB = os.environ.get("TAR_INDEX_DB", "/home/cch/DanbooruFinder_Backend/cache/tar_index.db")
LABELS_DB_PATH = sys.argv[1]
OUT_DIR = os.environ.get("DANBOORU_DISLIKED_DIR", "/home/cch/_tmp_pack_work/disliked")

os.makedirs(OUT_DIR, exist_ok=True)

conn_l = sqlite3.connect(LABELS_DB_PATH)
cur = conn_l.cursor()
cur.execute("SELECT image_id, ext FROM labels WHERE verdict='disliked'")
disliked = {str(r[0]): r[1] for r in cur.fetchall()}
conn_l.close()
print(f"Disliked images to extract: {len(disliked)}")

conn_t = sqlite3.connect(TAR_INDEX_DB)
cur_t = conn_t.cursor()
found = missing = errors = 0

for img_id, ext in disliked.items():
    dst = os.path.join(OUT_DIR, f"{img_id}.{ext}")
    if os.path.exists(dst) and os.path.getsize(dst) > 100:
        found += 1
        continue
    cur_t.execute(
        "SELECT tar_path, offset, size FROM tar_index WHERE file_name=? OR file_name=? LIMIT 1",
        (f"{img_id}.{ext}", f"./{img_id}.{ext}")
    )
    row = cur_t.fetchone()
    if not row:
        missing += 1
        continue
    tar_path, offset, size = row
    try:
        fd = os.open(tar_path, os.O_RDONLY)
        data = os.pread(fd, size, offset)
        os.close(fd)
        with open(dst, "wb") as f:
            f.write(data)
        found += 1
        if found % 500 == 0:
            print(f"  Extracted {found}...")
    except Exception as e:
        print(f"  Error {img_id}: {e}")
        errors += 1

conn_t.close()
print(f"Done: {found} extracted, {missing} missing, {errors} errors")
