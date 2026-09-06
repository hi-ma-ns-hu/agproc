# AgProc

AgProc is a multi-channel agricultural procurement agent — it can call farmers or take their calls (voice), or converse with them over text (messaging), holding an open, goal-directed conversation to collect and qualify a produce lot: what crop, how much, what grade, expected price, pickup location, availability. Rather than reading a rigid script, it reasons about what the farmer actually says, handles corrections and digressions, and reaches a justified procurement judgment by the end of the conversation.

---

## What's here

- **FastAPI app factory** (`app.py`) with graceful shutdown (drains in-flight requests on `SIGTERM`, `/health/ready` returns 503 while draining) and a request-timing middleware.
- **Typed settings** (`config.py`, pydantic-settings) — loads from real env vars, falls back to `.env` locally, crashes loudly at startup if a required field is missing.
- **Procurement conversation engine** (`services/`) — the actual agent logic, channel-agnostic:
  - `agent.py` — `conversation()`, the one-turn state machine: builds the prompt, calls the LLM
    (with an optional tool-calling round-trip), applies extracted updates to the claimed record,
    qualifies the lot once it's complete, and fires a closing turn once qualification lands.
  - `contract.py` / `schema.py` — the LLM's structured output contract (`ConversationOutput`,
    `ExtractedField`, `MeasureValue`) versus the internal record (`ClaimedRecord`,
    `ConversationState`, `Qualification`).
  - `extraction.py` — validates and applies each extracted field to the record; converts quantity/price into canonical units (`unit.py`) and returns `(applied_count, rejected)` so a farmer's unusable answer (e.g. "60 bags" — not a real weight unit) gets fed back into the *next* turn's prompt instead of silently dropped.
  - `qualification.py` — decides DECLINE / NEGOTIATE / FORWARD / INCOMPLETE against reference data (`refdata.py`, `refdata.sample.yml`).
  - `prompt.py` — builds the system prompt per channel (`voice` / `messaging`): reference data, outstanding low-confidence fields, rejected-field callouts, and the reached verdict, all rendered into one template.
  - `validation.py` — what's required per crop, what's still missing, what's known but unconfirmed.
- **Structured JSON logging** (`utils/logging/`) — every log line is a single JSON object with per-request context (`trace_id`, `path`, `method`, ...) auto-attached via a `ContextVar`. The *same* formatter runs in every environment — dev sees exactly the same fields production would, just printed to stdout instead of shipped to a log backend.
- **Optional Redis cache** (`utils/storage/redis.py`) — safe no-op pattern: `redis` is never `None`, it's a stand-in object when `REDIS_URL` is unset, so callers never need to check before calling `redis.get(...)`/`redis.set(...)`. `REDIS_ENABLED` distinguishes "disabled" from a real result where that matters (e.g. health checks).
- **OpenLLMetry / OpenTelemetry tracing** (`utils/logging/tracing.py`) — built on `traceloop-sdk`, which bundles both LLM-aware instrumentation (rich spans for OpenAI calls: prompt, tokens, cost) and generic service instrumentation (Redis, HTTP, SQL). Required — `TRACELOOP_API_ENDPOINT` has no default, so the app won't boot without an OTLP endpoint configured (see [Tracing locally](#tracing-locally)). FastAPI itself is instrumented separately via `FastAPIInstrumentor` (the one thing `traceloop-sdk` doesn't bundle).
- **LLM client with retries** (`utils/llm/client.py`) — a lazy `AsyncOpenAI` singleton behind `get_llm_response()`, which retries transient/rate-limit/empty-parse failures with backoff and raises `LLMCallFailed` once retries are exhausted. This is what `services/agent.py` calls.
- **Test suite** (`tests/`, pytest) — mirrors `services/` and `utils/` one-to-one; covers extraction/validation edge cases, qualification bands, prompt rendering, and the full `conversation()` turn engine with a mocked LLM.
- **Manual conversation harness** (`evals/harness.py`) — a keyboard-driven REPL against the real `conversation()` engine (and, unless mocked, the real OpenAI API) for poking at agent behavior by hand, over the `voice` channel by default.
- **Ruff** (`pyproject.toml`) for lint + format — configured to match this codebase's existing style (2-space indent, single quotes), not Ruff's Black-compatible defaults.

---

## Project structure

