"""FastAPI application entrypoint."""
from __future__ import annotations

import logging

import redis.asyncio as aioredis
from fastapi import FastAPI, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import text

from app.api.routes import dashboard, internal_wa, reminders, tasks
from app.core.config import settings
from app.db.session import engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

app = FastAPI(title="WAINT Backend", version="0.1.0", root_path="/api/v1")

# routers
app.include_router(internal_wa.router)
app.include_router(tasks.router)
app.include_router(reminders.router)
app.include_router(dashboard.router)

# Prometheus /metrics (lightweight; avoids middleware incompatibilities)
@app.get("/metrics")
async def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.get("/readyz")
async def readyz():
    checks = {"db": False, "redis": False}
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        checks["db"] = True
    except Exception:  # noqa: BLE001
        pass
    try:
        r = aioredis.from_url(settings.redis_url)
        await r.ping()
        checks["redis"] = True
    except Exception:  # noqa: BLE001
        pass
    ready = all(checks.values())
    return {"ready": ready, "checks": checks}
