# FCC-mas Web Frontend — Engineering Plan

Internal-tool web frontend for the FCC Partners multi-agent research system.
This document is the working architecture spec. It does not contain a timeline.

---

## 1. Goals and constraints

### What this app actually is

A web wrapper around the existing CLI (`python3.13 main.py --input ...`)
that lets interns and analysts submit research / dictation / translation /
podcast tasks from a browser, watch them run in real time, and download
the produced `.docx`. Same agent code, same outputs — only the entry
point and the UX change.

### Hard constraints from the existing backend

| Constraint | Implication |
|---|---|
| Tasks take **1–5 minutes** (sometimes longer for medium mode + audio) | Synchronous request/response is impossible. Need async job + streaming progress. |
| CLI has **three interactive checkpoints** (`subject_review`, `planner.confirm`, `confirm_slides`) | Web flow must replicate these as proper UI states, not just blocking prompts. |
| Output is a **`.docx` file**, sometimes large (with images for `speech_ppt`) | Browser must download as binary; server needs to retain files long enough for user to retrieve. |
| Cost tracking exists per task (`utils/cost_tracker.py`) | Costs must surface in UI — IB analysts will ask. |
| Audio uploads can be **>4 minutes** (ffmpeg slicing) | Multipart upload with progress, server-side processing time visible. |
| `.env` contains real API keys | They never leave the server. Frontend talks to our backend only. |

### Non-functional bar

This is an Investment Banking internal tool. The polish bar is higher
than a generic side project:

- Typography correct (no system fallbacks, no inconsistent weights)
- No layout shift, no janky loading states
- Errors surfaced with context, not generic "Something went wrong"
- Keyboard navigation works end-to-end
- Dark mode acceptable, light mode mandatory (printing / screenshots
  go to clients sometimes — light mode renders correctly)

---

## 2. Stack decisions

Each row lists the choice, runners-up considered, and why this one.

### Frontend

| Layer | Choice | Why this and not the alternative |
|---|---|---|
| Build tool | **Vite** | Native ESM dev server, sub-second HMR. Next.js considered and rejected: its strengths (SSR, file routing, edge) don't apply to an authed internal tool that hits a Python API. Adding it costs complexity for zero return. |
| Language | **TypeScript (strict)** | Catches API shape mismatches at compile time. `strict: true` + `noUncheckedIndexedAccess: true` from day one. |
| Framework | **React 18** | Pragmatic call: largest ecosystem, best AI-tooling support, shadcn/ui is React-native. Vue/Svelte are technically nicer but the network effects on React are decisive. |
| Routing | **TanStack Router** | Type-safe routes + search params, file-based when wanted. Preferred over react-router-dom for new projects in 2026 because it eliminates a class of runtime bugs (untyped params) that bite IB users harder than retail. |
| Styling | **Tailwind CSS** (v4) | Utility-class. No CSS Modules, no styled-components, no Emotion — they all add a JS-runtime cost or context-switching tax. Tailwind compiles down, period. |
| UI components | **shadcn/ui** (Radix + Tailwind) | Copy-into-repo model (not an npm dep). Means we own the component code and can tune to the FCC visual style. Used by Linear, Vercel, Cal.com — the polish bar this project needs. |
| Icons | **Lucide React** | shadcn/ui default. Consistent stroke weights. |
| Forms | **react-hook-form + Zod** | RHF for performance (uncontrolled by default), Zod for schema-validate input AND parse API responses. Same schema both sides via `zod-to-typescript`. |
| Server-state | **TanStack Query** (React Query) | Caches, retries, deduplicates, manages loading/error/refetch. Without this you write the same boilerplate in every component. |
| Client-state | **Zustand** | For the small amount of cross-component state (current user, theme, in-flight task IDs). Redux is overkill at this scale. Context is fine for theme but Zustand handles more elegantly with the same boilerplate. |
| Data tables | **TanStack Table** | Headless. Needed for task history view. |
| Charts (if needed) | **Recharts** or **Visx** | Recharts for simple, Visx for anything bespoke. Cost trends, agent run distributions — analysts will want these eventually. |
| Date handling | **date-fns** | Tree-shakeable, immutable. Day.js is fine but date-fns wins on tree-shake. |
| Markdown rendering | **react-markdown + remark-gfm** | For showing agent log output if we surface it. |
| Tests | **Vitest + Testing Library** | Vitest matches Vite's dev experience. Playwright for E2E (later). |
| Lint / format | **ESLint + Prettier** | Standard. `eslint-config-prettier` to avoid conflicts. |

