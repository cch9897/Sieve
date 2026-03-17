#!/bin/bash
# Retrain the preference classifier (combines all data sources)
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
BACKEND_DIR="$PROJECT_ROOT/backend"

cd "$BACKEND_DIR"
source venv/bin/activate

# 1. Tag new images (if Twitter data configured)
echo "=== Step 1: Tagging new images ==="
python3 "$SCRIPT_DIR/tag_twitter.py"

# 2. Retrain
echo "=== Step 2: Training classifier ==="
python3 "$SCRIPT_DIR/train_classifier.py"

# 3. Restart service to load new model
echo "=== Step 3: Restarting sieve ==="
systemctl --user restart sieve || echo "Service restart skipped (not installed)"

echo "Done! Model retrained and service restarted."
