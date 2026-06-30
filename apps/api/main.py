"""Borina Mesh — FastAPI application entry point."""

# Fix Windows cp1252 crash — must be FIRST before any imports.
import os, sys
os.environ["PYTHONUTF8"] = "1"
os.environ["PYTHONIOENCODING"] = "utf-8"
if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from dotenv import load_dotenv

from db import init_db
from routes import agents as agents_routes, chat as chat_routes, jobs as jobs_routes, activity as activity_routes, schedules as schedules_routes, analytics as analytics_routes, artifacts as artifacts_routes, logs as logs_routes, wiki as wiki_routes, briefs as briefs_routes, memory as memory_routes, workspace as workspace_routes, tasks as tasks_routes, stats as stats_routes, finance as finance_routes, finance_lifeos as finance_lifeos_routes, daily as daily_routes, calendar as calendar_routes, telegram as telegram_routes, files as files_routes, outlook as outlook_routes, outreach as outreach_routes, runs as runs_routes
from routers.sessions import router as sessions_router
from scheduler import scheduler_service

# Import agent modules to trigger registration
import agents.ceo  # noqa
import agents.scout  # noqa
import agents.researcher  # noqa
import agents.trader  # noqa
import agents.adset  # noqa
import agents.inbox  # noqa
import agents.qa_director  # noqa
import agents.finance  # noqa
import agents.planner  # noqa
import agents.builder  # noqa
import agents.applier  # noqa

load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """App startup/shutdown lifecycle."""
    print("Borina Mesh starting...")
    init_db()
    try:
        from db import engine as _engine
        from fleet_roster import seed_roster
        added = seed_roster(_engine)
        print(f"[fleet] roster seeded ({added} new agent rows)")
    except Exception as e:
        print(f"[fleet] roster seed error: {e}")
    try:
        from db import engine
        from stats_helper import fail_orphaned_running_jobs
        n = fail_orphaned_running_jobs(engine)
        if n:
            print(f"[jobs] failed {n} orphaned running job(s)")
    except Exception as e:
        print(f"[jobs] orphan recovery error: {e}")
    try:
        from dispatch.goal import recover_runs
        ng = recover_runs()
        if ng:
            print(f"[run] {ng} run(s)/goal(s) recovered after restart")
    except Exception as e:
        print(f"[run] recovery error: {e}")
    try:
        from wiki_engine.paths import bootstrap_schema_file, bootstrap_subcategory_files, ensure_vault_layout
        ensure_vault_layout()
        bootstrap_schema_file()
        bootstrap_subcategory_files()
        from wiki_engine.curator_memory import read_curator_memory
        read_curator_memory()
    except RuntimeError:
        print("[wiki] OBSIDIAN_VAULT_PATH not set — wiki engine disabled")
    except Exception as e:
        print(f"[wiki] bootstrap error: {e}")
    scheduler_service.start()
    scheduler_service.register_defaults()
    scheduler_service.register_trader_health()
    scheduler_service.register_finance_brief()
    scheduler_service.register_schedule_daily()
    scheduler_service.register_planner()
    scheduler_service.register_operator()
    scheduler_service.register_fleet_health()
    scheduler_service.register_apply_weekly()
    # Register the Telegram slash-command menu so /help /jobs /fleet /cancel
    # autocomplete in the client.
    try:
        from routes.telegram import set_my_commands
        if set_my_commands():
            print("[telegram] slash commands registered")
    except Exception as e:
        print(f"[telegram] setMyCommands error: {e}")
    # Background Telegram dispatch worker (crash-safe queue drain).
    try:
        from dispatch.worker import worker as dispatch_worker
        dispatch_worker.start()
        print("[dispatch-worker] started")
    except Exception as e:
        print(f"[dispatch-worker] failed to start: {e}")
    # Inbound getUpdates poller (only when TELEGRAM_DISPATCH_MODE=polling).
    try:
        from dispatch.poller import poller as telegram_poller
        telegram_poller.start()
    except Exception as e:
        print(f"[telegram-poller] failed to start: {e}")
    yield
    try:
        from dispatch.poller import poller as telegram_poller
        telegram_poller.stop()
    except Exception:
        pass
    try:
        from dispatch.worker import worker as dispatch_worker
        dispatch_worker.stop()
    except Exception:
        pass
    scheduler_service.stop()
    print("Borina Mesh shutting down...")


app = FastAPI(
    title="Borina",
    description="Multi-agent command center",
    version="0.1.0",
    lifespan=lifespan,
)

cors_origins = os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(agents_routes.router)
app.include_router(chat_routes.router)
# stats must register before jobs: GET /jobs/stats would otherwise be shadowed
# by GET /jobs/{job_id} (job_id:int) and 422 on the literal "stats".
app.include_router(stats_routes.router)
app.include_router(jobs_routes.router)
app.include_router(activity_routes.router)
app.include_router(schedules_routes.router)
app.include_router(analytics_routes.router)
app.include_router(artifacts_routes.router)
app.include_router(logs_routes.router)
app.include_router(wiki_routes.router)
app.include_router(briefs_routes.router)
app.include_router(memory_routes.router)
app.include_router(workspace_routes.router)
app.include_router(tasks_routes.router)
app.include_router(finance_routes.router)
app.include_router(finance_lifeos_routes.router)
app.include_router(daily_routes.router)
app.include_router(calendar_routes.router)
app.include_router(telegram_routes.router)
app.include_router(files_routes.router)
app.include_router(outlook_routes.router)
app.include_router(outreach_routes.router)
app.include_router(runs_routes.router)
app.include_router(sessions_router, prefix="/api/sessions", tags=["sessions"])


@app.get("/")
async def root():
    return RedirectResponse(url="/docs")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "borina-mesh"}


@app.get("/ping")
async def ping():
    return {"ping": "pong"}
