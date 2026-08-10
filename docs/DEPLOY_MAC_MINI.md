# Deploying Borina Mesh on the Mac Mini

Goal: Borina Mesh running 24/7 on the Mac Mini, using your **Claude Max
subscription** (no API key), reachable from any device over Tailscale, and
auto-starting on boot.

> **Why not Docker?** The bundled `docker-compose.yml` runs the API inside a
> container, but subscription mode needs the `claude` CLI, which isn't in the
> container. On the Mac Mini we therefore run the **API natively** so it can
> shell out to `claude`. The web frontend runs natively too (simplest), though
> it *could* run in Docker pointed at the host API.

---

## 0. Prerequisites (one time)

```bash
# Homebrew packages
brew install python@3.11 node tmux        # tmux powers the Terminal/sessions feature
brew install pango cairo libffi gdk-pixbuf # native libs for PDF (WeasyPrint)

# Claude Code CLI — the auth source for subscription mode
npm install -g @anthropic-ai/claude-code
claude            # run once, complete the login flow, then Ctrl-C
which claude      # NOTE THIS PATH — you need it for launchd (step 5)

# Tailscale (if not already on the Mac)
brew install --cask tailscale
# then sign in via the Tailscale app; note the Mac's tailnet name, e.g.
#   mac-mini.tailXXXX.ts.net   (Settings → "This device")
```

Verify the toolchain:

```bash
python3.11 --version   # 3.11.x
node --version         # v20+ fine
tmux -V
claude --version
```

---

## 1. Get the code

```bash
git clone https://github.com/bocodes1/borina-mesh.git ~/borina-mesh
cd ~/borina-mesh
git checkout feature/finance-deepdive   # current full app (panes + finance)
git pull
```

> If you already cloned it, just `git fetch && git checkout feature/finance-deepdive && git pull`.

---

## 2. Backend (API) — native

```bash
cd ~/borina-mesh/apps/api
python3.11 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt   # weasyprint imports OK here thanks to brew libs

cp .env.example .env
```

Edit `apps/api/.env`:

```ini
# Leave BLANK to use the claude CLI subscription (recommended on the Mac Mini).
ANTHROPIC_API_KEY=

DATABASE_URL=sqlite:///./borina.db

# The web origin(s) you'll load in a browser. With the Next proxy these are
# only needed for safety/direct calls — include localhost + your tailnet host.
CORS_ORIGINS=http://localhost:3000,http://mac-mini.tailXXXX.ts.net:3000

# Obsidian vault root — reports sync here. Set to your real vault, or leave
# blank to disable the wiki engine cleanly.
OBSIDIAN_VAULT_PATH=/Users/clawd/.openclaw/workspace
```

Optional — Telegram **notifications** (job-completion / digests; outbound only):

```ini
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
BORINA_DASHBOARD_URL=http://mac-mini.tailXXXX.ts.net:3000
```

Smoke-test it natively before wiring autostart:

```bash
cd ~/borina-mesh/apps/api
PYTHONUTF8=1 .venv/bin/python -m uvicorn main:app --host 0.0.0.0 --port 8000
# in another terminal:
curl -s localhost:8000/health           # {"status":"ok",...}
curl -s localhost:8000/jobs/stats        # {"active":0,"queued":0,"today":N}
# Ctrl-C when satisfied
```

---

## 3. Frontend (web) — native production build

```bash
cd ~/borina-mesh/apps/web
npm install
cp .env.local.example .env.local
# .env.local: the web server (on the Mac) proxies to the API on the same host
echo 'NEXT_PUBLIC_API_URL=http://localhost:8000' > .env.local
npm run build
```

Smoke-test:

```bash
npm start -- -H 0.0.0.0 -p 3000
# open http://localhost:3000 on the Mac, or http://mac-mini.tailXXXX.ts.net:3000 from your phone
# Ctrl-C when satisfied
```

---

## 4. Remote access (Tailscale)

Tailscale gives the Mac a stable hostname/IP on your private tailnet. From any
device with Tailscale (phone, laptop), open:

```
http://mac-mini.tailXXXX.ts.net:3000
```

The browser only ever talks to the **web** server on `:3000`; Next proxies
`/api/*` to `localhost:8000` on the Mac, so the API never needs to be exposed
and there are no CORS hops. The dashboard is fully responsive.

> Don't want to remember the port? Add a Tailscale `serve` rule to put it on
> 443: `tailscale serve --bg 3000` → then just `https://mac-mini.tailXXXX.ts.net`.

---

## 5. Auto-start on boot (launchd)

Two LaunchAgents live in `deploy/`. They run at login and restart on crash.

**Before installing**, fix two machine-specific things in each plist:

1. Replace `__HOME__` with your home dir (run `echo $HOME`, e.g. `/Users/clawd`).
2. In `com.borina.api.plist`, make sure `PATH` includes the dir from
   `which claude` (step 0) **and** the Homebrew bin. Subprocess mode fails
   silently if `claude` isn't on launchd's PATH.

Install:

```bash
cd ~/borina-mesh
# substitute __HOME__ → your home, then copy into place
sed "s|__HOME__|$HOME|g" deploy/com.borina.api.plist > ~/Library/LaunchAgents/com.borina.api.plist
sed "s|__HOME__|$HOME|g" deploy/com.borina.web.plist > ~/Library/LaunchAgents/com.borina.web.plist

launchctl load -w ~/Library/LaunchAgents/com.borina.api.plist
launchctl load -w ~/Library/LaunchAgents/com.borina.web.plist
```

Manage:

```bash
launchctl list | grep borina                 # see both jobs
tail -f ~/borina-mesh/apps/api/launchd-api.log
tail -f ~/borina-mesh/apps/web/launchd-web.log

# restart after a code update:
git pull
launchctl kickstart -k gui/$(id -u)/com.borina.api
launchctl kickstart -k gui/$(id -u)/com.borina.web

# stop / remove:
launchctl unload -w ~/Library/LaunchAgents/com.borina.api.plist
```

> Keep-alive runs the jobs whenever you're logged in. To run **without** being
> logged in (true headless boot), move the plists to `/Library/LaunchDaemons/`
> and load them as root — but LaunchAgents + auto-login is simpler for a
> single-user Mac Mini.

---

## 6. Update workflow

```bash
cd ~/borina-mesh
git pull
# API deps changed? cd apps/api && .venv/bin/pip install -r requirements.txt
# Web changed?       cd apps/web && npm install && npm run build
launchctl kickstart -k gui/$(id -u)/com.borina.api
launchctl kickstart -k gui/$(id -u)/com.borina.web
```

---

## What works where

| Feature | Mac Mini | Windows dev |
|---|---|---|
| Agent chat (SDK subprocess) | ✅ | ✅ |
| PDF reports (WeasyPrint) | ✅ (brew GTK) | falls back to markdown |
| Terminal / tmux sessions | ✅ | ❌ (no tmux) |
| Polymarket tab (`:8080` embed) | ✅ if your bot runs there | shows "not running" |
| Scheduler / activity / analytics | ✅ | ✅ |

---

## Not yet built: inbound Telegram control

Today Telegram is **outbound only** (notifications). Messaging the bot to
*dispatch* an agent and get the result back is a separate feature — see the
"Telegram control bot" track. The web dashboard over Tailscale already gives
you full any-device control in the meantime.