### Backend

| Layer | Choice | Why |
|---|---|---|
| HTTP framework | **FastAPI** | Python-native (matches agent code), async-friendly, auto-generated OpenAPI for the frontend's typed client, Pydantic models reusable across HTTP boundary. |
| ASGI server | **Uvicorn + Gunicorn (workers)** in prod, plain Uvicorn in dev | Standard FastAPI deployment. |
| Background task runtime | **`asyncio.create_task` + in-process job registry** to start; **Celery + Redis** when usage grows | Tasks are long-running but few (small team). In-process suffices until concurrency demands real queueing. Document the migration path. |
| Real-time progress | **Server-Sent Events (SSE)** | One-way server → client, plain HTTP, no special infra. WebSocket considered: we don't need bidirectional streaming, and SSE auto-reconnects on flaky networks. |
| Auth | **Phase 1: shared secret + IP allowlist. Phase 2: Google OAuth (Workspace SSO).** | FCC almost certainly uses Google Workspace. Skip session servers, use signed JWT cookies. |
| File storage | **Filesystem on the server**, paths recorded in a job-result store | Output is already going to `output/`. Wrap that with per-task IDs. S3 only if multi-instance deploy. |
| Job/result persistence | **SQLite (via SQLAlchemy)** | Single file, durable, sufficient for ≤1k jobs/day. Postgres swap-in is trivial via SQLAlchemy. |
| Schema validation | **Pydantic v2** | Same models on HTTP boundary AND inside agent code if useful. |
| API client codegen | **openapi-typescript** | Reads `/openapi.json` from FastAPI, generates a typed TS client. No drift between backend schema and frontend types. |

### What is deliberately not in the stack

- **GraphQL** — REST + OpenAPI gives us typed access with less moving parts.
- **Microservices / message bus** — premature.
- **A CSS-in-JS library** — pure Tailwind.
- **Storybook** — useful at larger scale; until we have >40 components, not worth the build overhead.
- **A design system library (MUI, Ant Design, Chakra)** — they lock in a visual style. shadcn/ui owns less of that decision. MUI specifically: prevents the polish bar we want.

---

## 3. Repository layout

The web app lives inside this repo, not a separate one. Reason: the
agent code is the source of truth, and we want the backend to import
`agents.*` directly without packaging gymnastics.

