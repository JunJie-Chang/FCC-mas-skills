"""
web/api/config.py — Settings loaded from environment / .env.

Pydantic Settings means values can be overridden by env vars at runtime
without touching code. The .env at the repo root already holds the
agent-side API keys; this module just adds the web-layer knobs on top.
"""

from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


_REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_REPO_ROOT / ".env"),
        env_prefix="WEB_",
        extra="ignore",
    )

    # ── Server ────────────────────────────────────────────────────────
    host: str = "127.0.0.1"
    port: int = 8000
    # CORS origins for the React dev server. Production deploy adds the
    # internal host. Open list during Phase 1 (localhost dev only).
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"]
    )

    # ── Persistence ───────────────────────────────────────────────────
    # SQLite file lives under web/api/data/ so it travels with the code
    # but stays out of the agent output tree. Override with WEB_DB_URL
    # in production to point at Postgres.
    db_url: str = f"sqlite:///{_REPO_ROOT / 'web' / 'api' / 'data' / 'jobs.db'}"

    # ── Job runtime ───────────────────────────────────────────────────
    # Soft cap to keep one user from blocking the whole node on
    # concurrent agent runs. Each agent run holds one Anthropic and
    # Tavily quota slice; this is the bottleneck, not CPU.
    max_concurrent_jobs: int = 4
    # Sweep interval for cleaning up finished job event queues
    queue_idle_seconds: int = 600  # 10 minutes


settings = Settings()
