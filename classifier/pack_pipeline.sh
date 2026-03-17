#!/bin/bash
# Pack dataset for GPU training (extracts disliked from remote, then packs)
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
BACKEND_DIR="$PROJECT_ROOT/backend"
LABELS_DB="$BACKEND_DIR/danbooru_labels.db"

# These can be overridden via environment
TOYSERVER="${TOYSERVER_HOST:?Set TOYSERVER_HOST in .env}"
LOCAL_DISLIKED="${DANBOORU_DISLIKED_DIR:-/tmp/danbooru_disliked}"

echo "=== Step 1: Extract disliked from remote ($TOYSERVER) ==="
scp "$LABELS_DB" "$TOYSERVER:/tmp/danbooru_labels.db"
scp "$SCRIPT_DIR/extract_disliked_remote.py" "$TOYSERVER:/tmp/extract_danbooru_disliked.py"
ssh "$TOYSERVER" "python3 /tmp/extract_danbooru_disliked.py /tmp/danbooru_labels.db"

echo "=== Step 2: Rsync back ==="
mkdir -p "$LOCAL_DISLIKED"
rsync -a "$TOYSERVER:/tmp/danbooru_disliked/" "$LOCAL_DISLIKED/"

echo "=== Step 3: Pack dataset ==="
cd "$SCRIPT_DIR"
source "$BACKEND_DIR/venv/bin/activate"
DANBOORU_DISLIKED_DIR="$LOCAL_DISLIKED" python pack_dataset.py

echo "=== Step 4: Cleanup ==="
rm -rf "$LOCAL_DISLIKED"
ssh "$TOYSERVER" "rm -rf /tmp/danbooru_disliked /tmp/danbooru_labels.db /tmp/extract_danbooru_disliked.py"

ARCHIVE="$SCRIPT_DIR/preference_train.tar.gz"
SIZE=$(du -h "$ARCHIVE" | cut -f1)
echo "=== Done! Archive: $ARCHIVE ($SIZE) ==="
