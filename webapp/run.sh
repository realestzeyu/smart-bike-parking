#!/usr/bin/env bash
# Start the web app. First run sets everything up; later runs just start the server.
# Usage (from anywhere):  bash webapp/run.sh        Windows: run it in Git Bash.
set -e
cd "$(dirname "$0")"

# 1. Find Python 3.
PY=""
for cmd in python3 python py; do
  if command -v "$cmd" >/dev/null 2>&1 && "$cmd" -c "import sys; sys.exit(sys.version_info < (3, 10))" 2>/dev/null; then
    PY="$cmd"; break
  fi
done
if [ -z "$PY" ]; then
  echo "Python 3.10+ not found. Install it from https://www.python.org/downloads/ and run this again."
  exit 1
fi

# 2. Virtual environment (.venv, gitignored).
if [ ! -d .venv ]; then
  echo "Creating virtual environment (.venv)..."
  "$PY" -m venv .venv
fi
if [ -x .venv/Scripts/python.exe ]; then VPY=.venv/Scripts/python.exe; else VPY=.venv/bin/python; fi

# 3. Install packages, only when requirements.txt changed since the last install.
if [ ! -f .venv/.installed ] || ! cmp -s requirements.txt .venv/.installed; then
  echo "Installing packages..."
  # A .venv made by uv has no pip; add it.
  "$VPY" -m pip --version >/dev/null 2>&1 || "$VPY" -m ensurepip --upgrade >/dev/null
  "$VPY" -m pip install --quiet --upgrade pip
  "$VPY" -m pip install --quiet -r requirements.txt
  cp requirements.txt .venv/.installed
fi

# 4. Settings: .env from the example (BACKEND=fake works with no other values).
if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env from .env.example (BACKEND=fake: no AWS needed)."
fi

# 5. Start. Show the addresses to open.
IP=$("$VPY" -c "import socket; s=socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.connect(('8.8.8.8', 80)); print(s.getsockname()[0])" 2>/dev/null || echo "<laptop-ip>")
echo ""
echo "  Laptop: http://127.0.0.1:8000"
echo "  Phone (same Wi-Fi): http://$IP:8000"
echo "  Demo accounts (fake mode): officer / officer1, alice / alice123. Demo helper: /dev"
echo "  Stop with Ctrl+C."
echo ""
exec "$VPY" -m uvicorn main:app --host 0.0.0.0 --port 8000
