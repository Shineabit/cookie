#!/usr/bin/env bash
# ───────────────────────────────────────────────────────────────────────
# Single start for Cookie Auto-Login ULTIMATE Pro (version_one)
#   ./start.sh
# Ensures venv + deps, then launches the GUI. Idempotent (safe to re-run).
# ───────────────────────────────────────────────────────────────────────
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

PY="${PY:-python3}"

# 1) Create venv if missing
if [ ! -x ".venv/bin/activate" ]; then
  echo "[*] Creating virtualenv..."
  "$PY" -m venv .venv
fi

# 2) Activate
# shellcheck disable=SC1091
source .venv/bin/activate

# 3) Ensure tkinter is importable (Debian/Ubuntu)
if ! "$PY" -c "import tkinter" >/dev/null 2>&1; then
  echo "[*] tkinter missing - attempting install (needs apt/sudo)..."
  (command -v sudo >/dev/null && sudo apt-get update -qq && sudo apt-get install -y python3-tk) \
    || echo "[!] Could not auto-install python3-tk. Install it manually: sudo apt install python3-tk"
fi

# 4) Install/refresh deps
echo "[*] Checking dependencies..."
pip install --quiet --disable-pip-version-check -r requirements.txt

# 5) Launch
echo "[*] Starting GUI..."
if [ -z "$DISPLAY" ] && [ -z "$WAYLAND_DISPLAY" ]; then
  echo "[!] No DISPLAY/Wayland detected. This is a GUI app and needs a desktop session."
  echo "    - Run it on your local machine / a desktop environment, or"
  echo "    - Forward X with:  ssh -X user@host  (then re-run ./start.sh)"
  exit 1
fi
exec "$PY" gui.py
