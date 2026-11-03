"""PulseWatch API - manage monitors and show their status.

Postgres: monitors + check history (durable storage)
Redis:    latest status of each monitor (fast reads), rate limiting
The actual website checks are done by worker.py, not this file.
"""
import json
import os
import secrets
import socket
from contextlib import asynccontextmanager
from pathlib import Path

import asyncpg
import redis.asyncio as aioredis
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, HttpUrl

from common import is_public_url

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:pass@localhost:5432/db")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
API_KEY = os.getenv("API_KEY", "")
INSTANCE = os.getenv("INSTANCE_NAME", socket.gethostname())
MAX_MONITORS = int(os.getenv("MAX_MONITORS", "50"))
WRITE_LIMIT_PER_MIN = int(os.getenv("WRITE_LIMIT_PER_MIN", "20"))
INDEX_HTML = Path(__file__).parent / "static" / "index.html"


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.pg = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
    app.state.redis = aioredis.from_url(REDIS_URL, decode_responses=True)
    yield
    await app.state.pg.close()
    await app.state.redis.aclose()


app = FastAPI(title="PulseWatch", lifespan=lifespan)


@app.middleware("http")
async def add_instance_header(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Served-By"] = INSTANCE  # shows which backend answered
    return response


def require_key(x_api_key: str = Header(default="")):
    # if API_KEY is not set, everything is rejected (fail closed)
    if not API_KEY or not secrets.compare_digest(x_api_key.encode(), API_KEY.encode()):
        raise HTTPException(status_code=401, detail="invalid or missing X-API-Key")


async def rate_limit(request: Request):
    # nginx sets the X-Real-IP header; otherwise we would only see nginx's own IP
    ip = request.headers.get("x-real-ip") or request.client.host
    r = request.app.state.redis
    key = f"rl:{ip}"
    count = await r.incr(key)
    if count == 1:
        await r.expire(key, 60)
    if count > WRITE_LIMIT_PER_MIN:
        raise HTTPException(status_code=429, detail="too many requests")


class MonitorIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    url: HttpUrl
    interval_s: int = Field(default=30, ge=10, le=3600)


@app.get("/", include_in_schema=False)
async def dashboard():
    return FileResponse(INDEX_HTML)


@app.get("/health")
async def health():
    try:
        await app.state.pg.fetchval("SELECT 1")
        await app.state.redis.ping()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"unhealthy: {exc}")
    hb = await app.state.redis.get("worker:heartbeat")
    return {"status": "ok", "instance": INSTANCE, "worker_alive": hb is not None}


@app.post("/api/monitors", status_code=201, dependencies=[Depends(require_key)])
async def create_monitor(body: MonitorIn, request: Request):
    url = str(body.url)
    if not await is_public_url(url):
        raise HTTPException(status_code=400, detail="url must resolve to a public address")
    await rate_limit(request)
    pg = request.app.state.pg
    if await pg.fetchval("SELECT count(*) FROM monitors") >= MAX_MONITORS:
        raise HTTPException(status_code=400, detail="monitor limit reached")
    row = await pg.fetchrow(
        "INSERT INTO monitors (name, url, interval_s) VALUES ($1, $2, $3) "
        "RETURNING id, name, url, interval_s",
        body.name, url, body.interval_s,
    )
    return dict(row)


@app.get("/api/monitors")
async def list_monitors(request: Request):
    rows = await request.app.state.pg.fetch(
        "SELECT id, name, url, interval_s FROM monitors ORDER BY id"
    )
    keys = [f"status:{r['id']}" for r in rows]
    values = await request.app.state.redis.mget(keys) if keys else []
    return [
        {**dict(r), "status": json.loads(v) if v else None}
        for r, v in zip(rows, values)
    ]


async def _ensure_exists(request: Request, monitor_id: int):
    ok = await request.app.state.pg.fetchval(
        "SELECT 1 FROM monitors WHERE id = $1", monitor_id
    )
    if not ok:
        raise HTTPException(status_code=404, detail="monitor not found")


@app.get("/api/monitors/{monitor_id}/history")
async def history(request: Request, monitor_id: int, limit: int = Query(50, ge=1, le=500)):
    await _ensure_exists(request, monitor_id)
    rows = await request.app.state.pg.fetch(
        "SELECT checked_at, up, status_code, latency_ms, error FROM checks "
        "WHERE monitor_id = $1 ORDER BY checked_at DESC LIMIT $2",
        monitor_id, limit,
    )
    return [dict(r) for r in rows]


@app.get("/api/monitors/{monitor_id}/stats")
async def stats(request: Request, monitor_id: int):
    await _ensure_exists(request, monitor_id)
    row = await request.app.state.pg.fetchrow(
        "SELECT count(*) AS total, count(*) FILTER (WHERE up) AS ups, "
        "avg(latency_ms) FILTER (WHERE up) AS avg_ms "
        "FROM checks WHERE monitor_id = $1 AND checked_at > now() - interval '24 hours'",
        monitor_id,
    )
    total = row["total"]
    return {
        "checks_24h": total,
        "uptime_pct_24h": round(100 * row["ups"] / total, 2) if total else None,
        "avg_latency_ms_24h": round(float(row["avg_ms"]), 1) if row["avg_ms"] else None,
    }


@app.delete("/api/monitors/{monitor_id}", status_code=204, dependencies=[Depends(require_key)])
async def delete_monitor(request: Request, monitor_id: int):
    await _ensure_exists(request, monitor_id)
    await request.app.state.pg.execute("DELETE FROM monitors WHERE id = $1", monitor_id)
    await request.app.state.redis.delete(f"status:{monitor_id}", f"due:{monitor_id}")
