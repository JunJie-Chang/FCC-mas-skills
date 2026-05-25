# FCC-mas Web Layer

HTTP / SSE surface around the existing agent code. See `FRONTEND_PLAN.md`
at the repo root for the full architecture spec.

## Layout

```
web/
├── api/                FastAPI backend
│   ├── main.py         app entry — `uvicorn web.api.main:app`
│   ├── config.py       pydantic-settings, reads .env at repo root
│   ├── db.py           SQLAlchemy 2.0 engine, init_db()
│   ├── models.py       Job + JobEvent ORM models
│   ├── schemas.py      Pydantic v2 request / response shapes
│   ├── routes/jobs.py  POST /jobs, GET /jobs/{id}, /events (SSE), /download, /log
│   ├── services/
│   │   ├── progress_bus.py  per-job asyncio.Queue + JobEvent persistence
│   │   └── job_runner.py    bridges Job rows to agent.run() with per-job CostTracker
│   ├── data/           SQLite file lives here (gitignored)
│   └── requirements.txt
└── README.md           this file
```

## Run (dev)

```bash
python3.13 -m pip install -r web/api/requirements.txt
python3.13 -m uvicorn web.api.main:app --reload --port 8000
```

`.env` at repo root supplies the agent API keys (already in place for
the CLI). Web-layer settings can override via `WEB_*` env vars or the
same `.env`. See `web/api/config.py:Settings`.

## Smoke test

```bash
# 1. Submit a job
curl -s -X POST http://127.0.0.1:8000/jobs \
  -H 'Content-Type: application/json' \
  -d '{"type":"company_info","instruction":"查 NVIDIA NVDA 股價走勢與市值","intern_name":"Justin","mode":"short"}' \
  | python3.13 -m json.tool

# 2. Stream events (open in another terminal)
curl -N http://127.0.0.1:8000/jobs/<job_id>/events

# 3. Status poll
curl -s http://127.0.0.1:8000/jobs/<job_id> | python3.13 -m json.tool

# 4. Download the .docx once status=done
curl -o report.docx http://127.0.0.1:8000/jobs/<job_id>/download
```

## OpenAPI

Auto-generated at runtime:

- `GET /openapi.json` — schema (used by `openapi-typescript` to generate
  the frontend's TS client)
- `GET /docs` — Swagger UI
- `GET /redoc` — ReDoc

## Phase 1 scope

This phase ships the backend HTTP surface only, and only the
`company_info` agent type. Other types (person_info, podcast,
translation, dictation, verbal_cleanup, speech_ppt) return HTTP 501
until enabled in Phase 3+. No authentication yet — listen on `127.0.0.1`
only during dev. The React frontend comes in Phase 2.

## Concurrency model

- One uvicorn worker (the in-process progress bus assumes single-process
  fanout — see `progress_bus.py`).
- Agents run in `asyncio.to_thread` worker threads — blocking SDK calls
  don't stall the event loop.
- Per-job `CostTracker` and `progress_cb` bound for the worker's lifetime
  via `utils/cost_tracker.use_tracker()` and the agent's `progress_cb`
  parameter (from Phase 0 refactors).
- `JobEvent` rows persist every event so SSE clients can reconnect with
  `Last-Event-ID` and resume mid-job without loss.
