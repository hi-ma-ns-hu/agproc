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
- **Voice pipeline** (`services/voice/`, `routers/voice.py`) — real phone calls via Twilio Media Streams + [pipecat](https://github.com/pipecat-ai/pipecat), decoupled from procurement specifics by dependency injection (`run_conversation_pipeline` takes the conversation engine and state builder as parameters, so another domain could reuse the same pipeline later):
  - `provider.py` — builds the Sarvam STT/TTS services and Silero VAD for one call.
  - `orchestrator.py` — wires transport → STT → `ConversationBridge` (turns transcriptions into `conversation()` calls) → TTS → transport into a pipecat `Pipeline`, handling both inbound and outbound call direction.
  - `language.py` — `VoiceLanguage`, a provider-agnostic enum wrapping pipecat's own `Language` values (not raw Sarvam wire-format strings), so the configured `VOICE_LANGUAGE` also drives *what language the LLM replies in*, not just TTS pronunciation.
  - `routers/voice.py` — the Twilio webhook endpoints (`/voice/incoming`, `/voice/outgoing`) returning TwiML that opens a `<Stream>` back to `/voice/stream`, and the `websocket` route that starts the pipeline per call.
- **Structured JSON logging** (`utils/logging/`) — every log line is a single JSON object with per-request context (`trace_id`, `path`, `method`, ...) auto-attached via a `ContextVar`. The *same* formatter runs in every environment — dev sees exactly the same fields production would, just printed to stdout instead of shipped to a log backend.
- **Optional Redis cache** (`utils/storage/redis.py`) — safe no-op pattern: `redis` is never `None`, it's a stand-in object when `REDIS_URL` is unset, so callers never need to check before calling `redis.get(...)`/`redis.set(...)`. `REDIS_ENABLED` distinguishes "disabled" from a real result where that matters (e.g. health checks).
- **OpenLLMetry / OpenTelemetry tracing** (`utils/logging/tracing.py`) — built on `traceloop-sdk`, which bundles both LLM-aware instrumentation (rich spans for OpenAI calls: prompt, tokens, cost) and generic service instrumentation (Redis, HTTP, SQL). Required — `TRACELOOP_API_ENDPOINT` has no default, so the app won't boot without an OTLP endpoint configured (see [Tracing locally](#tracing-locally)). FastAPI itself is instrumented separately via `FastAPIInstrumentor` (the one thing `traceloop-sdk` doesn't bundle).
- **LLM client with retries** (`utils/llm/client.py`) — a lazy `AsyncOpenAI` singleton behind `get_llm_response()`, which retries transient/rate-limit/empty-parse failures with backoff and raises `LLMCallFailed` once retries are exhausted. This is what `services/agent.py` calls.
- **Test suite** (`tests/`, pytest) — mirrors `services/` and `utils/` one-to-one; covers extraction/validation edge cases, qualification bands, prompt rendering, and the full `conversation()` turn engine with a mocked LLM.
- **Manual conversation harness** (`evals/harness.py`) — a keyboard-driven REPL against the real `conversation()` engine (and, unless mocked, the real OpenAI API) for poking at agent behavior by hand. Prompts at startup for inbound (farmer speaks first) or outbound (agent opens with a greeting), simulating both call directions the same way `services/voice/orchestrator.py` does for real calls. `/state` dumps the claimed record and verdict at any point, `/quit` exits.
- **Ruff** (`pyproject.toml`) for lint + format — configured to match this codebase's existing style (2-space indent, single quotes), not Ruff's Black-compatible defaults.

---

## Project structure

