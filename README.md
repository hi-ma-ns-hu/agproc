# AgProc

AgProc is an inbound and outbound voice agent for agricultural procurement. It calls farmers or takes their calls and holds an open, goal-directed conversation to collect and qualify a produce lot: what crop, how much, what grade, expected price, pickup location, availability. Rather than reading a rigid script, it reasons about what the farmer actually says, handles corrections and digressions, and reaches a justified procurement judgment by the end of the call. The structured record is a byproduct of the conversation, not a form the caller is walked through.

---

## What's here

- **FastAPI app factory** (`app.py`) with graceful shutdown (drains in-flight requests on
  `SIGTERM`, `/health/ready` returns 503 while draining) and a request-timing middleware.
- **Typed settings** (`config.py`, pydantic-settings) — loads from real env vars, falls back to
  `.env` locally, crashes loudly at startup if a required field is missing.
- **Structured JSON logging** (`shared/logging/`) — every log line is a single JSON object with
  per-request context (`trace_id`, `path`, `method`, ...) auto-attached via a `ContextVar`. The
  *same* formatter runs in every environment — dev sees exactly the same fields production would,
  just printed to stdout instead of shipped to a log backend.
- **Optional Redis cache** (`shared/storage/redis.py`) — safe no-op pattern: `redis` is never
  `None`, it's a stand-in object when `REDIS_URL` is unset, so callers never need to check before
  calling `redis.get(...)`/`redis.set(...)`. `REDIS_ENABLED` distinguishes "disabled" from a real
  result where that matters (e.g. health checks).
- **OpenLLMetry / OpenTelemetry tracing** (`shared/logging/tracing.py`) — built on
  `traceloop-sdk`, which bundles both LLM-aware instrumentation (rich spans for OpenAI calls:
  prompt, tokens, cost) and generic service instrumentation (Redis, HTTP, SQL). Required —
  `TRACELOOP_API_ENDPOINT` has no default, so the app won't boot without an OTLP endpoint
  configured (see [Tracing locally](#tracing-locally)). FastAPI itself is instrumented
  separately via `FastAPIInstrumentor` (the one thing `traceloop-sdk` doesn't bundle).
- **OpenAI client scaffold** (`shared/llm/client.py`) — a lazy `AsyncOpenAI` singleton. Not
  wired into anything yet; will get real trace/token data once a service actually calls it.
- **Ruff** (`pyproject.toml`) for lint + format — configured to match this codebase's existing
  style (2-space indent, single quotes), not Ruff's Black-compatible defaults.

---

## Project structure

```
agproc/
├── app.py                  # FastAPI factory: lifespan, health routes, trace middleware
├── config.py                # typed settings (pydantic-settings)
├── main.py                   # `from app import app` — entrypoint for `fastapi deploy`/`fastapi run`
├── routers/                  # empty — mount your API routes here
├── services/                  # empty — business logic goes here
├── shared/
│   ├── llm/
│   │   └── client.py            # lazy AsyncOpenAI singleton
│   ├── storage/
│   │   └── redis.py              # shared async Redis pool, no-op when REDIS_URL unset
│   └── logging/
│       ├── __init__.py            # JSON logging, per-request context binding
│       └── tracing.py              # OpenLLMetry/OTel init, no-op when unconfigured
├── pyproject.toml            # Ruff lint/format config
├── makefile                   # install / dev / lint / lint-fix / format
├── requirements.txt
└── .env.example
```

---

## Getting started

### Prerequisites
- Python 3.12+
- **Required**: a running Postgres instance, and an OTLP-speaking tracing backend (see
  [Tracing locally](#tracing-locally)) — the app won't boot without both configured.
- Optional: Redis.

### Setup
```bash
git clone <your-repo-url>
cd agproc

python -m venv venv
source venv/bin/activate
make install          # pip install -r requirements.txt

cp .env.example .env  # then point DATABASE_URL / TRACELOOP_API_ENDPOINT at something real
```

### Running
```bash
make dev              # uvicorn app:app --port 7000 --reload
```
- `GET /api/health` — liveness probe.
- `GET /api/health/ready` — readiness probe; reports Redis + database status, 503s while draining on shutdown.
- Interactive docs (dev only): http://localhost:7000/docs

### Linting / formatting
```bash
make lint       # ruff check .
make lint-fix   # ruff check . --fix
make format     # ruff format .
```

---

## Environment variables

See [`.env.example`](.env.example) / [`config.py`](config.py).

| Variable | Purpose |
|---|---|
| `APP_ENV` | `DEVELOPMENT` / `STAGING` / `PRODUCTION` (default `DEVELOPMENT`) |
| `LOG_LEVEL` | stdlib logging level (default `INFO`) |
| `REDIS_URL` | enables the shared Redis pool; unset = safe no-op, app runs cache-less |
| `DATABASE_URL` | **required** — Postgres connection string (`postgresql+asyncpg://...`); no fallback, app won't boot without it |
| `TRACELOOP_API_ENDPOINT` | **required** — OTLP HTTP endpoint for OpenLLMetry/OTel tracing (e.g. a local Jaeger instance); no fallback, app won't boot without it |

---

## Tracing locally

Tracing needs a backend to actually look at — a raw OTLP export isn't human-readable. **Jaeger**
is the easiest one to run just for local dev (single binary, OTLP receiver + UI bundled, no
Docker required — Docker's daemon is real overhead if you don't need it elsewhere):

1. Download the `jaeger-<version>-linux-amd64.tar.gz` binary from the
   [Jaeger releases page](https://github.com/jaegertracing/jaeger/releases), extract it.
2. Run it with no arguments — it defaults to an all-in-one setup with in-memory storage:
   ```bash
   ./jaeger
   ```
3. Set `TRACELOOP_API_ENDPOINT=http://localhost:4318` in `.env` (already the default there).
4. Run the app, hit a route, then open http://localhost:16686 and search for the `agproc` service.

Notes:
- Storage is in-memory — restarting Jaeger wipes all traces. Fine for local dev, not for keeping
  a history.
- Jaeger only handles traces, not logs or metrics. `Traceloop.init()` also tries to export
  metrics (token usage, request duration, etc. — e.g. `gen_ai.client.token.usage`); those have
  nowhere to land against Jaeger and fail with a harmless 404. A metrics backend (Prometheus, or
  Grafana Mimir) is a separate piece to add later if that data becomes useful.
- The same `TRACELOOP_API_ENDPOINT` mechanism works against any OTLP-compatible backend — swap
  in Grafana Tempo (or whatever prod uses) by pointing the env var elsewhere; no code changes.

---

## Deferred on purpose

A few things were deliberately left out rather than half-configured — add them when there's
actual code that needs them, not before:

- **Type checking** (pyright/mypy) — worth adding once `routers`/`services` have real logic with
  non-trivial data shapes to check. Ruff does not type-check.
- **Metrics backend** (Prometheus/Grafana Mimir) — `Traceloop.init()` already emits metrics
  (token usage, operation duration, ...); nothing currently collects them.
- **Tests** — no pytest setup yet; add `[tool.pytest.ini_options]` to `pyproject.toml` once
  there's logic worth testing.
