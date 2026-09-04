#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
VENV_DIR=".venv"
if [ -x "venv/bin/python" ]; then
  VENV_DIR="venv"
fi
if [ ! -x "$VENV_DIR/bin/python" ]; then
  python3 -m venv "$VENV_DIR"
fi
source "$VENV_DIR/bin/activate"
python -m pip install -r requirements.txt
python run.py