```
FCC-mas/
├── agents/                  # existing — untouched
├── utils/                   # existing — untouched
├── formatters/              # existing — untouched
├── main.py                  # CLI entry — kept working
├── translate.py             # CLI entry — kept working
├── output/                  # existing — agent docx output
├── web/
│   ├── api/                 # FastAPI app
│   │   ├── __init__.py
│   │   ├── main.py          # FastAPI() instance, middleware, lifespan
│   │   ├── config.py        # settings (env vars)
│   │   ├── db.py            # SQLAlchemy engine + session
│   │   ├── models.py        # ORM models: Job, JobEvent, User
│   │   ├── schemas.py       # Pydantic request/response models
│   │   ├── deps.py          # FastAPI dependencies (auth, db session)
│   │   ├── routes/
│   │   │   ├── __init__.py
│   │   │   ├── auth.py
│   │   │   ├── jobs.py      # POST /jobs, GET /jobs/{id}, GET /jobs/{id}/events (SSE)
│   │   │   ├── files.py     # GET /jobs/{id}/download
│   │   │   └── uploads.py   # POST /uploads/audio
│   │   ├── services/
│   │   │   ├── job_runner.py    # bridges to agents.* and streams events
│   │   │   ├── progress_bus.py  # in-process pub/sub for SSE
│   │   │   └── auth_service.py
│   │   └── tests/
│   ├── frontend/            # React app
│   │   ├── public/
│   │   ├── src/
│   │   │   ├── main.tsx
│   │   │   ├── App.tsx
│   │   │   ├── router.tsx
│   │   │   ├── api/             # generated client + hooks
│   │   │   │   ├── client.ts
│   │   │   │   ├── generated.ts # from openapi-typescript
│   │   │   │   └── hooks.ts     # TanStack Query wrappers
│   │   │   ├── components/
│   │   │   │   ├── ui/          # shadcn/ui — owned source
│   │   │   │   └── domain/      # task forms, progress log, results
│   │   │   ├── routes/          # TanStack Router file routes
│   │   │   ├── stores/          # Zustand stores
│   │   │   ├── lib/             # utils (formatters, type guards)
│   │   │   └── types/
│   │   ├── index.html
│   │   ├── package.json
│   │   ├── tsconfig.json
│   │   ├── vite.config.ts
│   │   ├── tailwind.config.ts
│   │   └── components.json      # shadcn/ui config
│   ├── docker-compose.yml   # optional — for Postgres swap-in
│   └── README.md            # web-specific dev setup
└── FRONTEND_PLAN.md         # this file
```

Two npm workspaces are tempting (shared types between back and front)
but unnecessary — `openapi-typescript` already bridges that. Keep it
simple.

---

## 4. Backend architecture

### 4.1 The job lifecycle

```
Client                          API                          Worker (asyncio)
  │                              │                                │
  │ POST /jobs {type, params} ──▶│                                │
  │                              │ create Job(status=queued)      │
  │  ◀── 201 {job_id}            │                                │
  │                              │ schedule background task ─────▶│
  │                              │                                │ load agent module
  │ GET /jobs/{id}/events (SSE)─▶│                                │ run agent
  │  ◀── event: started          │  ◀── publish via progress_bus  │ emit progress
  │  ◀── event: planning         │  ◀── ...                       │ ...
  │  ◀── event: searching 3/6    │                                │
  │  ◀── event: writing report   │                                │
  │  ◀── event: completed        │                                │ save docx, set status=done
  │                              │                                │
  │ GET /jobs/{id}/download ────▶│                                │
  │  ◀── docx bytes              │                                │
```

### 4.2 Data model (SQLAlchemy)

```python
class Job(Base):
    id:           str (uuid)              # primary key
    user_id:      str
    type:         str                     # company_info | person_info | podcast | …
    instruction:  str                     # raw user input
    mode:         str                     # short | medium
    status:       Literal["queued", "needs_confirm", "running",
                          "needs_subject_review", "needs_slide_confirm",
                          "done", "failed", "cancelled"]
    output_path:  str | None              # set on success
    log_path:     str | None              # .log sidecar
    cost_usd:     float                   # accumulated
    error:        str | None
    created_at, started_at, completed_at: datetime
    metadata:     JSON                    # type-specific extras

class JobEvent(Base):
    id:        int
    job_id:    FK Job.id
    kind:      str   # progress | confirm_request | error | log
    payload:   JSON
    ts:        datetime
```

Events are persisted (not just streamed) so that a user reopening
the browser mid-job can replay the stream.

### 4.3 SSE design

Endpoint: `GET /jobs/{job_id}/events?since={event_id}`

- Initial connection: server sends all persisted events for the job
  (catch up), then keeps connection open and streams new ones.
- Heartbeat every 15s (`event: ping`) to keep proxies from closing.
- Standard SSE format:
  ```
  id: 42
  event: progress
  data: {"node": "run_search", "round": 3, "max_rounds": 6}
  ```
- Frontend uses native `EventSource` API, reconnects automatically.