```
agproc/
├── app.py                    # FastAPI factory: lifespan, health routes, trace middleware
├── config.py                  # typed settings (pydantic-settings)
├── main.py                     # `from app import app` — entrypoint for `fastapi deploy`/`fastapi run`
├── routers/                    # empty — mount your API routes here
├── services/                    # 
│   ├── agent.py                    # conversation() — one turn: extract, update, qualify, respond
│   ├── contract.py                  # LLM structured-output contract
│   ├── schema.py                     # internal record/state types
│   ├── extraction.py                  # validate + apply extracted fields, canonicalize units
│   ├── unit.py                         # weight/price unit conversion (kg, tonne -> quintal)
│   ├── qualification.py                # DECLINE / NEGOTIATE / FORWARD / INCOMPLETE logic
│   ├── validation.py                    # required / missing / unconfirmed fields per crop
│   ├── prompt.py                         # per-channel system prompt template + renderers
│   ├── refdata.py                         # loads refdata.yml, falls back to refdata.sample.yml
│   ├── refdata.sample.yml                  # example crop reference data (prices, grades, margins)
│   ├── tools.py                             # tool-calling definitions (currently empty)
│   └── __init__.py                          # re-exports the package's public API
├── evals/
│   └── harness.py               # keyboard REPL for manually driving conversation()
├── tests/                       # pytest suite, mirrors services/ and utils/
│   ├── services/
│   └── utils/
├── utils/
│   ├── llm/
│   │   └── client.py             # AsyncOpenAI singleton + get_llm_response() with retry/backoff
│   ├── storage/
│   │   └── redis.py               # shared async Redis pool, no-op when REDIS_URL unset
│   └── logging/
│       ├── __init__.py             # JSON logging, per-request context binding
│       └── tracing.py               # OpenLLMetry/OTel init, no-op when unconfigured
├── pyproject.toml             # Ruff lint/format config + pytest config
├── makefile                    # install / dev / lint / lint-fix / format / test
├── requirements.txt
└── .env.example
```

---

## Getting started

### Prerequisites
- Python 3.12+
- **Required**: a running Postgres instance, an OTLP-speaking tracing backend (see
  [Tracing locally](#tracing-locally)), and an OpenAI API key — the app won't boot without all
  three configured.
- Optional: Redis.

### Setup
```bash
git clone <your-repo-url>
cd agproc

python -m venv venv
source venv/bin/activate
make install          # pip install -r requirements.txt

cp .env.example .env  # then point DATABASE_URL / TRACELOOP_API_ENDPOINT / OPENAI_API_KEY at something real
```

### Running
```bash
make dev              # uvicorn app:app --port 7000 --reload
```
- `GET /api/health` — liveness probe.
- `GET /api/health/ready` — readiness probe; reports Redis + database status, 503s while draining on shutdown.
- Interactive docs (dev only): http://localhost:7000/docs

### Trying the conversation agent by hand
```bash
python -m evals.harness
```
Type as the farmer; `/state` dumps the claimed record and verdict at any point, `/quit` exits.
This calls the real OpenAI API (no mocking), so it needs `OPENAI_API_KEY` set. The harness drives
the `voice` channel; pass `channel='messaging'` to `conversation()` to exercise the other one.

### Testing
```bash
make test                                    # pytest
make test file=tests/services/agent.py       # one file
make test file=tests/services/agent.py func=test_turn_applies_extracted_updates  # one test
```

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
| `OPENAI_API_KEY` | **required** — used by `utils/llm/client.py`'s `AsyncOpenAI` client; no fallback, app won't boot without it |
| `PROCUREMENT_MODEL` | OpenAI model used for conversation turns (default `gpt-4o`) |
| `CURRENCY` | currency symbol used in prompts and price rendering (default `₹`) |
| `WEIGHT` | canonical weight unit quantity/price get converted to (default `quintal`) |

---

## Reference data

`services/refdata.py` loads `services/refdata.yml` if it exists, otherwise falls back to the
committed `services/refdata.sample.yml`. `refdata.yml` is gitignored — that's where real crop
prices, grades, and per-crop margins/minimums go; the sample file is just enough (`wheat`,
`onion`) to run the harness and tests without real business data.

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

- **Type checking** (pyright/mypy) — worth adding once `routers/` has real logic with
  non-trivial data shapes to check. Ruff does not type-check.
- **Metrics backend** (Prometheus/Grafana Mimir) — `Traceloop.init()` already emits metrics
  (token usage, operation duration, ...); nothing currently collects them.
- **API routes** (`routers/`) — the conversation engine isn't wired to an HTTP/websocket
  endpoint yet; `evals/harness.py` is the only way to drive it today.
