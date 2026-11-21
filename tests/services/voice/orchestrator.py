import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from pipecat.frames.frames import EndFrame, TextFrame, TranscriptionFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.tests.utils import QueuedFrameProcessor

from services import ConversationBridge
from services.voice.orchestrator import run_conversation_pipeline


def _fake_transcription(text: str) -> TranscriptionFrame:
  return TranscriptionFrame(text=text, user_id='test', timestamp='')


def _fake_build_state(conversation_id: str, direction: str):
  return {'conversation_id': conversation_id, 'direction': direction}


async def test_bridge_pushes_reply_as_text_frame():
  fake_response = {'reply': 'नमस्ते', 'state': None, 'done': False}
  mock_conversation = AsyncMock(return_value=fake_response)
  bridge = ConversationBridge(mock_conversation, _fake_build_state, 'CA123', direction='inbound')
  bridge.push_frame = AsyncMock()

  await bridge.process_frame(_fake_transcription('गेहूं'), FrameDirection.DOWNSTREAM)

  pushed_frame = bridge.push_frame.call_args_list[1].args[0]
  assert isinstance(pushed_frame, TextFrame)
  assert pushed_frame.text == 'नमस्ते'


async def test_bridge_pushes_end_frame_when_done():
  fake_response = {'reply': 'धन्यवाद', 'state': None, 'done': True}
  mock_conversation = AsyncMock(return_value=fake_response)
  bridge = ConversationBridge(mock_conversation, _fake_build_state, 'CA123', direction='inbound')
  bridge.push_frame = AsyncMock()

  await bridge.process_frame(_fake_transcription('ठीक है'), FrameDirection.DOWNSTREAM)

  pushed_types = [call.args[0].__class__ for call in bridge.push_frame.call_args_list]
  assert TextFrame in pushed_types
  assert EndFrame in pushed_types


async def test_bridge_does_not_push_end_frame_when_not_done():
  fake_response = {'reply': 'और बताएं', 'state': None, 'done': False}
  mock_conversation = AsyncMock(return_value=fake_response)
  bridge = ConversationBridge(mock_conversation, _fake_build_state, 'CA123', direction='inbound')
  bridge.push_frame = AsyncMock()

  await bridge.process_frame(_fake_transcription('गेहूं है'), FrameDirection.DOWNSTREAM)

  pushed_types = [call.args[0].__class__ for call in bridge.push_frame.call_args_list]
  assert EndFrame not in pushed_types


async def test_bridge_passes_through_non_transcription_frames_unchanged():
  bridge = ConversationBridge(AsyncMock(), _fake_build_state, 'CA123', direction='inbound')
  bridge.push_frame = AsyncMock()

  other_frame = EndFrame()  # any non-TranscriptionFrame
  await bridge.process_frame(other_frame, FrameDirection.DOWNSTREAM)

  bridge.push_frame.assert_called_once_with(other_frame, FrameDirection.DOWNSTREAM)


def test_build_state_is_called_with_conversation_id_and_direction():
  build_state = MagicMock(return_value='some-state')
  ConversationBridge(AsyncMock(), build_state, 'CA123', direction='outbound')
  build_state.assert_called_once_with('CA123', 'outbound')


async def test_speak_outbound_opening_calls_conversation_with_opening_flag():
  fake_response = {'reply': 'नमस्ते! ...', 'state': None, 'done': False}
  mock_conversation = AsyncMock(return_value=fake_response)
  bridge = ConversationBridge(mock_conversation, _fake_build_state, 'CA123', direction='outbound')
  bridge.push_frame = AsyncMock()

  await bridge.speak_outbound_opening()

  mock_conversation.assert_called_once()
  _, kwargs = mock_conversation.call_args
  assert kwargs.get('is_opening_turn') is True


# --- run_conversation_pipeline() itself (added for #36: PipelineWorker +
# ErrorObserver/StartupTimingObserver/UserBotLatencyObserver wiring) ----------


class _PassthroughStub(FrameProcessor):
  """Plain passthrough, standing in for the real transport-input/STT/TTS
  processors - base FrameProcessor doesn't forward frames on its own."""

  async def process_frame(self, frame, direction):
    await super().process_frame(frame, direction)
    await self.push_frame(frame, direction)


class _FakeTransport:
  """Stands in for pipecat's real Twilio/FastAPIWebsocket transport: exposes the
  same .input()/.output()/.event_handler() surface run_conversation_pipeline()
  uses, without a real WebSocket or audio."""

  def __init__(self, input_processor: FrameProcessor, output_processor: FrameProcessor):
    self._input = input_processor
    self._output = output_processor
    self.handlers: dict[str, object] = {}

  def input(self):
    return self._input

  def output(self):
    return self._output

  def event_handler(self, name):
    def decorator(fn):
      self.handlers[name] = fn
      return fn

    return decorator


async def test_run_conversation_pipeline_builds_and_speaks_outbound_opening():
  # SileroVADAnalyzer loads a real ONNX model on construction - mock it out so
  # this stays a fast unit test, not an integration test with model-load cost.
  with patch('services.voice.orchestrator.SileroVADAnalyzer', return_value=MagicMock()), patch('services.voice.orchestrator.get_stt_service', return_value=_PassthroughStub(name='fake-stt')), patch('services.voice.orchestrator.get_tts_service', return_value=_PassthroughStub(name='fake-tts')):
    received_down = asyncio.Queue()
    sink = QueuedFrameProcessor(queue=received_down, queue_direction=FrameDirection.DOWNSTREAM)
    transport = _FakeTransport(input_processor=_PassthroughStub(name='fake-transport-in'), output_processor=sink)

    fake_response = {'reply': 'नमस्ते! Calling about produce you may have to sell.', 'state': 'state-after-opening', 'done': False}
    conversation = AsyncMock(return_value=fake_response)
    build_state = MagicMock(return_value='initial-state')

    pipeline_task = asyncio.create_task(run_conversation_pipeline(transport, conversation, build_state, 'CA123', 'outbound'))
    try:
      # run_conversation_pipeline()'s event_handler registrations happen
      # synchronously before `await runner.run(task)`, but the pipeline itself
      # needs a moment to finish its StartFrame handshake before it'll actually
      # move frames - poll for the first frame to land rather than guessing a
      # fixed delay (no external handle to the task/worker to await its own
      # on_pipeline_started event instead).
      for _ in range(50):
        if 'on_client_connected' in transport.handlers:
          break
        await asyncio.sleep(0.05)
      assert 'on_client_connected' in transport.handlers

      await transport.handlers['on_client_connected'](transport, client=None)

      down_frames = []
      for _ in range(50):
        while not received_down.empty():
          down_frames.append(await received_down.get())
        if any(isinstance(f, TextFrame) for f in down_frames):
          break
        await asyncio.sleep(0.05)

      assert any(isinstance(f, TextFrame) and f.text == fake_response['reply'] for f in down_frames)
      conversation.assert_called_once()
      assert conversation.call_args.kwargs.get('is_opening_turn') is True

      await transport.handlers['on_client_disconnected'](transport, client=None)
    finally:
      await asyncio.wait_for(pipeline_task, timeout=2.0)
