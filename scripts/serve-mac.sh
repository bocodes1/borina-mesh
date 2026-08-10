#!/usr/bin/env bash
set -euo pipefail

# Borina Mesh — native production-style run on macOS (subscription/subprocess
# auth, no Docker, no API key). Use this to verify the full stack before
# wiring launchd autostart (see docs/DEPLOY_MAC_MINI.md).
#
# Usage: bash scripts/serve-mac.sh

cd "$(dirname "$0")/.."
ROOT="$(pwd)"

echo "=== Borina Mesh (native macOS) ==="

# --- API ---
if [ ! -d apps/api/.venv ]; then
  echo "apps/api/.venv missing — run: cd apps/api && python3.11 -m venv .venv && .venv/bin/pip install -r requirements.txt"
  exit 1
fi
( cd apps/api && PYTHONUTF8=1 .venv/bin/python -m uvicorn main:app --host 0.0.0.0 --port 8000 ) &
API_PID=$!

# --- Web (build once if no production build exists, then start) ---
if [ ! -d apps/web/.next ]; then
  echo "Building web (first run)..."
  ( cd apps/web && npm run build )
fi
( cd apps/web && node node_modules/next/dist/bin/next start -H 0.0.0.0 -p 3000 ) &
WEB_PID=$!

trap 'kill $API_PID $WEB_PID 2>/dev/null || true' EXIT INT TERM

echo ""
echo "API:  http://localhost:8000  (docs at /docs)"
echo "Web:  http://localhost:3000"
echo "Tailscale: http://<this-mac>.tailXXXX.ts.net:3000"
echo "Ctrl-C to stop both."

wait
