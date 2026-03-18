#!/bin/bash
# Pack dataset for GPU training.
# Strategy:
#   1. Locally: build manifest, resize local images (booru+twitter+danbooru_liked) to 512px JPEG
#   2. Upload resized images + danbooru disliked list to ToyServer
#   3. ToyServer: extract disliked from tar, resize them, merge all, compress
#   4. Pull back only the final tar.gz
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
BACKEND_DIR="$PROJECT_ROOT/backend"

TOYSERVER="${TOYSERVER_HOST:?Set TOYSERVER_HOST in .env}"
REMOTE_WORK="/home/cch/_tmp_pack_work"

# Load .env for local paths
if [ -f "$PROJECT_ROOT/.env" ]; then
    set -a; source "$PROJECT_ROOT/.env"; set +a
fi

LABELS_DB="${LABELS_DB:-$BACKEND_DIR/labels.db}"
DANBOORU_LABELS_DB="$BACKEND_DIR/danbooru_labels.db"
CRAWLER_DIR="${CRAWLER_DIR:?Set CRAWLER_DIR in .env}"
DEDUP_DB="$CRAWLER_DIR/dedup.db"
TWITTER_DIR="${TWITTER_DIR:-}"
DANBOORU_LIKES_DIR="${DANBOORU_LIKES_DIR:-$PROJECT_ROOT/data/danbooru_liked}"
ARCHIVE="$SCRIPT_DIR/preference_train.tar.gz"
LOCAL_WORK="$SCRIPT_DIR/_tmp_pack_local"

cleanup() {
    echo "=== Cleanup ==="
    rm -rf "$LOCAL_WORK"
    ssh "$TOYSERVER" "rm -rf $REMOTE_WORK" 2>/dev/null || true
}
trap cleanup EXIT

mkdir -p "$LOCAL_WORK/resized"

echo "=== Pack started at $(date '+%F %T') ==="

# --- Step 1: Build manifest + resize local images ---
echo "=== Step 1: Build manifest & resize local images ==="
cd "$BACKEND_DIR"
source venv/bin/activate

python3 - <<PYEOF
import csv, json, os, sqlite3, sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from PIL import Image

labels_db = "$LABELS_DB"
dedup_db = "$DEDUP_DB"
danbooru_labels_db = "$DANBOORU_LABELS_DB"
crawler_dir = "$CRAWLER_DIR"
danbooru_likes_dir = "$DANBOORU_LIKES_DIR"
twitter_dir = "$TWITTER_DIR"
local_work = "$LOCAL_WORK"
MAX_SIZE = 512

resized_dir = os.path.join(local_work, "resized")

def resize_save(src, dst):
    try:
        img = Image.open(src).convert("RGB")
        w, h = img.size
        if max(w, h) > MAX_SIZE:
            r = MAX_SIZE / max(w, h)
            img = img.resize((int(w * r), int(h * r)), Image.LANCZOS)
        img.save(dst, "JPEG", quality=85)
        return True
    except Exception as e:
        print(f"  SKIP {src}: {e}")
        return False

# --- Collect local tasks ---
local_tasks = []  # (src_path, dst_name, label)

# Booru
conn_l = sqlite3.connect(labels_db)
cur = conn_l.cursor()
cur.execute('SELECT image_id, verdict FROM labels WHERE verdict IN ("liked","disliked")')
labels = {r[0]: r[1] for r in cur.fetchall()}
conn_l.close()

conn_d = sqlite3.connect(dedup_db)
cur = conn_d.cursor()
ids = list(labels.keys())
ph = ",".join("?" * len(ids))
cur.execute(f"SELECT id, file_path FROM images WHERE id IN ({ph})", ids)
for img_id, fp in cur.fetchall():
    src = os.path.join(crawler_dir, fp)
    local_tasks.append((src, f"booru_{img_id}.jpg", 1 if labels[img_id] == "liked" else 0))
conn_d.close()