```
agproc/
├── app.py                    # FastAPI factory: lifespan, health routes, trace middleware
├── config.py                  # typed settings (pydantic-settings)
├── main.py                     # `from app import app` — entrypoint for `fastapi deploy`/`fastapi run`
├── routers/
│   └── voice.py                # Twilio webhooks (/voice/incoming, /voice/outgoing) + the call websocket
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
│   ├── voice/                                # pipecat voice pipeline (Twilio <-> Sarvam STT/TTS)
│   │   ├── orchestrator.py                     # wires transport/STT/TTS into a pipecat Pipeline
│   │   ├── provider.py                          # builds Sarvam STT/TTS + Silero VAD per call
│   │   └── language.py                           # VoiceLanguage enum (pipecat Language, not raw Sarvam codes)
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
  [Tracing locally](#tracing-locally)), an OpenAI API key, a Sarvam API key (STT/TTS), and a
  Twilio account SID + auth token — the app won't boot without all of these configured.
- Optional: Redis.
- To actually receive/place phone calls locally (not needed for the harness or tests): `ngrok`
  (or any tunnel) to expose the local server to Twilio's webhooks — see
  [Voice calls locally](#voice-calls-locally).

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
make dev              # uvicorn app:app --port 5000 --reload
```
- `GET /api/health` — liveness probe.
- `GET /api/health/ready` — readiness probe; reports Redis + database status, 503s while draining on shutdown.
- Interactive docs (dev only): http://localhost:5000/docs

### Trying the conversation agent by hand
```bash
python -m evals.harness
```
Prompts for inbound vs. outbound at startup, then type as the farmer; `/state` dumps the claimed
record and verdict at any point, `/quit` exits. This calls the real OpenAI API (no mocking), so it
needs `OPENAI_API_KEY` set. The harness drives the `voice` channel; pass `channel='messaging'` to
`conversation()` directly to exercise the other one.

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
| `SARVAM_API_KEY` | **required** — Sarvam STT/TTS, used by `services/voice/provider.py`; no fallback, app won't boot without it |
| `STT_MODEL` | Sarvam STT model (default `saaras:v3`) |
| `TTS_MODEL` | Sarvam TTS model (default `bulbul:v3`) |
| `VOICE_LANGUAGE` | BCP-47-style code (e.g. `hi-IN`) controlling both Sarvam STT/TTS language and which language the LLM replies in on voice calls (default `hi-IN`); see `services/voice/language.py`'s `VoiceLanguage` for the supported set |
| `TWILIO_ACCOUNT_SID` / `TWILIO_AUTH_TOKEN` | **required** — used by `routers/voice.py`'s Twilio webhooks and the call serializer; no fallback, app won't boot without them |
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

## Voice calls locally

Twilio needs a public HTTPS URL to reach your local server for both the incoming-call webhook
and the Media Stream websocket, so a tunnel is required even for local testing:

1. Run the app (`make dev`) and a tunnel against the same port, e.g. `ngrok http 5000`.
2. Point the TwiML in `routers/voice.py` (`/voice/incoming`, `/voice/outgoing`) at that tunnel's
   `wss://` URL for the `<Stream>` — update it each time the tunnel restarts, since a free ngrok
   URL changes on every restart.
3. For an **inbound** test call: configure the Twilio phone number's "A call comes in" webhook to
   `https://<tunnel>/api/voice/incoming`, then call that number.
4. For an **outbound** test call: use the Twilio REST client to place a call with
   `url='https://<tunnel>/api/voice/outgoing'` (see `client.calls.create(...)` in the Twilio docs)
   — `routers/voice.py`'s websocket route reads the `direction` custom parameter to tell
   `services/agent.py`'s `conversation()` whether the agent or the farmer speaks first.

---

## Deferred on purpose

A few things were deliberately left out rather than half-configured — add them when there's
actual code that needs them, not before:

- **Type checking** (pyright/mypy) — worth adding once `routers/` has real logic with
  non-trivial data shapes to check. Ruff does not type-check.
- **Metrics backend** (Prometheus/Grafana Mimir) — `Traceloop.init()` already emits metrics
  (token usage, operation duration, ...); nothing currently collects them.
- **Messaging channel routes** — the `voice` channel is wired end-to-end (`routers/voice.py`,
  Twilio + pipecat); `messaging` only exists as a code path in `services/prompt.py`'s
  `CHANNEL_CONTEXT` and isn't connected to any actual messaging provider (WhatsApp, SMS, ...) yet.
  `evals/harness.py` currently only drives the `voice` channel too, though `conversation()` itself
  already accepts `channel='messaging'`.