### 4.4 Bridging agent code to the web

The existing agents `print(...)` to stdout. Two options:

1. **Capture stdout** — wrap each agent run in a `redirect_stdout`
   context and parse lines. Brittle; print formats may change.
2. **Add a structured logger / callback hook to agent state** —
   refactor agents so that nodes call `state["progress_cb"](event)`
   when present. Backward-compatible: CLI path passes a no-op callback
   that also prints to stdout.

**Choose option 2.** It is a small, contained refactor: add an
optional `progress_cb: Callable[[dict], None] | None` to each agent's
`run(...)` signature, call it at meaningful points (round transitions,
node entries, error states). The web API supplies a callback that
publishes to the SSE bus; the CLI supplies `None` and gets the
existing stdout behavior.

Affected files: `agents/*.py` (one callback wiring per agent),
`router.py` (pass through), `utils/react_loop.py` (call at round
boundaries).

### 4.5 Interactive checkpoints

Three points in the existing CLI require user input mid-task:

| Checkpoint | When | UI shape |
|---|---|---|
| `subject_review` (`utils/subject_review.py`) | After STT, before planner | Modal listing suspected mishears with suggested fixes; user accepts / edits / skips. Job status: `needs_subject_review`. |
| `planner.confirm` | After task parsing | Tabular list of parsed tasks with edit/delete/merge controls. Job status: `needs_confirm`. |
| `confirm_slides` (`speech_ppt`) | After script parse, before DALL-E spend | Slides preview with titles + bullets + notes. User can cancel before image generation. Job status: `needs_slide_confirm`. |

Backend pattern: agent calls `progress_cb({"kind": "confirm_request",
"payload": {...}})` and **awaits a `confirm_response` event from the
bus** (timeout: 30 min, then auto-cancel). The frontend submits
`POST /jobs/{id}/confirm` with the user's choice. The bus delivers
that to the awaiting coroutine, which resumes the agent.

This means agents must be refactored to be `async` at those points,
or the checkpoint runs on a thread and uses a sync queue. The
`async` refactor is cleaner; do it once and forever.

### 4.6 File uploads (audio)

- `POST /uploads/audio` — multipart, 100 MB cap initially
- Server stores at `web/api/uploads/{user_id}/{uuid}.m4a` (or original ext)
- Returns `{upload_id, path}`; job submission references it by id
- Cleanup job: delete uploads >30 days old

### 4.7 Auth

**Phase 1 (acceptable for closed beta):** `X-API-Key` header with a
shared secret, plus IP allowlist via reverse proxy. Cookie-based
session for the browser side.

**Phase 2 (before broader rollout):** Google OAuth via Workspace SSO.
Use `Authlib` server-side; restrict email domain to FCC's. Sign JWT
with rotation. Store `User` row keyed by email.

### 4.8 Cost surfacing

The existing `utils/cost_tracker.py` is a singleton. For the web
version it must be per-job:

- Instantiate a `CostTracker` per job inside `job_runner.py`
- Pass it through agent calls (already takes `tracker.record_claude(...)`
  in code — make it injectable rather than global singleton)
- Persist final `cost_usd` on `Job`
- Surface in UI: per-job cost + monthly running total

This is a small refactor in `utils/cost_tracker.py` (singleton →
class, with a thread-local accessor for back-compat with CLI).

---

## 5. Frontend architecture

### 5.1 Pages

| Route | Purpose |
|---|---|
| `/` | Dashboard — recent jobs, monthly cost, "new task" CTA |
| `/new` | Task submission form (type picker → form per type) |
| `/jobs` | Job history with filters (date, type, intern, status) |
| `/jobs/:id` | Job detail: live progress log, current status, action buttons (confirm, cancel, download) |
| `/settings` | API keys (server-side), default intern name, theme |
| `/login` | OAuth entry |

### 5.2 State boundaries

- **Server state** (TanStack Query): jobs, events, user profile,
  cost summaries. Cached, deduped, auto-refetched on focus.
