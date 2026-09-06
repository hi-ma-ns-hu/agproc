from unittest.mock import AsyncMock, MagicMock, patch

from services import TOOLS, Confidence, ConversationOutput, ConversationState, CropState, ExtractedField, Measure, MeasureValue, Role, Verdict, conversation
from utils import LLMCallFailed


def _mock_llm(output: ConversationOutput):
  """Patch get_llm_response to return a fixed ConversationOutput instead of calling the API."""
  return patch('services.agent.get_llm_response', new=AsyncMock(return_value=output))


async def test_turn_applies_extracted_updates():
  fake = ConversationOutput(
    updates=[ExtractedField(field='crop', value='wheat', confidence='high')],
    reply='Got it — wheat. How much do you have?',
  )
  with _mock_llm(fake):
    state = ConversationState()
    result = await conversation('I have wheat to sell', state)

  assert result['state'].claimed.crop.value == 'wheat'
  assert result['state'].claimed.crop.confidence is Confidence.HIGH
  assert result['reply'] == 'Got it — wheat. How much do you have?'


async def test_turn_appends_to_history():
  fake = ConversationOutput(updates=[], reply='Sure, tell me more.')
  with _mock_llm(fake):
    state = ConversationState()
    result = await conversation('hello', state)

  history = result['state'].history
  assert len(history) == 2
  assert history[0].role is Role.USER
  assert history[0].content == 'hello'
  assert history[1].role is Role.ASSISTANT
  assert history[1].content == 'Sure, tell me more.'


async def test_turn_increments_turn_count():
  fake = ConversationOutput(updates=[], reply='ok')
  with _mock_llm(fake):
    state = ConversationState()
    await conversation('first', state)
    result = await conversation('second', state)

  assert result['state'].meta.turn_count == 2


async def test_turn_rejects_bad_extraction_without_crashing():
  fake = ConversationOutput(
    updates=[ExtractedField(field='quantity', value='a lot', confidence='high')],  # bad type
    reply='How much roughly?',
  )
  with _mock_llm(fake):
    state = ConversationState()
    result = await conversation('I have a lot of wheat', state)

  assert result['state'].claimed.quantity.is_known() is False  # rejected, didn't crash
  assert result['reply'] == 'How much roughly?'


async def test_turn_returns_apology_on_llm_failure():
  with patch('services.agent.get_llm_response', new=AsyncMock(side_effect=LLMCallFailed('boom'))):
    state = ConversationState()
    result = await conversation('hello', state)

  assert 'having trouble' in result['reply'].lower()
  assert result['done'] is False
  assert len(result['state'].history) == 0  # failed before history was touched


async def test_turn_does_not_qualify_when_record_incomplete():
  fake = ConversationOutput(
    updates=[ExtractedField(field='crop', value='wheat', confidence='high')],
    reply='How much do you have?',
  )
  with _mock_llm(fake):
    state = ConversationState()
    result = await conversation('wheat', state)

  assert result['state'].qualification.is_decided() is False
  assert result['done'] is False


async def test_turn_qualifies_once_record_becomes_complete():
  state = ConversationState()
  state.claimed.crop.update('wheat', Confidence.HIGH, 1)
  state.claimed.quantity.update(Measure(40, 'quintal'), Confidence.HIGH, 1)
  state.claimed.crop_state.update(CropState.HARVESTED, Confidence.HIGH, 1)
  state.claimed.location.update('farm gate', Confidence.HIGH, 1)

  normal_reply = ConversationOutput(
    updates=[ExtractedField(field='price', value=MeasureValue(value=2450, unit='₹/quintal'), confidence='high')],
    reply='Thanks — let me check that for you.',
  )
  closing_reply = ConversationOutput(updates=[], reply="Great, we'll follow up soon. Thanks!")

  with patch(
    'services.agent.get_llm_response',
    new=AsyncMock(side_effect=[normal_reply, closing_reply]),
  ):
    result = await conversation('2450 per quintal', state)

  assert result['state'].qualification.is_decided() is True
  assert result['reply'] == "Great, we'll follow up soon. Thanks!"
  assert result['done'] is True


