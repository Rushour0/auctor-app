from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient

from .config import settings

VERSION = "0.0.1"


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.mongo = AsyncIOMotorClient(settings.mongodb_uri)
    app.state.db = app.state.mongo[settings.mongodb_db]
    yield
    app.state.mongo.close()


app = FastAPI(title="Auctor Service", version=VERSION, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict:
    try:
        await app.state.db.command("ping")
        mongo_ok = True
    except Exception:
        mongo_ok = False
    return {"status": "ok" if mongo_ok else "degraded", "mongo": mongo_ok}


@app.get("/version")
async def version() -> dict:
    return {"auctor": VERSION, "env": settings.agency_env}


@app.get("/api/fleets")
async def list_fleets() -> dict:
    fleets = await app.state.db.fleet_runs.find({}, {"_id": 0}).to_list(length=100)
    return {"fleets": fleets}
