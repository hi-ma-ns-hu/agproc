from unittest.mock import AsyncMock

from pipecat.frames.frames import EndFrame, TextFrame, TranscriptionFrame
from pipecat.processors.frame_processor import FrameDirection

from services import ConversationBridge


def _fake_transcription(text: str) -> TranscriptionFrame:
  return TranscriptionFrame(text=text, user_id='test', timestamp='')


def _fake_build_state(direction: str):
  return {'direction': direction}


async def test_bridge_pushes_reply_as_text_frame():
  fake_response = {'reply': 'नमस्ते', 'state': None, 'done': False}
  mock_conversation = AsyncMock(return_value=fake_response)
  bridge = ConversationBridge(mock_conversation, _fake_build_state, direction='inbound')
  bridge.push_frame = AsyncMock()

  await bridge.process_frame(_fake_transcription('गेहूं'), FrameDirection.DOWNSTREAM)

  pushed_frame = bridge.push_frame.call_args_list[1].args[0]
  assert isinstance(pushed_frame, TextFrame)
  assert pushed_frame.text == 'नमस्ते'


async def test_bridge_pushes_end_frame_when_done():
  fake_response = {'reply': 'धन्यवाद', 'state': None, 'done': True}
  mock_conversation = AsyncMock(return_value=fake_response)
  bridge = ConversationBridge(mock_conversation, _fake_build_state, direction='inbound')
  bridge.push_frame = AsyncMock()

  await bridge.process_frame(_fake_transcription('ठीक है'), FrameDirection.DOWNSTREAM)

  pushed_types = [call.args[0].__class__ for call in bridge.push_frame.call_args_list]
  assert TextFrame in pushed_types
  assert EndFrame in pushed_types


async def test_bridge_does_not_push_end_frame_when_not_done():
  fake_response = {'reply': 'और बताएं', 'state': None, 'done': False}
  mock_conversation = AsyncMock(return_value=fake_response)
  bridge = ConversationBridge(mock_conversation, _fake_build_state, direction='inbound')
  bridge.push_frame = AsyncMock()

  await bridge.process_frame(_fake_transcription('गेहूं है'), FrameDirection.DOWNSTREAM)

  pushed_types = [call.args[0].__class__ for call in bridge.push_frame.call_args_list]
  assert EndFrame not in pushed_types


async def test_bridge_passes_through_non_transcription_frames_unchanged():
  bridge = ConversationBridge(AsyncMock(), _fake_build_state, direction='inbound')
  bridge.push_frame = AsyncMock()

  other_frame = EndFrame()  # any non-TranscriptionFrame
  await bridge.process_frame(other_frame, FrameDirection.DOWNSTREAM)

  bridge.push_frame.assert_called_once_with(other_frame, FrameDirection.DOWNSTREAM)


def test_build_state_is_called_with_direction():
  build_state = AsyncMock(return_value='some-state')
  ConversationBridge(AsyncMock(), build_state, direction='outbound')
  build_state.assert_called_once_with('outbound')


async def test_speak_outbound_opening_calls_conversation_with_opening_flag():
  fake_response = {'reply': 'नमस्ते! ...', 'state': None, 'done': False}
  mock_conversation = AsyncMock(return_value=fake_response)
  bridge = ConversationBridge(mock_conversation, _fake_build_state, direction='outbound')
  bridge.push_frame = AsyncMock()

  await bridge.speak_outbound_opening()

  mock_conversation.assert_called_once()
  _, kwargs = mock_conversation.call_args
  assert kwargs.get('is_opening_turn') is True
