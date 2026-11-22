"""
Will I Make It — FastAPI Application Entry Point
=================================================
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import os

import app.config  # Deterministically resolves and loads backend/.env regardless of process CWD

from app.routers import health, energy, routes, chargers, trips, sarvam, neo4j
from app.services.charger_service import init_db
from app.services.outbox_service import init_outbox_db
from app.services.sync_worker import start_sync_worker, stop_sync_worker
from app.services.neo4j_service import is_enabled, get_driver, seed_graph, close_driver


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    print("[Startup] Initialising SQLite database...")
    init_db()
    init_outbox_db()
    print("[Startup] SQLite ready.")

    # Start background transactional outbox sync worker
    start_sync_worker(interval_seconds=5.0)

    if is_enabled():
        print("[Startup] Neo4j is enabled (NEO4J_ENABLED=true) — attempting connection...")
        driver = get_driver()
        if driver:
            if os.environ.get("NEO4J_AUTO_SEED", "false").strip().lower() in ("true", "1", "yes"):
                print("[Startup] Neo4j connected. Seeding graph per NEO4J_AUTO_SEED...")
                seed_graph()
            else:
                print("[Startup] Neo4j connected. Automatic graph seeding disabled (NEO4J_AUTO_SEED is not true).")
        else:
            print("[Startup] Neo4j connection failed. Running in demo fallback mode.")
    else:
        print("[Startup] Neo4j is disabled by default (NEO4J_ENABLED is false) — running in demo mode.")

    yield
    # Shutdown
    print("[Shutdown] Cleaning up...")
    stop_sync_worker(timeout=3.0)
    close_driver()


app = FastAPI(
    title="Will I Make It — EV Route Planner API",
    description=(
        "Risk-aware, explainable EV route planner for Indian conditions. "
        "Predicts trip energy, compares routes, accounts for charger reliability. "
        "\n\n⚠️ **Demo Mode**: All routes and charger data are SIMULATED. "
        "Energy estimates use a physics model with synthetic uncertainty. "
        "P90 coverage is NOT validated against real Indian EV data."
    ),
    version="1.0.0-mvp",
    lifespan=lifespan,
)

# CORS — strict allowlist, credentials enabled without wildcard '*'
default_origins = [
    "http://localhost:5173",
    "http://localhost:3000",
    "http://127.0.0.1:5173",
    "https://will-i-make-it.vercel.app",
    "https://will-i-make-it-one.vercel.app",
    "https://will-i-make-l6tim64aw-shivansh-574f.vercel.app",
]
custom_origins = [o.strip() for o in os.environ.get("CORS_ALLOWED_ORIGINS", "").split(",") if o.strip()]
allowed_origins = list(dict.fromkeys(default_origins + custom_origins))

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(health.router)
app.include_router(energy.router)
app.include_router(routes.router)
app.include_router(chargers.router)
app.include_router(trips.router)
app.include_router(sarvam.router)
app.include_router(neo4j.router)


@app.get("/")
def root():
    return {
        "service": "Will I Make It — EV Route Planner",
        "docs": "/docs",
        "health": "/api/health",
        "demo_routes": "/api/routes/demo",
    }