# Twitter
if twitter_dir and os.path.isdir(twitter_dir):
    for f in sorted(os.listdir(twitter_dir)):
        if f.lower().split(".")[-1] in ("jpg", "jpeg", "png", "webp", "gif"):
            local_tasks.append((os.path.join(twitter_dir, f), f"twitter_{Path(f).stem}.jpg", 1))

# Danbooru liked
danbooru_disliked_ids = []
if os.path.exists(danbooru_labels_db):
    conn = sqlite3.connect(danbooru_labels_db)
    cur = conn.cursor()
    cur.execute('SELECT image_id, ext, verdict FROM labels WHERE verdict IN ("liked","disliked")')
    for img_id, ext, verdict in cur.fetchall():
        if verdict == "liked":
            p = os.path.join(danbooru_likes_dir, f"{img_id}.{ext}")
            if os.path.exists(p):
                local_tasks.append((p, f"danbooru_{img_id}.jpg", 1))
        else:
            danbooru_disliked_ids.append({"id": str(img_id), "ext": ext})
    conn.close()

n_booru = sum(1 for t in local_tasks if t[1].startswith("booru_"))
n_twitter = sum(1 for t in local_tasks if t[1].startswith("twitter_"))
n_dl = sum(1 for t in local_tasks if t[1].startswith("danbooru_"))
print(f"Local: {len(local_tasks)} (booru={n_booru}, twitter={n_twitter}, danbooru_liked={n_dl})")
print(f"Remote: {len(danbooru_disliked_ids)} danbooru disliked")

# --- Resize local images ---
print(f"Resizing {len(local_tasks)} local images to {MAX_SIZE}px...")
manifest_local = []
done = 0
with ThreadPoolExecutor(max_workers=8) as pool:
    futures = {}
    for src, dst_name, label in local_tasks:
        dst = os.path.join(resized_dir, dst_name)
        futures[pool.submit(resize_save, src, dst)] = (dst_name, label)
    for fut in as_completed(futures):
        dst_name, label = futures[fut]
        if fut.result():
            manifest_local.append((dst_name, label))
            done += 1
        if done % 500 == 0 and done > 0:
            print(f"  {done}/{len(local_tasks)}")

print(f"  Resized: {done}/{len(local_tasks)}")

# Write outputs
with open(os.path.join(local_work, "manifest_local.json"), "w") as f:
    json.dump(manifest_local, f)
with open(os.path.join(local_work, "danbooru_disliked.json"), "w") as f:
    json.dump(danbooru_disliked_ids, f)
PYEOF

echo "=== Step 2: Upload resized images to ToyServer ==="
ssh "$TOYSERVER" "mkdir -p $REMOTE_WORK/scripts"

# Upload already-resized images (much smaller than originals)
rsync -a "$LOCAL_WORK/resized/" "$TOYSERVER:$REMOTE_WORK/resized/"
scp "$LOCAL_WORK/manifest_local.json" "$TOYSERVER:$REMOTE_WORK/"
scp "$LOCAL_WORK/danbooru_disliked.json" "$TOYSERVER:$REMOTE_WORK/"

echo "=== Step 3: Extract disliked + pack on ToyServer ==="
# The remote script: extract disliked from tar, resize, merge with uploaded resized, compress
cat > "$LOCAL_WORK/_remote_pack.py" <<'REMOTEPY'
#!/usr/bin/env python3
"""Run on ToyServer: extract & resize disliked, merge with pre-resized local images, compress."""
import csv, json, os, shutil, sqlite3, subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from PIL import Image

WORK = os.environ.get("WORK_DIR", "/home/cch/_tmp_pack_work")
TAR_INDEX_DB = os.environ.get("TAR_INDEX_DB", "/home/cch/DanbooruFinder_Backend/cache/tar_index.db")
MAX_SIZE = 512
OUT = os.path.join(WORK, "preference_train")
OUT_IMAGES = os.path.join(OUT, "images")
os.makedirs(OUT_IMAGES, exist_ok=True)

