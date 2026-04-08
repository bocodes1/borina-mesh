#!/usr/bin/env bash
set -euo pipefail

# Borina Mesh — Mac Mini initial setup
# Usage: bash scripts/bootstrap.sh

echo "=== Borina Mesh Bootstrap ==="

# Check prerequisites
command -v docker >/dev/null 2>&1 || { echo "Docker required but not installed. https://docs.docker.com/get-docker/"; exit 1; }
command -v docker compose >/dev/null 2>&1 || command -v docker-compose >/dev/null 2>&1 || { echo "Docker Compose required"; exit 1; }

cd "$(dirname "$0")/.."

# Create .env if missing
if [ ! -f .env ]; then
  echo "Creating .env from template..."
  cat > .env <<'EOF'
# Anthropic API key — required
ANTHROPIC_API_KEY=

# Path to Obsidian vault (will be mounted read-only)
OBSIDIAN_VAULT_PATH=/Users/clawd/.openclaw/workspace
EOF
  echo "→ Edit .env and add your ANTHROPIC_API_KEY"
  exit 1
fi

# Start services
echo "Building and starting services..."
docker compose up -d --build

echo ""
echo "=== Borina Mesh is running ==="
echo "Dashboard: http://localhost:3000"
echo "API docs:  http://localhost:8000/docs"
echo ""
echo "Logs: docker compose logs -f"
echo "Stop: docker compose down"
