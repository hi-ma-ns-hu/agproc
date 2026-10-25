from __future__ import annotations

from opentelemetry import trace
from opentelemetry.trace import Tracer

from config import settings


def get_tracer(name: str) -> Tracer:
  """
  Returns a Tracer scoped to the calling module, for creating spans.
  """
  return trace.get_tracer(name)


def init_tracing() -> None:
  """
  Initialize OpenLLMetry/OTel tracing. Call ONCE at startup, before creating
  the FastAPI app or using any instrumented client.

  Always on — TRACELOOP_API_ENDPOINT is a required setting, not optional.
  """
  from opentelemetry.instrumentation.logging import LoggingInstrumentor
  from traceloop.sdk import Traceloop

  Traceloop.init(
    app_name='agproc',
    api_endpoint=settings.TRACELOOP_API_ENDPOINT,
    disable_batch=settings.IS_DEVELOPMENT,
  )
  # Attaches otelTraceID/otelSpanID to every LogRecord while a span is active, so JSONFormatter picks them up and Grafana can link a Loki log line to its Tempo trace.
  LoggingInstrumentor().instrument(inject_trace_context=True, enable_log_auto_instrumentation=False)
