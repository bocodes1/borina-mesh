"""Borina Mesh — FastAPI application entry point."""

import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from dotenv import load_dotenv

from db import init_db
from routes import agents as agents_routes, chat as chat_routes, jobs as jobs_routes, activity as activity_routes, schedules as schedules_routes, analytics as analytics_routes, artifacts as artifacts_routes, logs as logs_routes, wiki as wiki_routes
from scheduler import scheduler_service

# Import agent modules to trigger registration
import agents.ceo  # noqa
import agents.scout  # noqa
import agents.polymarket  # noqa
import agents.researcher  # noqa
import agents.trader  # noqa
import agents.adset  # noqa
import agents.inbox  # noqa
import agents.qa_director  # noqa

load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """App startup/shutdown lifecycle."""
    print("Borina Mesh starting...")
    init_db()
    try:
        from wiki_engine.paths import bootstrap_schema_file, bootstrap_subcategory_files, ensure_vault_layout
        ensure_vault_layout()
        bootstrap_schema_file()
        bootstrap_subcategory_files()
        # Bootstrap curator memory file too
        from wiki_engine.curator_memory import read_curator_memory
        read_curator_memory()  # side effect: writes initial file if missing
    except RuntimeError:
        print("[wiki] OBSIDIAN_VAULT_PATH not set — wiki engine disabled")
    except Exception as e:
        print(f"[wiki] bootstrap error: {e}")
    scheduler_service.start()
    scheduler_service.register_defaults()
    yield
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
app.include_router(jobs_routes.router)
app.include_router(activity_routes.router)
app.include_router(schedules_routes.router)
app.include_router(analytics_routes.router)
app.include_router(artifacts_routes.router)
app.include_router(logs_routes.router)
app.include_router(wiki_routes.router)


@app.get("/")
async def root():
    return RedirectResponse(url="/docs")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "borina-mesh"}
