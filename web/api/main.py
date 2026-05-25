"""
web/api/main.py — FastAPI app entry point.

Run in dev:
    python3.13 -m uvicorn web.api.main:app --reload --port 8000

Run in prod (later phases):
    python3.13 -m gunicorn web.api.main:app \
        -k uvicorn.workers.UvicornWorker -w 1 -b 127.0.0.1:8000

One worker only — the in-process progress bus (web/api/services/progress_bus.py)
assumes single process for now. Phase 7+ when scale matters: swap the bus
for Redis pub/sub and lift the worker cap.
"""

import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Add repo root to sys.path so the agent modules (`agents`, `utils`,
# `config`, etc. at the project root) are importable without an
# editable install. Mirrors the `sys.path.insert(...)` pattern that
# every agent already uses.
_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

from web.api.config import settings   # noqa: E402
from web.api.db import init_db        # noqa: E402
from web.api.routes import jobs as jobs_routes      # noqa: E402
from web.api.routes import uploads as uploads_routes  # noqa: E402
from web.api.services.progress_bus import bus       # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("web.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Startup / shutdown hooks.

    Startup:
      - Create SQLite tables if missing.
      - Bind the running event loop to the progress bus so worker
        threads can hop back into it via run_coroutine_threadsafe.

    Shutdown: nothing yet — pending SSE streams self-cancel when
    asyncio.CancelledError propagates.
    """
    init_db()
    bus.bind_loop(asyncio.get_running_loop())
    log.info("FCC-mas API ready on http://%s:%s", settings.host, settings.port)
    yield


app = FastAPI(
    title="FCC-mas API",
    description="Internal HTTP surface for the FCC Partners multi-agent system.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(jobs_routes.router)
app.include_router(uploads_routes.router)


@app.get("/healthz", tags=["meta"])
def healthz() -> dict[str, str]:
    return {"status": "ok"}