- **Client state** (Zustand): theme, current user identity (after
  hydration from cookie), in-flight SSE connections, transient form
  drafts. Persist theme + intern default to `localStorage`.
- **Form state** (react-hook-form local): bounded to a form's
  lifetime, never lifted unless multiple components need it.

Anti-patterns to avoid: `useEffect` chains for derived state
(compute it during render), `useContext` for anything that isn't
truly global, mirroring server state into Zustand.

### 5.3 SSE consumption pattern

```tsx
// hooks/useJobEvents.ts
function useJobEvents(jobId: string) {
  const queryClient = useQueryClient();

  useEffect(() => {
    const es = new EventSource(`/api/jobs/${jobId}/events`);
    es.addEventListener("progress", (e) => {
      const data = JSON.parse(e.data);
      // append to local event list (TanStack Query setQueryData)
      queryClient.setQueryData(["job", jobId, "events"], (prev = []) => [...prev, data]);
    });
    es.addEventListener("completed", () => {
      queryClient.invalidateQueries({ queryKey: ["job", jobId] });
      es.close();
    });
    return () => es.close();
  }, [jobId]);
}
```

One `EventSource` per open job-detail page. Background tab keeps the
connection open (browser handles).

### 5.4 The confirm UX

Critical to get right — this is where the LLM and the user negotiate.

- **Subject review**: present a list of suspected mishears as cards.
  Each card shows: detected token, context snippet, suggested fix
  (if any), confidence. User can accept-all (button), edit a fix
  inline, or reject the suggestion. Submit replaces tokens in the
  transcript before planner runs.
- **Task confirm**: tabular view of parsed tasks. Inline edit on
  the instruction field. Buttons: delete row, merge selected rows,
  add new row. Confirm sends the final list back. This mirrors the
  CLI's `y / n / [N] / d[N] / a / m a,b` but with mouse + keyboard.
