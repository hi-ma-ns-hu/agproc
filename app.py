from __future__ import annotations

import signal
import time
import uuid
from collections import defaultdict
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from sqlalchemy import text

from config import settings
from shared import REDIS_ENABLED, bind_context, clear_context, configure_logging, engine, get_logger, init_tracing, redis

# configure logging and tracing once at startup, before any traced client is used
configure_logging()
init_tracing()
logger = get_logger(__name__)

# ── Graceful shutdown state ───────────────────────────────────────────────────
# _active_requests tracks in-flight HTTP requests so we know when it's safe to exit.
# _shutting_down flips to True on SIGTERM — /health/ready returns 503 immediately,
# telling the load balancer to stop sending new traffic. In-flight requests drain
# on their own; we don't kill them.
_active_requests: int = 0
_shutting_down: bool = False


def _handle_sigterm(*_) -> None:
  global _shutting_down
  _shutting_down = True
  logger.info('SIGTERM received — draining requests', active=_active_requests)


signal.signal(signal.SIGTERM, _handle_sigterm)


# lifespan
@asynccontextmanager
async def lifespan(app: FastAPI):
  logger.info('Vaani starting', env=settings.APP_ENV)

  # from services import SlackAdapter, set_slack
  # set_slack(await SlackAdapter().initialize())

  yield

  await redis.aclose()
  await engine.dispose()
  logger.info('Vaani shutdown complete')


def _add_health_routes(app: FastAPI) -> None:
  @app.get('/health', tags=['ops'])
  async def health_check():
    # Liveness probe — just confirms the process is alive.
    # Kubernetes kills and restarts the pod if this fails.
    # Never returns 503 during shutdown: we want the process alive until drain is done.
    return {'status': 'ok', 'env': settings.APP_ENV}

  @app.get('/health/ready', tags=['ops'])
  async def health_ready():
    # Readiness probe — tells the load balancer whether to send traffic here.
    # Returns 503 when shutting down so Kubernetes stops routing new requests
    # while in-flight ones finish. This is how drain works without dropping requests.
    if _shutting_down:
      return JSONResponse(
        content={'status': 'shutting_down', 'active_requests': _active_requests},
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
      )

    checks: defaultdict[str, str] = defaultdict(str)

    if not REDIS_ENABLED:
      checks['redis'] = 'disabled'
    else:
      try:
        await redis.ping()
        checks['redis'] = 'ok'
      except Exception as e:
        checks['redis'] = f'error: {e}'

    try:
      async with engine.connect() as conn:
        await conn.execute(text('SELECT 1'))
      checks['database'] = 'ok'
    except Exception as e:
      checks['database'] = f'error: {e}'

    ok = all(v in ('ok', 'disabled') for v in checks.values())
    return JSONResponse(
      content={'checks': checks, 'active_requests': _active_requests},
      status_code=status.HTTP_200_OK if ok else status.HTTP_503_SERVICE_UNAVAILABLE,
    )


# def _add_api_routes(app: FastAPI) -> None:
#   app.include_router(router)


def _add_trace_middleware(app: FastAPI) -> None:
  @app.middleware('http')
  async def trace_middleware(request: Request, call_next):
    global _active_requests
    _active_requests += 1
    trace_id = uuid.uuid4().hex[:12]
    bind_context(trace_id=trace_id, path=request.url.path, method=request.method)
    t0 = time.perf_counter()
    response = None
    try:
      response = await call_next(request)
    finally:
      _active_requests -= 1
      duration_ms = round((time.perf_counter() - t0) * 1000)
      logger.info('http', status=response.status_code if response else 500, duration_ms=duration_ms)
      clear_context()
    return response


# app factory
def create_app() -> FastAPI:
  app = FastAPI(title='Vaani', version='0.1.0', lifespan=lifespan, root_path='/api', docs_url='/docs' if settings.IS_DEVELOPMENT else None, redoc_url=None)
  FastAPIInstrumentor.instrument_app(app)
  _add_trace_middleware(app)
  _add_health_routes(app)
  return app


app = create_app()
