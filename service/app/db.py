from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from .config import settings

_client: AsyncIOMotorClient | None = None


def get_db() -> AsyncIOMotorDatabase:
    """Return a lazily-created Motor database handle.

    Used by standalone entry points (the ``.agent/tools/auctor_tools.py`` CLI dispatcher) that
    run outside the FastAPI app's lifespan, so they don't need a live ``app.state.db``. The
    FastAPI app itself continues to use ``app.state.db`` from its own lifespan-managed client.
    """
    global _client
    if _client is None:
        _client = AsyncIOMotorClient(settings.mongodb_uri)
    return _client[settings.mongodb_db]
