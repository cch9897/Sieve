#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$SCRIPT_DIR/backend"
VENV_DIR="$BACKEND_DIR/venv"

# Create venv if needed
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating Python virtual environment..."
    python3 -m venv "$VENV_DIR"
    "$VENV_DIR/bin/pip" install -q -r "$BACKEND_DIR/requirements.txt"
fi

echo "Starting Sieve on http://localhost:8780"
cd "$BACKEND_DIR"
exec "$VENV_DIR/bin/python" -m uvicorn main:app --host 0.0.0.0 --port 8780
