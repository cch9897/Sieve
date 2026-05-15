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
    touch "$VENV_DIR/.requirements_installed"
fi

# Sync deps if requirements.txt changed since last install
MARKER="$VENV_DIR/.requirements_installed"
if [ ! -f "$MARKER" ] || [ "$BACKEND_DIR/requirements.txt" -nt "$MARKER" ]; then
    echo "Updating Python dependencies..."
    "$VENV_DIR/bin/pip" install -q -r "$BACKEND_DIR/requirements.txt"
    touch "$MARKER"
fi

echo "Starting Sieve on http://localhost:8780"
cd "$BACKEND_DIR"
exec "$VENV_DIR/bin/python" -m uvicorn main:app --host 0.0.0.0 --port 8780