async def test_turn_does_not_requalify_once_decided():
  # a qualification already exists; a later turn should not overwrite it
  state = ConversationState()
  state.claimed.crop.update('wheat', Confidence.HIGH, 1)
  state.claimed.quantity.update(Measure(40, 'quintal'), Confidence.HIGH, 1)
  state.claimed.crop_state.update(CropState.HARVESTED, Confidence.HIGH, 1)
  state.claimed.location.update('farm gate', Confidence.HIGH, 1)
  state.claimed.price.update(Measure(2450, '₹/quintal'), Confidence.HIGH, 1)

  state.qualification.decide(Verdict.NEGOTIATE, 'already decided earlier')

  fake = ConversationOutput(updates=[], reply='anything else?')
  with _mock_llm(fake):
    await conversation('ok thanks', state)

  assert state.qualification.reason == 'already decided earlier'


async def test_turn_takes_simple_path_when_no_tools_active():
  assert TOOLS == []
  fake = ConversationOutput(updates=[], reply='ok')
  with patch('services.agent.get_llm_response', new=AsyncMock(return_value=fake)):
    state = ConversationState()
    result = await conversation('hello', state)
  assert result['reply'] == 'ok'


async def test_turn_resolves_tool_call_and_persists_only_the_result():
  fake_tool_call = MagicMock()
  fake_tool_call.id = 'call_1'
  fake_tool_call.function.name = 'get_commodity_price'
  fake_tool_call.function.arguments = '{"crop": "wheat"}'
  fake_message = MagicMock()
  fake_message.tool_calls = [fake_tool_call]
  final_output = ConversationOutput(updates=[], reply='Let me check that for you.')
  with patch('services.agent.TOOLS', [{'type': 'function', 'function': {'name': 'get_commodity_price'}}]):
    with patch(
      'services.agent.get_llm_response',
      new=AsyncMock(side_effect=[fake_message, final_output]),
    ):
      state = ConversationState()
      result = await conversation("what's wheat going for?", state)
  assert result['reply'] == 'Let me check that for you.'
  tool_turns = [t for t in result['state'].history if t.role.value == 'tool']
  assert len(tool_turns) == 1
  assert tool_turns[0].content == 'Unknown tool: get_commodity_price'


async def test_closing_call_fires_only_when_qualification_completes_this_turn():
  state = ConversationState()
  state.claimed.crop.update('wheat', Confidence.HIGH, 1)
  state.claimed.quantity.update(Measure(40, 'quintal'), Confidence.HIGH, 1)
  state.claimed.crop_state.update(CropState.HARVESTED, Confidence.HIGH, 1)
  state.claimed.location.update('farm gate', Confidence.HIGH, 1)

  normal_reply = ConversationOutput(
    updates=[ExtractedField(field='price', value=MeasureValue(value=2450, unit='₹/quintal'), confidence='high')],
    reply='checking...',
  )
  closing_reply = ConversationOutput(updates=[], reply='closing message')
  mock_call = AsyncMock(side_effect=[normal_reply, closing_reply])

  with patch('services.agent.get_llm_response', new=mock_call):
    await conversation('2450 per quintal', state)

  assert mock_call.call_count == 2


async def test_no_closing_call_when_record_still_incomplete():
  fake = ConversationOutput(updates=[], reply='how much do you have?')
  mock_call = AsyncMock(return_value=fake)

  with patch('services.agent.get_llm_response', new=mock_call):
    state = ConversationState()
    await conversation('I have wheat', state)

  assert mock_call.call_count == 1


async def test_closing_reply_replaces_history_entry():
  state = ConversationState()
  state.claimed.crop.update('wheat', Confidence.HIGH, 1)
  state.claimed.quantity.update(Measure(40, 'quintal'), Confidence.HIGH, 1)
  state.claimed.crop_state.update(CropState.HARVESTED, Confidence.HIGH, 1)
  state.claimed.location.update('farm gate', Confidence.HIGH, 1)

  normal_reply = ConversationOutput(
    updates=[ExtractedField(field='price', value=MeasureValue(value=2450, unit='₹/quintal'), confidence='high')],
    reply='pre-close reply that should be overwritten',
  )
  closing_reply = ConversationOutput(updates=[], reply='the real closing reply')

  with patch(
    'services.agent.get_llm_response',
    new=AsyncMock(side_effect=[normal_reply, closing_reply]),
  ):
    result = await conversation('2450 per quintal', state)

  last_turn = result['state'].history[-1]
  assert last_turn.content == 'the real closing reply'
  assert 'pre-close' not in last_turn.content