def resize_save(src, dst):
    try:
        img = Image.open(src).convert("RGB")
        w, h = img.size
        if max(w, h) > MAX_SIZE:
            r = MAX_SIZE / max(w, h)
            img = img.resize((int(w * r), int(h * r)), Image.LANCZOS)
        img.save(dst, "JPEG", quality=85)
        return True
    except Exception as e:
        print(f"  SKIP {src}: {e}")
        return False

# --- Move pre-resized local images into output ---
manifest_local = json.load(open(os.path.join(WORK, "manifest_local.json")))
resized_dir = os.path.join(WORK, "resized")
manifest_out = []
for dst_name, label in manifest_local:
    src = os.path.join(resized_dir, dst_name)
    dst = os.path.join(OUT_IMAGES, dst_name)
    if os.path.exists(src):
        shutil.move(src, dst)
        manifest_out.append((dst_name, label))

print(f"Local images: {len(manifest_out)}")

# --- Extract + resize danbooru disliked ---
danbooru_disliked = json.load(open(os.path.join(WORK, "danbooru_disliked.json")))
if danbooru_disliked:
    print(f"Extracting & resizing {len(danbooru_disliked)} disliked from tar archives...")
    conn = sqlite3.connect(TAR_INDEX_DB)
    cur = conn.cursor()
    extracted = missing = errors = 0

    for item in danbooru_disliked:
        img_id, ext = item["id"], item["ext"]
        dst_name = f"danbooru_{img_id}.jpg"
        dst = os.path.join(OUT_IMAGES, dst_name)
        fname1, fname2 = f"{img_id}.{ext}", f"./{img_id}.{ext}"
        cur.execute("SELECT tar_path, offset, size FROM tar_index WHERE file_name=? OR file_name=? LIMIT 1", (fname1, fname2))
        row = cur.fetchone()
        if not row:
            missing += 1
            continue
        tar_path, offset, size = row
        try:
            fd = os.open(tar_path, os.O_RDONLY)
            data = os.pread(fd, size, offset)
            os.close(fd)
            # Write raw, then resize in-place
            raw_path = dst + ".raw"
            with open(raw_path, "wb") as f:
                f.write(data)
            if resize_save(raw_path, dst):
                manifest_out.append((dst_name, 0))
                extracted += 1
            os.unlink(raw_path)
        except Exception as e:
            print(f"  Error {img_id}: {e}")
            errors += 1
        if extracted % 500 == 0 and extracted > 0:
            print(f"  Extracted & resized {extracted}...")

    conn.close()
    print(f"  Done: {extracted} extracted, {missing} missing, {errors} errors")

# Clean up resized dir (already moved)
shutil.rmtree(resized_dir, ignore_errors=True)

n_liked = sum(1 for _, l in manifest_out if l == 1)
n_disliked = sum(1 for _, l in manifest_out if l == 0)
print(f"Final: {len(manifest_out)} images ({n_liked} liked, {n_disliked} disliked)")

# Write manifest
with open(os.path.join(OUT, "manifest.csv"), "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["filename", "label"])
    for name, label in sorted(manifest_out):
        w.writerow([name, label])

print("Compressing...")
archive = os.path.join(WORK, "preference_train.tar.gz")
subprocess.run(["tar", "czf", archive, "-C", WORK, "preference_train"], check=True)
size_mb = os.path.getsize(archive) / 1024 / 1024
print(f"Archive: {size_mb:.0f} MB")

# Clean up images dir to free space before download
shutil.rmtree(OUT, ignore_errors=True)
REMOTEPY

scp "$LOCAL_WORK/_remote_pack.py" "$TOYSERVER:$REMOTE_WORK/scripts/remote_pack.py"
ssh "$TOYSERVER" "pip3 install --quiet --user Pillow 2>/dev/null; WORK_DIR=$REMOTE_WORK python3 $REMOTE_WORK/scripts/remote_pack.py"

echo "=== Step 4: Download archive ==="
rsync -a --progress "$TOYSERVER:$REMOTE_WORK/preference_train.tar.gz" "$ARCHIVE"

SIZE=$(du -h "$ARCHIVE" | cut -f1)
echo "=== Done! Archive: $ARCHIVE ($SIZE) ==="
