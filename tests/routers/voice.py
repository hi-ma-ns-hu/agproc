from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from routers.voice import incoming_call, outgoing_call, voice_stream

REAL_START_EVENT = {
  'event': 'start',
  'sequenceNumber': '1',
  'start': {
    'accountSid': 'AC00000000000000000000000000000000',
    'streamSid': 'MZ72d84c6b2fc3338ca50bc7eef1636ce8',
    'callSid': 'CAe90d8233d72bfa8872bdb695c2d44ede',
    'tracks': ['inbound'],
    'mediaFormat': {'encoding': 'audio/x-mulaw', 'sampleRate': 8000, 'channels': 1},
    'customParameters': {},
  },
  'streamSid': 'MZ72d84c6b2fc3338ca50bc7eef1636ce8',
}

CONNECTED_EVENT = {'event': 'connected', 'protocol': 'Call', 'version': '1.0.0'}


class _FakeWebSocket:
  """Stands in for the real Twilio media-stream WebSocket: delivers the two
  JSON messages voice_stream() reads (connected, then start) in order."""

  def __init__(self, start_event: dict):
    self._messages = [CONNECTED_EVENT, start_event]
    self.accepted = False

  async def accept(self):
    self.accepted = True

  async def receive_json(self):
    return self._messages.pop(0)


# --- TwiML routes --------------------------------------------------------------


async def test_incoming_call_returns_twiml_without_direction_parameter():
  response = await incoming_call()

  assert response.media_type == 'application/xml'
  body = response.body.decode()
  assert '<Stream' in body
  assert '<Parameter' not in body


async def test_outgoing_call_returns_twiml_with_outbound_direction_parameter():
  response = await outgoing_call()

  assert response.media_type == 'application/xml'
  body = response.body.decode()
  assert '<Stream' in body
  assert '<Parameter name="direction" value="outbound"/>' in body


# --- voice_stream() websocket handler -------------------------------------------
# Everything voice_stream() constructs/calls besides parsing the start event
# itself is patched out - the real pipeline/transport/VAD model are out of
# scope for a router-level test.


async def test_voice_stream_starts_pipeline_with_call_sid_and_default_direction():
  ws = _FakeWebSocket(REAL_START_EVENT)
  with (
    patch('routers.voice.SileroVADAnalyzer', return_value=MagicMock()),
    patch('routers.voice.TwilioFrameSerializer', return_value=MagicMock()),
    patch('routers.voice.FastAPIWebsocketParams', return_value=MagicMock()),
    patch('routers.voice.FastAPIWebsocketTransport', return_value=MagicMock()),
    patch('routers.voice.run_conversation_pipeline', new=AsyncMock()) as mock_run_pipeline,
    patch('routers.voice.bind_context') as mock_bind,
    patch('routers.voice.clear_context') as mock_clear,
  ):
    await voice_stream(ws)

  assert ws.accepted is True
  mock_run_pipeline.assert_called_once()
  args = mock_run_pipeline.call_args.args
  assert args[3] == 'CAe90d8233d72bfa8872bdb695c2d44ede'  # call_sid
  assert args[4] == 'inbound'  # default direction
  mock_bind.assert_called_once_with(conversation_id='CAe90d8233d72bfa8872bdb695c2d44ede', channel='voice', direction='inbound')
  mock_clear.assert_called_once()


async def test_voice_stream_respects_outbound_direction_custom_parameter():
  start_event = {**REAL_START_EVENT, 'start': {**REAL_START_EVENT['start'], 'customParameters': {'direction': 'outbound'}}}
  ws = _FakeWebSocket(start_event)
  with (
    patch('routers.voice.SileroVADAnalyzer', return_value=MagicMock()),
    patch('routers.voice.TwilioFrameSerializer', return_value=MagicMock()),
    patch('routers.voice.FastAPIWebsocketParams', return_value=MagicMock()),
    patch('routers.voice.FastAPIWebsocketTransport', return_value=MagicMock()),
    patch('routers.voice.run_conversation_pipeline', new=AsyncMock()) as mock_run_pipeline,
    patch('routers.voice.bind_context') as mock_bind,
    patch('routers.voice.clear_context'),
  ):
    await voice_stream(ws)

  assert mock_run_pipeline.call_args.args[4] == 'outbound'
  mock_bind.assert_called_once_with(conversation_id=REAL_START_EVENT['start']['callSid'], channel='voice', direction='outbound')


async def test_voice_stream_clears_context_even_if_pipeline_raises():
  ws = _FakeWebSocket(REAL_START_EVENT)
  with (
    patch('routers.voice.SileroVADAnalyzer', return_value=MagicMock()),
    patch('routers.voice.TwilioFrameSerializer', return_value=MagicMock()),
    patch('routers.voice.FastAPIWebsocketParams', return_value=MagicMock()),
    patch('routers.voice.FastAPIWebsocketTransport', return_value=MagicMock()),
    patch('routers.voice.run_conversation_pipeline', new=AsyncMock(side_effect=RuntimeError('boom'))),
    patch('routers.voice.bind_context'),
    patch('routers.voice.clear_context') as mock_clear,
  ):
    with pytest.raises(RuntimeError, match='boom'):
      await voice_stream(ws)

  mock_clear.assert_called_once()