async def test_does_not_requalify_no_extra_closing_call_on_later_turns():
  state = ConversationState()
  state.claimed.crop.update('wheat', Confidence.HIGH, 1)
  state.claimed.quantity.update(Measure(40, 'quintal'), Confidence.HIGH, 1)
  state.claimed.crop_state.update(CropState.HARVESTED, Confidence.HIGH, 1)
  state.claimed.location.update('farm gate', Confidence.HIGH, 1)
  state.claimed.price.update(Measure(2450, '₹/quintal'), Confidence.HIGH, 1)
  state.qualification.decide(Verdict.NEGOTIATE, 'already decided')

  fake = ConversationOutput(updates=[], reply='anything else?')
  mock_call = AsyncMock(return_value=fake)

  with patch('services.agent.get_llm_response', new=mock_call):
    await conversation('ok thanks', state)

  assert mock_call.call_count == 1


async def test_no_closing_call_when_qualified_but_unconfirmed():
  state = ConversationState()
  state.claimed.crop.update('wheat', Confidence.HIGH, 1)
  state.claimed.quantity.update(Measure(40, 'quintal'), Confidence.HIGH, 1)
  state.claimed.crop_state.update(CropState.HARVESTED, Confidence.LOW, 1)  # shaky
  state.claimed.location.update('Karnal', Confidence.HIGH, 1)

  normal_reply = ConversationOutput(
    updates=[ExtractedField(field='price', value=MeasureValue(value=2400, unit='quintal'), confidence='high')],
    reply='Is the wheat already harvested, or still in the field?',
  )
  mock_call = AsyncMock(return_value=normal_reply)

  with patch('services.agent.get_llm_response', new=mock_call):
    result = await conversation('2400 per quintal', state)

  assert result['state'].qualification.is_decided() is True
  assert result['done'] is False
  assert mock_call.call_count == 1
  assert result['reply'] == 'Is the wheat already harvested, or still in the field?'


async def test_closes_once_everything_including_confidence_is_settled():
  state = ConversationState()
  state.claimed.crop.update('wheat', Confidence.HIGH, 1)
  state.claimed.quantity.update(Measure(40, 'quintal'), Confidence.HIGH, 1)
  state.claimed.crop_state.update(CropState.HARVESTED, Confidence.HIGH, 1)  # confirmed
  state.claimed.location.update('Karnal', Confidence.HIGH, 1)

  normal_reply = ConversationOutput(
    updates=[ExtractedField(field='price', value=MeasureValue(value=2400, unit='quintal'), confidence='high')],
    reply='pre-close reply',
  )
  closing_reply = ConversationOutput(updates=[], reply="We're interested — final price after grading.")
  mock_call = AsyncMock(side_effect=[normal_reply, closing_reply])

  with patch('services.agent.get_llm_response', new=mock_call):
    result = await conversation('2400 per quintal', state)

  assert result['done'] is True
  assert mock_call.call_count == 2
  assert result['reply'] == "We're interested — final price after grading."
  assert result['state'].history[-1].content == "We're interested — final price after grading."


async def test_unlisted_crop_declines_immediately_via_qualify():
  fake = ConversationOutput(
    updates=[ExtractedField(field='crop', value='paddy', confidence='high')],
    reply='Got it, paddy.',
  )
  closing = ConversationOutput(updates=[], reply="We don't currently buy paddy, thanks for reaching out.")
  with patch('services.agent.get_llm_response', new=AsyncMock(side_effect=[fake, closing])):
    state = ConversationState()
    result = await conversation('I have paddy to sell', state)

  assert result['state'].qualification.verdict == Verdict.DECLINE
  assert 'paddy' in result['state'].qualification.reason
  assert result['done'] is True
