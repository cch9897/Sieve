#!/bin/bash
# Incremental auto-tagger runner — processes ALL untagged images
# Resource limits: max 4 cores, 2GB RAM, low priority
# Called daily at 03:00 by cron
# Uses flock to prevent concurrent runs

LOCKFILE="/tmp/booru-auto-tagger.lock"

exec 200>"$LOCKFILE"
if ! flock -n 200; then
    echo "Auto-tagger already running, skipping."
    exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"
source venv/bin/activate

# CPU: limit to cores 0-3, nice 15, ionice idle
# RAM: cgroup hard limit 2GB via systemd-run
systemd-run --user --scope -q \
    -p MemoryMax=2G \
    -p MemorySwapMax=0 \
    -p CPUQuota=400% \
    nice -n 15 ionice -c 3 \
    taskset -c 0-3 \
    python auto_tagger.py --batch 99999 --sleep 0.5 --threshold 0.35
