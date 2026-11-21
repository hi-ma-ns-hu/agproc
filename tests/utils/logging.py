import json
import logging

from utils.logging import JSONFormatter, bind_context, clear_context, get_context, get_logger


def _make_record(level=logging.INFO, msg='hello', **extra) -> logging.LogRecord:
  record = logging.LogRecord(name='test.logger', level=level, pathname=__file__, lineno=1, msg=msg, args=(), exc_info=None)
  for key, value in extra.items():
    setattr(record, key, value)
  return record


# --- context propagation ----------------------------------------------------


def test_bind_context_merges_into_an_empty_context():
  clear_context()
  bind_context(trace_id='abc123')
  assert get_context() == {'trace_id': 'abc123'}
  clear_context()


def test_bind_context_merges_with_existing_fields_rather_than_replacing():
  clear_context()
  bind_context(trace_id='abc123')
  bind_context(conversation_id='CA1')
  assert get_context() == {'trace_id': 'abc123', 'conversation_id': 'CA1'}
  clear_context()


def test_bind_context_overwrites_a_field_with_the_same_name():
  clear_context()
  bind_context(direction='inbound')
  bind_context(direction='outbound')
  assert get_context() == {'direction': 'outbound'}
  clear_context()


def test_clear_context_drops_everything():
  bind_context(trace_id='abc123')
  clear_context()
  assert get_context() == {}


# --- JSONFormatter ------------------------------------------------------------


def test_json_formatter_includes_base_fields():
  clear_context()
  payload = json.loads(JSONFormatter().format(_make_record(msg='hi')))

  assert payload['level'] == 'INFO'
  assert payload['logger'] == 'test.logger'
  assert payload['message'] == 'hi'
  assert payload['service'] == 'agproc'
  assert 'timestamp' in payload
  assert 'env' in payload


def test_json_formatter_merges_bound_context_fields():
  clear_context()
  bind_context(conversation_id='CA1', channel='voice')
  payload = json.loads(JSONFormatter().format(_make_record()))
  clear_context()

  assert payload['conversation_id'] == 'CA1'
  assert payload['channel'] == 'voice'


def test_json_formatter_includes_extra_kwargs():
  payload = json.loads(JSONFormatter().format(_make_record(duration_ms=42, model='gpt-4o')))

  assert payload['duration_ms'] == 42
  assert payload['model'] == 'gpt-4o'


def test_json_formatter_excludes_stdlib_logrecord_attributes():
  payload = json.loads(JSONFormatter().format(_make_record()))

  # stdlib bookkeeping attributes (filename, lineno, threadName, ...) must not
  # leak into the JSON payload - only our own fields and the base shape should.
  assert 'filename' not in payload
  assert 'lineno' not in payload
  assert 'threadName' not in payload


def test_json_formatter_includes_exception_details():
  try:
    raise ValueError('boom')
  except ValueError:
    import sys

    record = _make_record(msg='it failed')
    record.exc_info = sys.exc_info()
    payload = json.loads(JSONFormatter().format(record))

  assert payload['exc_type'] == 'ValueError'
  assert payload['exc_message'] == 'boom'
  assert 'exc_traceback' in payload


def test_json_formatter_omits_exception_fields_when_none_raised():
  payload = json.loads(JSONFormatter().format(_make_record()))

  assert 'exc_type' not in payload
  assert 'exc_message' not in payload


# --- BoundLogger --------------------------------------------------------------


def test_bound_logger_forwards_kwargs_as_extra_fields(caplog):
  logger = get_logger('test.bound_logger.extra')
  with caplog.at_level(logging.INFO, logger='test.bound_logger.extra'):
    logger.info('turn.input', turn=3, input='hello')

  record = caplog.records[0]
  assert record.turn == 3
  assert record.input == 'hello'


def test_bound_logger_respects_logger_level(caplog):
  logger = get_logger('test.bound_logger.level')
  # caplog.at_level would itself lower the effective threshold to capture
  # everything - set it to the same WARNING floor we're testing instead, so
  # BoundLogger's own isEnabledFor() check is what's actually being exercised.
  with caplog.at_level(logging.WARNING, logger='test.bound_logger.level'):
    logger.debug('should be dropped')
    logger.warning('should go through')

  messages = [r.message for r in caplog.records]
  assert 'should be dropped' not in messages
  assert 'should go through' in messages


def test_bound_logger_warning_passes_exc_info_through(caplog):
  logger = get_logger('test.bound_logger.exc')
  with caplog.at_level(logging.WARNING, logger='test.bound_logger.exc'):
    try:
      raise RuntimeError('boom')
    except RuntimeError:
      logger.warning('it failed', exc_info=True)

  record = caplog.records[0]
  assert record.exc_info is not None
  assert record.exc_info[0] is RuntimeError
