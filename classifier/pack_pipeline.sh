#!/bin/bash
# Pack preference dataset for GPU training.
#
# Modes:
#   Local (default):
#     ./pack_pipeline.sh --liked ~/liked_imgs --disliked ~/disliked_imgs
#     ./pack_pipeline.sh --data-dir ~/preference_data
#     ./pack_pipeline.sh --include-db            # Sieve DB sources only
#
#   Remote (for setups with a second server holding large archives):
#     ./pack_pipeline.sh --remote --liked ~/liked --disliked ~/disliked
#     Requires TOYSERVER_HOST in .env. Resizes locally, uploads small images
#     to remote, extracts additional data there, packs and pulls back.
#
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
BACKEND_DIR="$PROJECT_ROOT/backend"

# Load .env
if [ -f "$PROJECT_ROOT/.env" ]; then
    set -a; source "$PROJECT_ROOT/.env"; set +a
fi

# --- Parse arguments ---
REMOTE_MODE=false
PACK_ARGS=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --remote)
            REMOTE_MODE=true
            shift
            ;;
        *)
            PACK_ARGS+=("$1")
            shift
            ;;
    esac
done

echo "=== Pack started at $(date '+%F %T') ==="

if [ "$REMOTE_MODE" = true ]; then
    # -----------------------------------------------------------------------
    # Remote mode: resize locally → upload → remote extract+pack → pull back
    # Requires: TOYSERVER_HOST, SSH access, Python+Pillow on remote
    # -----------------------------------------------------------------------
    TOYSERVER="${TOYSERVER_HOST:?Set TOYSERVER_HOST in .env for --remote mode}"
    REMOTE_WORK="/home/cch/_tmp_pack_work"
    LOCAL_WORK="$SCRIPT_DIR/_tmp_pack_local"

    cleanup() {
        echo "=== Cleanup ==="
        rm -rf "$LOCAL_WORK"
        ssh "$TOYSERVER" "rm -rf $REMOTE_WORK" 2>/dev/null || true
    }
    trap cleanup EXIT

    mkdir -p "$LOCAL_WORK/resized"

    # Step 1: Build manifest + resize locally via pack_dataset.py (dry-run style)
    echo "=== Step 1: Build manifest & resize local images ==="
    cd "$BACKEND_DIR"
    source venv/bin/activate

    python3 - "${PACK_ARGS[@]}" <<'PYEOF'
import csv, json, os, sqlite3, sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from PIL import Image

# Re-use pack_dataset collection logic
sys.path.insert(0, os.environ.get("SCRIPT_DIR", str(Path(__file__).parent)))

project_root = Path(os.environ.get("PROJECT_ROOT", str(Path(__file__).parent.parent)))
local_work = os.environ.get("LOCAL_WORK", "/tmp/_tmp_pack_local")
MAX_SIZE = 512
resized_dir = os.path.join(local_work, "resized")

# Import collection functions
sys.path.insert(0, str(project_root / "classifier"))
from pack_dataset import collect_from_folders, collect_from_sieve_dbs, resize_and_save, _env_path

# Parse args (simplified: just detect --liked/--disliked/--data-dir/--include-db)
import argparse
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

# Also collect danbooru disliked IDs for remote extraction
danbooru_disliked_ids = []
danbooru_labels_db = project_root / "backend" / "danbooru_labels.db"
if danbooru_labels_db.exists():
    import sqlite3
    conn = sqlite3.connect(str(danbooru_labels_db))
    cur = conn.cursor()
    cur.execute('SELECT image_id, ext FROM labels WHERE verdict = "disliked"')
    danbooru_disliked_ids = [{"id": str(r[0]), "ext": r[1]} for r in cur.fetchall()]
    conn.close()

print(f"Local: {len(all_tasks)} images, Remote disliked: {len(danbooru_disliked_ids)}")
print(f"Resizing {len(all_tasks)} local images to {MAX_SIZE}px...")

manifest_local = []
done = 0
with ThreadPoolExecutor(max_workers=8) as pool:
    futures = {}
    for src, dst_name, label in all_tasks:
        dst = os.path.join(resized_dir, dst_name)
        futures[pool.submit(resize_and_save, src, dst, MAX_SIZE)] = (dst_name, label)
    for fut in as_completed(futures):
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

    echo "=== Step 2: Upload resized images to remote ==="
    ssh "$TOYSERVER" "mkdir -p $REMOTE_WORK/scripts"
    rsync -a "$LOCAL_WORK/resized/" "$TOYSERVER:$REMOTE_WORK/resized/"
    scp "$LOCAL_WORK/manifest_local.json" "$TOYSERVER:$REMOTE_WORK/"
    scp "$LOCAL_WORK/danbooru_disliked.json" "$TOYSERVER:$REMOTE_WORK/"

    echo "=== Step 3: Extract + pack on remote ==="
    scp "$SCRIPT_DIR/extract_disliked_remote.py" "$TOYSERVER:$REMOTE_WORK/scripts/"

    # Remote pack script
    cat > "$LOCAL_WORK/_remote_pack.py" <<'REMOTEPY'
#!/usr/bin/env python3
"""Remote: merge pre-resized local images + extract disliked from tar archives."""
import csv, json, os, shutil, sqlite3, subprocess
from PIL import Image

WORK = os.environ.get("WORK_DIR", "/home/cch/_tmp_pack_work")
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

# Move pre-resized local images
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

# Extract + resize disliked from tar (if TAR_INDEX_DB configured)
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
    print(f"TAR_INDEX_DB not configured, skipping {len(danbooru_disliked)} remote disliked")

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
    ARCHIVE="$SCRIPT_DIR/preference_train.tar.gz"
    rsync -a --progress "$TOYSERVER:$REMOTE_WORK/preference_train.tar.gz" "$ARCHIVE"

    SIZE=$(du -h "$ARCHIVE" | cut -f1)
    echo "=== Done! Archive: $ARCHIVE ($SIZE) ==="

else
    # -----------------------------------------------------------------------
    # Local mode: just run pack_dataset.py directly
    # -----------------------------------------------------------------------
    echo "=== Local pack mode ==="

    # Activate venv if available
    if [ -f "$BACKEND_DIR/venv/bin/activate" ]; then
        source "$BACKEND_DIR/venv/bin/activate"
    fi

    python3 "$SCRIPT_DIR/pack_dataset.py" "${PACK_ARGS[@]}"
fi
