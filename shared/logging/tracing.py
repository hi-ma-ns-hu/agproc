"""
shared/logging/tracing.py — OpenLLMetry / OpenTelemetry tracing setup.

Built on Traceloop's OpenLLMetry SDK, which sets up standard OpenTelemetry
under the hood: LLM calls (OpenAI, etc.) get rich spans (prompt, tokens,
cost) and generic service calls (Redis, requests, SQLAlchemy) get traced too
— traceloop-sdk bundles those instrumentors already. FastAPI is the one
instrumentor it doesn't bundle, so that's wired separately in app.py via
FastAPIInstrumentor.

Required — TRACELOOP_API_ENDPOINT has no default (see config.py) and the app
won't boot without it. Call init_tracing() once at startup, before any traced
client (redis, the OpenAI client, etc.) is first used.

Usage:
    from shared.logging.tracing import init_tracing

    init_tracing()
"""

from __future__ import annotations

from config import settings


def init_tracing() -> None:
  """
  Initialize OpenLLMetry/OTel tracing. Call ONCE at startup, before creating
  the FastAPI app or using any instrumented client.

  Always on — TRACELOOP_API_ENDPOINT is a required setting, not optional.
  """
  from traceloop.sdk import Traceloop

  Traceloop.init(
    app_name='agproc',
    api_endpoint=settings.TRACELOOP_API_ENDPOINT,
    disable_batch=settings.IS_DEVELOPMENT,
  )
