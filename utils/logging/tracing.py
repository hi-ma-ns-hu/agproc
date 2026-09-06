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
