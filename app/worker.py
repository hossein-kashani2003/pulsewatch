"""Worker: checks websites and writes the results to Postgres and Redis.

Scheduling with Redis: the key due:<id> is created with SET NX and TTL = interval.
Whichever worker manages to create the key performs that check, so even with
several workers running at once, each check runs only once.
"""
import asyncio
import json
import os
import signal
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import asyncpg
import httpx
import redis.asyncio as aioredis

from common import is_public_url

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:pass@localhost:5432/db")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
REQUEST_TIMEOUT = float(os.getenv("CHECK_TIMEOUT_S", "5"))
RETENTION_DAYS = int(os.getenv("RETENTION_DAYS", "7"))
HEARTBEAT_FILE = Path("/tmp/hb")  # healthcheck probe: Docker checks this file's mtime
WORKER_ID = uuid.uuid4().hex[:8]


async def run_check(client: httpx.AsyncClient, monitor) -> dict:
    started = time.perf_counter()
    status_code, error, up = None, None, False
    try:
        if not await is_public_url(monitor["url"]):
            raise RuntimeError("blocked: target is not a public address")
        resp = await client.get(monitor["url"])  # redirect is not followed (security)
        status_code = resp.status_code
        up = status_code < 400
        if not up:
            error = f"HTTP {status_code}"
    except Exception as exc:
        error = (str(exc) or type(exc).__name__)[:200]
    latency = int((time.perf_counter() - started) * 1000)
    return {"up": up, "status_code": status_code, "latency_ms": latency, "error": error}


async def check_and_save(pg, r, client, sem, monitor):
    async with sem:
        res = await run_check(client, monitor)
    await pg.execute(
        "INSERT INTO checks (monitor_id, up, status_code, latency_ms, error) "
        "VALUES ($1, $2, $3, $4, $5)",
        monitor["id"], res["up"], res["status_code"], res["latency_ms"], res["error"],
    )
    res["checked_at"] = datetime.now(timezone.utc).isoformat()
    await r.set(f"status:{monitor['id']}", json.dumps(res), ex=600)
    print(f"[{WORKER_ID}] {monitor['url']} up={res['up']} {res['latency_ms']}ms", flush=True)


async def cleanup(pg, r):
    # only one worker per hour runs the cleanup
    if await r.set("lock:cleanup", WORKER_ID, nx=True, ex=3600):
        result = await pg.execute(
            "DELETE FROM checks WHERE checked_at < now() - make_interval(days => $1)",
            RETENTION_DAYS,
        )
        print(f"[{WORKER_ID}] cleanup: {result}", flush=True)


async def main():
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)

    pg = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
    r = aioredis.from_url(REDIS_URL, decode_responses=True)
    sem = asyncio.Semaphore(10)
    headers = {"User-Agent": "PulseWatch/1.0"}
    print(f"[{WORKER_ID}] worker started", flush=True)

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT, headers=headers) as client:
        while not stop.is_set():
            HEARTBEAT_FILE.touch()
            await r.set("worker:heartbeat", WORKER_ID, ex=15)
            try:
                monitors = await pg.fetch("SELECT id, url, interval_s FROM monitors")
                due = []
                for m in monitors:
                    if await r.set(f"due:{m['id']}", 1, nx=True, ex=m["interval_s"]):
                        due.append(m)
                await asyncio.gather(*(check_and_save(pg, r, client, sem, m) for m in due))
                await cleanup(pg, r)
            except Exception as exc:  # a single error must not kill the worker
                print(f"[{WORKER_ID}] tick error: {exc!r}", flush=True)
            try:
                await asyncio.wait_for(stop.wait(), timeout=2)
            except asyncio.TimeoutError:
                pass

    await pg.close()
    await r.aclose()
    print(f"[{WORKER_ID}] stopped", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
