#!/bin/bash
# Remote pack: resize locally → upload → extract from tar on remote → pull tar.gz back.
#
# This is a site-specific workflow for setups with:
#   - A remote server (ToyServer) with DanbooruFinder tar archives
#   - SSH access configured
#
# Requires: TOYSERVER_HOST and TAR_INDEX_DB in .env
#
# Usage:
#   ./integrations/pack_remote.sh --liked ~/liked --disliked ~/disliked
#   ./integrations/pack_remote.sh --include-db
#
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CLASSIFIER_DIR="$(dirname "$SCRIPT_DIR")"
PROJECT_ROOT="$(dirname "$CLASSIFIER_DIR")"
BACKEND_DIR="$PROJECT_ROOT/backend"

if [ -f "$PROJECT_ROOT/.env" ]; then
    set -a; source "$PROJECT_ROOT/.env"; set +a
fi

TOYSERVER="${TOYSERVER_HOST:?Set TOYSERVER_HOST in .env}"
REMOTE_WORK="${REMOTE_WORK_DIR:-/home/cch-claw/_tmp_pack_work}"
LOCAL_WORK="$CLASSIFIER_DIR/_tmp_pack_local"
ARCHIVE="$CLASSIFIER_DIR/preference_train.tar.gz"
MAX_SIZE=512

cleanup() {
    echo "=== Cleanup ==="
    rm -rf "$LOCAL_WORK"
    ssh "$TOYSERVER" "rm -rf $REMOTE_WORK" 2>/dev/null || true
}
trap cleanup EXIT

mkdir -p "$LOCAL_WORK/resized"

echo "=== Pack (remote) started at $(date '+%F %T') ==="

# --- Step 1: Build manifest + resize locally ---
echo "=== Step 1: Build manifest & resize local images ==="
cd "$BACKEND_DIR"
source venv/bin/activate

SCRIPT_DIR="$SCRIPT_DIR" PROJECT_ROOT="$PROJECT_ROOT" LOCAL_WORK="$LOCAL_WORK" \
python3 - "$@" <<'PYEOF'
import argparse, json, os, sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

project_root = Path(os.environ["PROJECT_ROOT"])
local_work = os.environ["LOCAL_WORK"]
MAX_SIZE = 512
resized_dir = os.path.join(local_work, "resized")

sys.path.insert(0, str(project_root / "classifier"))
from pack_dataset import collect_from_folders, collect_from_sieve_dbs, resize_and_save

parser = argparse.ArgumentParser()
parser.add_argument("--liked", nargs="*", type=Path)
parser.add_argument("--disliked", nargs="*", type=Path)
parser.add_argument("--data-dir", type=Path)
parser.add_argument("--include-db", action="store_true")
args, _ = parser.parse_known_args()

all_tasks = []
liked_dirs = list(args.liked or [])
disliked_dirs = list(args.disliked or [])
if args.data_dir:
    if (args.data_dir / "liked").is_dir(): liked_dirs.append(args.data_dir / "liked")
    if (args.data_dir / "disliked").is_dir(): disliked_dirs.append(args.data_dir / "disliked")
if liked_dirs or disliked_dirs:
    all_tasks.extend(collect_from_folders(liked_dirs, disliked_dirs))
if args.include_db or (not liked_dirs and not disliked_dirs):
    all_tasks.extend(collect_from_sieve_dbs())

# Danbooru disliked IDs for remote tar extraction
danbooru_disliked_ids = []
danbooru_labels_db = project_root / "backend" / "danbooru_labels.db"
if danbooru_labels_db.exists():
    import sqlite3
    conn = sqlite3.connect(str(danbooru_labels_db))
    cur = conn.cursor()
    cur.execute('SELECT image_id, ext FROM labels WHERE verdict = "disliked"')
    danbooru_disliked_ids = [{"id": str(r[0]), "ext": r[1]} for r in cur.fetchall()]
    conn.close()

print(f"Local: {len(all_tasks)}, Remote disliked: {len(danbooru_disliked_ids)}")
print(f"Resizing {len(all_tasks)} local images to {MAX_SIZE}px...")

manifest_local = []
done = 0
with ThreadPoolExecutor(max_workers=8) as pool:
    futures = {}
    for src, dst_name, label in all_tasks:
        dst = os.path.join(resized_dir, dst_name)
        futures[pool.submit(resize_and_save, src, dst, MAX_SIZE)] = (dst_name, label)
    for fut in futures:
        dst_name, label = futures[fut]
        if fut.result():
            manifest_local.append((dst_name, label))
            done += 1
        if done % 500 == 0 and done > 0:
            print(f"  {done}/{len(all_tasks)}")