- **Slide confirm**: vertical card list. Each slide shows title +
  bullets + speaker notes. Toggle to mark a slide as
  "non-structured" (skip image gen). Cost preview ("8 slides ×
  ~$0.04 = ~$0.32 for image generation") shown before submission.

### 5.5 Component design principles

- **Composition over configuration**: prefer `<Card>{children}</Card>`
  over `<Card title="..." body="..." />`.
- **Server state stays in hooks**, not props. A `JobStatusBadge` takes
  a `jobId`, not a `status` — it reads from cache.
- **Loading states are first-class**. No bare spinners. Use skeleton
  components matching the final layout.
- **Errors are first-class**. Every fetch hook surfaces error state
  the component must handle; no swallowed exceptions.
- **Empty states are designed**. "No tasks yet" page has a CTA, not
  a blank screen.

### 5.6 Typography and visual

- Use **Inter Variable** for UI (free, excellent at all weights).
  Self-host with `@fontsource-variable/inter` (no external CDN —
  it's an internal tool).
- For the docx download preview area, render with a system serif
  (Georgia / Source Serif) to match Word output spirit.
- Spacing scale: Tailwind default (4px base).
- Color: shadcn/ui default + a single accent token tuned to FCC's
  red `#EE0000` (already used in `WordBuilder` for podcast titles).
  Define `--accent` in `globals.css` so accent usages are centralized.

---

## 6. Critical UX flows (storyboards)

### 6.1 Submit a research task

1. User on `/new`. Type picker: 6 options (`company_info`, `person_info`,
   `podcast`, `translation`, `dictation`, `verbal_cleanup`, `speech_ppt`).
   Default highlighted: `company_info`.
2. Form fields adapt to type. For `company_info`: instruction
   textarea, mode (short/medium), optional intern override.
3. Submit → `POST /jobs` returns `{job_id}`. Navigate to `/jobs/:id`.
4. Job detail page opens SSE; first events render immediately.
5. If task type runs through planner → after parse, status flips to
   `needs_confirm` and a modal appears with the parsed task list.
6. User confirms → status flips to `running`. Progress log streams.
7. On completion: status flips to `done`, download button enables,
   cost shown, log link enabled.

### 6.2 STT-driven flow (audio → research)

1. User uploads `.m4a` via dropzone. Progress bar during upload.
2. Submit job referencing `upload_id` + intern + mode.
3. Backend: STT runs → status `needs_subject_review`.
4. UI: modal listing detected proper nouns with suspicion flags. User
   accepts or edits.
5. Submit corrections → planner runs → status `needs_confirm`.
6. Modal: parsed task list. User accepts → tasks dispatch one by one.
7. Each task gets a sub-row in the job detail showing its own
   progress. Aggregate cost rolls up.

### 6.3 Multi-task batch

The CLI dispatches a list of tasks from one input. Web version
either:
- (a) Treats the whole input as **one job** with sub-tasks (matches
  CLI mental model, simpler URL), or
- (b) Creates **N independent jobs** linked by a `batch_id`.

Choose (a) for v1. Sub-tasks render as nested rows in the job detail.
This lets us keep the single-job state machine and avoid batch
coordination logic.

---

## 7. Non-functional concerns

### 7.1 Errors and logging

- Backend: structured JSON logs via `structlog`. Every request gets
  a request_id; every job gets a job_id; both appear in logs.
- Frontend: catch React render errors via error boundary; send to
  Sentry. Network errors surface in-UI via TanStack Query's `onError`.
- Add `Sentry` server + browser SDK. Free tier sufficient.

### 7.2 Observability

- `/healthz` endpoint
- Prometheus metrics endpoint (`/metrics`) — even if not scraped yet,
  having `prometheus_fastapi_instrumentator` plugged in costs nothing
- Browser perf: web-vitals to Sentry

### 7.3 Security checklist

- HTTPS only in prod
- `httponly + secure + samesite=lax` cookies
- CSRF token for state-changing endpoints (FastAPI middleware)
- Rate-limit per-user (`slowapi`)
- Pydantic strict-mode on input bodies
- File-type sniff on audio upload (don't trust the extension)
- Filesystem path traversal: never join user-supplied paths;
  always pass through a UUID indirection (`upload_id` → server-side
  resolved path)
- Don't echo back full filesystem paths in error messages
- API keys (Anthropic / Tavily / OpenAI) stay in server `.env`,
  never reach the browser

### 7.4 Deployment

Minimum viable: one Linux VM (DigitalOcean, Hetzner) with:

- Caddy as reverse proxy (auto-TLS via Let's Encrypt)
- Backend: Uvicorn workers under `systemd`
- Frontend: static build served by Caddy
- SQLite file with daily backup to S3 (or `restic` to a NAS)
- `ffmpeg` installed (STT requirement)

Frontend build is `npm run build` → `dist/` → copy to Caddy's serve
directory. Cache-bust via Vite's hashed filenames.

CI: GitHub Actions running lint + type-check + test on push, deploy
on tag.

---

## 8. Phased delivery

No dates. Order is what matters.

### Phase 0 — Backend refactors (no UI yet)

1. Add `progress_cb` callback hook to each agent's `run(...)`.
2. Convert `cost_tracker` from singleton to per-job instance (keep
   thread-local accessor for CLI back-compat).
3. Extract interactive checkpoints into hooks that can either block
   on stdin (CLI) or await a bus message (web).
4. Verify CLI behavior is unchanged with `progress_cb=None`.

This is the most architecturally important step. It removes the
coupling between the agent code and a specific I/O surface.

### Phase 1 — Backend HTTP surface

1. FastAPI app skeleton, settings, DB.
2. `Job` + `JobEvent` models, migrations.
3. `POST /jobs` for `company_info` (one agent first), `GET /jobs/{id}`,
   `GET /jobs/{id}/events` (SSE), `GET /jobs/{id}/download`.
4. In-process job runner using `asyncio.create_task`.
5. Smoke test: curl-driven end-to-end. No frontend yet.

### Phase 2 — Frontend MVP

1. Vite + React + TS scaffold; Tailwind; shadcn/ui init.
2. `openapi-typescript` codegen wired to backend.
3. Layout shell (sidebar + header). Auth via shared secret cookie.
4. `/new` for `company_info` only. `/jobs/:id` with live SSE.
5. Polish to IB standard before going further.

### Phase 3 — All agent types

1. Add `person_info`, `translation`, `podcast`, `dictation`,
   `verbal_cleanup` to `/new`.
2. Form variants per type.
3. Backend `routes/jobs.py` dispatches to the right agent.

### Phase 4 — Interactive checkpoints

1. `needs_confirm` state + planner modal.
2. `needs_subject_review` + transcript correction UI.
3. `needs_slide_confirm` + slides preview (for `speech_ppt`).

### Phase 5 — Audio + batch

1. Audio upload with progress.
2. Multi-task batch jobs (sub-tasks).
3. STT cost surfacing.

### Phase 6 — History, cost, polish

1. `/jobs` history with filters.
2. `/` dashboard with cost trends.
3. Search across past tasks.
4. Light/dark theme toggle.

### Phase 7 — Production hardening

1. Google OAuth (replace shared secret).
2. Sentry + Prometheus wired up.
3. Backup + restore tested.
4. Rate limits, security headers, CSRF.

---

## 9. Open questions (need product decisions before phase 4)

1. **Job retention**: how long do output `.docx` files stay
   downloadable? 30 days? Forever? Affects storage planning.
2. **Cost limits**: should a user be blocked from running a `medium`
   mode task that would cost >$5? Per-user monthly cap?
3. **Multi-intern**: when an intern submits a task with multiple
   intern names (currently `--intern "Justin,Neil"`), is the job
   "owned" by the submitter or shared? Affects access control.
4. **Output naming**: file names currently include intern name and
   date. Should multi-intern shared tasks change the convention?
5. **Mobile**: is iPhone use a goal or is desktop-only acceptable?
   The current dictation flow on iPhone (AirDrop screenshot, paste)
   suggests mobile would be valued.
6. **CY's read-only view**: does the boss need a separate read-only
   dashboard showing what's been delivered, or just shared file
   access?
7. **Document history**: do users need to see *previous versions*
   of a task's output (re-runs)?

---

## 10. Risks

| Risk | Mitigation |
|---|---|
| Agent code paths that don't yet emit progress events appear stuck | Add a periodic heartbeat from `react_loop` and other long nodes; expose model latency in events. |
| SSE through corporate proxies sometimes broken | Fallback to polling `GET /jobs/{id}` every 2s if SSE connection fails N times. |
| User closes browser mid-confirm | Persist `needs_confirm` state with a TTL; expose pending confirmations on the dashboard so user can resume. |
| Concurrent runs exceed Anthropic rate limits | Per-user concurrency cap (semaphore) in `job_runner`, configurable. |
| Frontend build artifacts drift from backend schema | CI step that fails when `openapi.json` changes without committing regenerated TS types. |
| docx files leak between users | Always resolve download paths via `Job.id` ownership check, never via direct filesystem path. |

---

## 11. References and prior art to mimic

These all use the React + Tailwind + shadcn/ui + FastAPI/Node stack
or close to it. Worth studying their UI density and progress UX:

- **Linear** — task list density, keyboard nav, command palette
- **Vercel dashboard** — build-log streaming UX is essentially what
  we need for the live progress view
- **Anthropic Console / OpenAI Playground** — token / cost surfacing
  patterns
- **Cursor / Continue** — long-running agent UI patterns

---

## 12. Document conventions

- This file is the source of truth for the web side. Updates require
  a brief rationale at the top of the changed section.
- Code references use `path/to/file:line` (matching repo convention).
- Decisions that are reversed should leave the prior reasoning intact
  with a strike-through and a dated note.
