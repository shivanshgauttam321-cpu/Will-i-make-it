"""
Will I Make It — FastAPI Application Entry Point
=================================================
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import os

from dotenv import load_dotenv

load_dotenv()

from app.routers import health, energy, routes, chargers, trips, sarvam
from app.services.charger_service import init_db
from app.services.neo4j_service import get_driver, seed_graph


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    print("[Startup] Initialising SQLite database...")
    init_db()
    print("[Startup] SQLite ready.")

    if os.environ.get("NEO4J_URI"):
        print("[Startup] Neo4j URI found — attempting connection...")
        driver = get_driver()
        if driver:
            print("[Startup] Neo4j connected. Seeding graph...")
            seed_graph()
        else:
            print("[Startup] Neo4j connection failed. Running in demo fallback mode.")
    else:
        print("[Startup] NEO4J_URI not set — running in demo fallback mode (no Neo4j).")

    yield
    # Shutdown
    print("[Shutdown] Cleaning up...")


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

# CORS — allow frontend dev and production deployments
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
        "https://will-i-make-it.vercel.app",
        "http://localhost:5173",
        "https://will-i-make-it-one.vercel.app",
        "https://will-i-make-l6tim64aw-shivansh-574f.vercel.app",
        "*",  # Allow cross-origin requests from deployed frontend (e.g. Vercel, Render)
    ],
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


@app.get("/")
def root():
    return {
        "service": "Will I Make It — EV Route Planner",
        "docs": "/docs",
        "health": "/api/health",
        "demo_routes": "/api/routes/demo",
    }
