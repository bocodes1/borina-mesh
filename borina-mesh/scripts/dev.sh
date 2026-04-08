#!/usr/bin/env bash
set -euo pipefail

# Run backend and frontend locally for development
# Usage: bash scripts/dev.sh

cd "$(dirname "$0")/.."

echo "=== Borina Mesh Dev Mode ==="

# Backend
(cd apps/api && python -m uvicorn main:app --reload --port 8000) &
API_PID=$!

# Frontend
(cd apps/web && npm run dev) &
WEB_PID=$!

trap "kill $API_PID $WEB_PID 2>/dev/null || true" EXIT INT TERM

echo "API:  http://localhost:8000"
echo "Web:  http://localhost:3000"
echo "Press Ctrl+C to stop"

wait