print(f"  Resized: {done}/{len(all_tasks)}")

with open(os.path.join(local_work, "manifest_local.json"), "w") as f:
    json.dump(manifest_local, f)
with open(os.path.join(local_work, "danbooru_disliked.json"), "w") as f:
    json.dump(danbooru_disliked_ids, f)
PYEOF

echo "=== Step 2: Upload to remote ==="
ssh "$TOYSERVER" "mkdir -p $REMOTE_WORK/scripts"
rsync -a "$LOCAL_WORK/resized/" "$TOYSERVER:$REMOTE_WORK/resized/"
scp "$LOCAL_WORK/manifest_local.json" "$TOYSERVER:$REMOTE_WORK/"
scp "$LOCAL_WORK/danbooru_disliked.json" "$TOYSERVER:$REMOTE_WORK/"

echo "=== Step 3: Extract + pack on remote ==="
cat > "$LOCAL_WORK/_remote_pack.py" <<'REMOTEPY'
#!/usr/bin/env python3
"""Merge pre-resized images + extract disliked from DanbooruFinder tar archives."""
import csv, json, os, shutil, sqlite3, subprocess
from PIL import Image

WORK = os.environ.get("WORK_DIR", "/home/cch-claw/_tmp_pack_work")
TAR_INDEX_DB = os.environ.get("TAR_INDEX_DB", "")
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

danbooru_disliked = json.load(open(os.path.join(WORK, "danbooru_disliked.json")))
if danbooru_disliked and TAR_INDEX_DB and os.path.exists(TAR_INDEX_DB):
    print(f"Extracting {len(danbooru_disliked)} disliked from tar archives...")
    conn = sqlite3.connect(TAR_INDEX_DB)
    cur = conn.cursor()
    extracted = missing = 0
    for item in danbooru_disliked:
        img_id, ext = item["id"], item["ext"]
        dst_name = f"danbooru_{img_id}.jpg"
        dst = os.path.join(OUT_IMAGES, dst_name)
        fname1, fname2 = f"{img_id}.{ext}", f"./{img_id}.{ext}"
        cur.execute("SELECT tar_path, offset, size FROM tar_index WHERE file_name=? OR file_name=? LIMIT 1", (fname1, fname2))
        row = cur.fetchone()
        if not row:
            missing += 1; continue
        tar_path, offset, size = row
        try:
            fd = os.open(tar_path, os.O_RDONLY)
            data = os.pread(fd, size, offset)
            os.close(fd)
            raw_path = dst + ".raw"
            with open(raw_path, "wb") as f: f.write(data)
            if resize_save(raw_path, dst):
                manifest_out.append((dst_name, 0))
                extracted += 1
            os.unlink(raw_path)
        except Exception as e:
            print(f"  Error {img_id}: {e}")
    conn.close()
    print(f"  Extracted: {extracted}, missing: {missing}")
elif danbooru_disliked:
    print(f"TAR_INDEX_DB not set, skipping {len(danbooru_disliked)} remote disliked")

shutil.rmtree(resized_dir, ignore_errors=True)
n_liked = sum(1 for _, l in manifest_out if l == 1)
n_disliked = sum(1 for _, l in manifest_out if l == 0)
print(f"Final: {len(manifest_out)} ({n_liked} liked, {n_disliked} disliked)")

with open(os.path.join(OUT, "manifest.csv"), "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["filename", "label"])
    for name, label in sorted(manifest_out):
        w.writerow([name, label])

print("Compressing...")
archive = os.path.join(WORK, "preference_train.tar.gz")
subprocess.run(["tar", "czf", archive, "-C", WORK, "preference_train"], check=True)
print(f"Archive: {os.path.getsize(archive)/1024/1024:.0f} MB")
shutil.rmtree(OUT, ignore_errors=True)
REMOTEPY

scp "$LOCAL_WORK/_remote_pack.py" "$TOYSERVER:$REMOTE_WORK/scripts/remote_pack.py"
ssh "$TOYSERVER" "pip3 install --quiet --user Pillow 2>/dev/null; WORK_DIR=$REMOTE_WORK python3 $REMOTE_WORK/scripts/remote_pack.py"

echo "=== Step 4: Download archive ==="
rsync -a --progress "$TOYSERVER:$REMOTE_WORK/preference_train.tar.gz" "$ARCHIVE"

SIZE=$(du -h "$ARCHIVE" | cut -f1)
echo "=== Done! Archive: $ARCHIVE ($SIZE) ==="
