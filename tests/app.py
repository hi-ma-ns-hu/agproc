from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# app.py calls init_tracing()/configure_logging() at module level, on first
# import. init_tracing() installs a REAL, process-wide OTel TracerProvider
# with synchronous (non-batched) export in this dev environment - with no
# network route to the real endpoint here, every span closed anywhere in the
# rest of the test suite afterward (including pipecat's own tracing in
# services/voice/orchestrator.py's tests) would then block on a network
# timeout. Neither has any effect worth the cost in a test run, so both are
# no-ops for this one, first-ever import of `app`.
with patch('utils.init_tracing'), patch('utils.configure_logging'):
  import app as app_module

# The real `app.app` also has FastAPIInstrumentor attached and tries to export
# a span over the network on every request, which hangs the same way -
# confirmed by testing it directly. Each test instead builds a bare FastAPI()
# and registers just the one real _add_*_routes()/_add_trace_middleware()
# helper under test, so the actual production logic still runs, just without
# the instrumentation that requires real connectivity.


@pytest.fixture(autouse=True)
def _reset_shutdown_state():
  app_module._shutting_down = False
  app_module._active_requests = 0
  yield
  app_module._shutting_down = False
  app_module._active_requests = 0


def _health_client() -> TestClient:
  test_app = FastAPI()
  app_module._add_health_routes(test_app)
  return TestClient(test_app)


def _connect_cm(conn: AsyncMock) -> MagicMock:
  cm = MagicMock()
  cm.__aenter__ = AsyncMock(return_value=conn)
  cm.__aexit__ = AsyncMock(return_value=False)
  return cm


def _fake_engine(**connect_kwargs) -> MagicMock:
  """AsyncEngine.connect is a read-only attribute on the real engine, so the
  whole `app.engine` name has to be replaced rather than just its method."""
  engine = MagicMock()
  engine.connect = MagicMock(**connect_kwargs)
  return engine


# --- SIGTERM handling -----------------------------------------------------


def test_handle_sigterm_sets_shutting_down_flag():
  assert app_module._shutting_down is False
  app_module._handle_sigterm()
  assert app_module._shutting_down is True


# --- /health (liveness) ----------------------------------------------------


def test_health_check_returns_ok():
  response = _health_client().get('/health')

  assert response.status_code == 200
  assert response.json() == {'status': 'ok', 'env': app_module.settings.APP_ENV}


def test_health_check_never_503s_even_while_shutting_down():
  app_module._shutting_down = True

  response = _health_client().get('/health')

  assert response.status_code == 200


# --- /health/ready (readiness) ----------------------------------------------


def test_health_ready_returns_503_while_shutting_down():
  app_module._shutting_down = True

  response = _health_client().get('/health/ready')

  assert response.status_code == 503
  assert response.json()['status'] == 'shutting_down'


def test_health_ready_ok_when_redis_and_database_healthy():
  conn = AsyncMock()
  with patch('app.REDIS_ENABLED', True), patch('app.redis.ping', new=AsyncMock(return_value=True)), patch('app.engine', new=_fake_engine(return_value=_connect_cm(conn))):
    response = _health_client().get('/health/ready')

  assert response.status_code == 200
  assert response.json()['checks'] == {'redis': 'ok', 'database': 'ok'}


def test_health_ready_reports_redis_disabled_when_not_configured():
  conn = AsyncMock()
  with patch('app.REDIS_ENABLED', False), patch('app.engine', new=_fake_engine(return_value=_connect_cm(conn))):
    response = _health_client().get('/health/ready')

  assert response.status_code == 200
  assert response.json()['checks']['redis'] == 'disabled'


def test_health_ready_503_when_database_unreachable():
  with patch('app.REDIS_ENABLED', False), patch('app.engine', new=_fake_engine(side_effect=RuntimeError('connection refused'))):
    response = _health_client().get('/health/ready')

  assert response.status_code == 503
  assert response.json()['checks']['database'].startswith('error:')


def test_health_ready_503_when_redis_unreachable():
  conn = AsyncMock()
  with patch('app.REDIS_ENABLED', True), patch('app.redis.ping', new=AsyncMock(side_effect=RuntimeError('refused'))), patch('app.engine', new=_fake_engine(return_value=_connect_cm(conn))):
    response = _health_client().get('/health/ready')

  assert response.status_code == 503
  assert response.json()['checks']['redis'].startswith('error:')


# --- trace middleware -------------------------------------------------------


def _traced_client() -> TestClient:
  test_app = FastAPI()
  app_module._add_trace_middleware(test_app)

  @test_app.get('/dummy')
  async def dummy():
    return {'ok': True}

  return TestClient(test_app)


def test_trace_middleware_logs_non_health_requests():
  client = _traced_client()
  with patch('app.logger') as mock_logger:
    response = client.get('/dummy')

  assert response.status_code == 200
  assert any(call.args[:1] == ('http',) for call in mock_logger.info.call_args_list)


def test_trace_middleware_excludes_health_paths_from_access_log():
  test_app = FastAPI()
  app_module._add_trace_middleware(test_app)
  app_module._add_health_routes(test_app)
  client = TestClient(test_app)

  with patch('app.logger') as mock_logger:
    response = client.get('/health')

  assert response.status_code == 200
  assert not any(call.args[:1] == ('http',) for call in mock_logger.info.call_args_list)


def test_trace_middleware_resets_active_requests_after_response():
  client = _traced_client()

  client.get('/dummy')

  assert app_module._active_requests == 0
