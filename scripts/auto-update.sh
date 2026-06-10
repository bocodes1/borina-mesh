#!/bin/bash
# Borina Mesh auto-updater
# Polls GitHub main branch; on new commit: pulls, rebuilds (smart), kickstarts services.
# Logs to ~/borina-mesh/logs/auto-update.log
set -u
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"

REPO_DIR="$HOME/borina-mesh"
LOG="$REPO_DIR/logs/auto-update.log"
LOCK="$REPO_DIR/logs/auto-update.lock.d"

mkdir -p "$REPO_DIR/logs"

# Single-instance lock (mkdir is atomic on macOS)
if ! mkdir "$LOCK" 2>/dev/null; then
    # Stale lock? Remove if older than 30 min
    if [ -d "$LOCK" ] && [ "$(find "$LOCK" -maxdepth 0 -mmin +30 2>/dev/null)" ]; then
        rm -rf "$LOCK" && mkdir "$LOCK" || exit 0
    else
        echo "$(date '+%F %T') skip: another updater running" >> "$LOG"
        exit 0
    fi
fi
trap 'rm -rf "$LOCK"' EXIT

log() { echo "$(date '+%F %T') $*" >> "$LOG"; }

cd "$REPO_DIR" || { log "ERR cannot cd $REPO_DIR"; exit 1; }

# Fetch quietly
git fetch origin main --quiet 2>>"$LOG" || { log "ERR git fetch failed"; exit 1; }

LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/main)

if [ "$LOCAL" = "$REMOTE" ]; then
    exit 0  # nothing to do, silent
fi

log "NEW COMMIT detected: $LOCAL -> $REMOTE"

# Detect what changed BEFORE pulling
CHANGED=$(git diff --name-only "$LOCAL" "$REMOTE")
log "changed files:"
echo "$CHANGED" | sed 's/^/  /' >> "$LOG"

WEB_CHANGED=0
API_CHANGED=0
PYDEPS_CHANGED=0
NPMDEPS_CHANGED=0
echo "$CHANGED" | grep -q '^apps/web/'           && WEB_CHANGED=1
echo "$CHANGED" | grep -q '^apps/api/'           && API_CHANGED=1
echo "$CHANGED" | grep -q '^apps/api/requirements.txt$' && PYDEPS_CHANGED=1
echo "$CHANGED" | grep -qE '^apps/web/(package\.json|package-lock\.json)$' && NPMDEPS_CHANGED=1

# Pull
git pull --ff-only origin main >>"$LOG" 2>&1 || { log "ERR git pull failed"; exit 1; }

# Backend deps
if [ "$PYDEPS_CHANGED" = "1" ]; then
    log "installing python deps..."
    "$REPO_DIR/apps/api/.venv/bin/pip" install -r "$REPO_DIR/apps/api/requirements.txt" >>"$LOG" 2>&1 \
        || { log "ERR pip install failed"; exit 1; }
fi

# Frontend deps + build
if [ "$WEB_CHANGED" = "1" ]; then
    cd "$REPO_DIR/apps/web" || exit 1
    if [ "$NPMDEPS_CHANGED" = "1" ]; then
        log "installing npm deps..."
        npm install >>"$LOG" 2>&1 || { log "ERR npm install failed"; exit 1; }
    fi
    log "building frontend..."
    npm run build >>"$LOG" 2>&1 || { log "ERR npm run build failed"; exit 1; }
fi

# Kickstart services
UID_NUM=$(id -u)
if [ "$API_CHANGED" = "1" ]; then
    log "restarting api..."
    launchctl kickstart -k "gui/$UID_NUM/com.borina.mesh-api" >>"$LOG" 2>&1
fi
if [ "$WEB_CHANGED" = "1" ]; then
    log "restarting web..."
    launchctl kickstart -k "gui/$UID_NUM/com.borina.mesh-web" >>"$LOG" 2>&1
fi

# Health check
sleep 6
HEALTH=$(curl -s -m 5 http://localhost:8000/health || echo "FAIL")
WEB=$(curl -s -m 5 -o /dev/null -w "%{http_code}" http://localhost:3000 || echo "FAIL")
log "post-update health: api=$HEALTH web=$WEB"
log "DONE $(git rev-parse --short HEAD)"
