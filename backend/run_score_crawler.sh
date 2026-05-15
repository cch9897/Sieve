#!/bin/bash
# Score crawler images with vision model
# Run with nice/ionice to avoid impacting other services
cd "$(dirname "$0")" || exit 1
source venv/bin/activate 2>/dev/null || source ../backend/venv/bin/activate 2>/dev/null
exec nice -n 15 ionice -c 3 python score_crawler.py "$@"
