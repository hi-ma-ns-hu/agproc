from config import Settings


def _settings(**overrides) -> Settings:
  required = {
    'DATABASE_URL': 'postgresql+asyncpg://user:pass@localhost/db',
    'TRACELOOP_API_ENDPOINT': 'http://localhost:4318',
    'OPENAI_API_KEY': 'sk-test',
    'SARVAM_API_KEY': 'test',
    'TWILIO_ACCOUNT_SID': 'AC_test',
    'TWILIO_AUTH_TOKEN': 'test',
  }
  return Settings(**{**required, **overrides})


def test_is_development_true_for_development_env():
  assert _settings(APP_ENV='DEVELOPMENT').IS_DEVELOPMENT is True


def test_is_development_false_for_staging_and_production():
  assert _settings(APP_ENV='STAGING').IS_DEVELOPMENT is False
  assert _settings(APP_ENV='PRODUCTION').IS_DEVELOPMENT is False
