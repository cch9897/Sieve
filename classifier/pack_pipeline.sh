#!/bin/bash
# Pack preference dataset for GPU training.
#
# Usage:
#   ./pack_pipeline.sh --liked ~/liked_imgs --disliked ~/disliked_imgs
#   ./pack_pipeline.sh --data-dir ~/preference_data
#   ./pack_pipeline.sh --include-db   # Sieve DB sources
#
# All arguments are passed through to pack_dataset.py.
# See: python pack_dataset.py --help
#
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
BACKEND_DIR="$PROJECT_ROOT/backend"

# Load .env if present
if [ -f "$PROJECT_ROOT/.env" ]; then
    set -a; source "$PROJECT_ROOT/.env"; set +a
fi

# Activate venv if available
if [ -f "$BACKEND_DIR/venv/bin/activate" ]; then
    source "$BACKEND_DIR/venv/bin/activate"
fi

echo "=== Pack started at $(date '+%F %T') ==="
python3 "$SCRIPT_DIR/pack_dataset.py" "$@"
