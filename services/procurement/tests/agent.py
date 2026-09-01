from unittest.mock import AsyncMock, patch

from shared import LLMCallFailed

from ..agent import _render_refdata, _render_verdict, conversation
from ..contract import ConversationOutput, ExtractedField, MeasureValue
from ..schema import Confidence, ConversationState, CropState, Measure, Role, Verdict


def _mock_llm(output: ConversationOutput):
  """Patch call_structured to return a fixed ConversationOutput instead of calling the API."""
  return patch('services.procurement.agent.get_llm_response', new=AsyncMock(return_value=output))


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
  with patch('services.procurement.agent.get_llm_response', new=AsyncMock(side_effect=LLMCallFailed('boom'))):
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
  # pre-fill everything except the last required field
  state = ConversationState()
  state.claimed.crop.update('wheat', Confidence.HIGH, 1)
  state.claimed.quantity.update(Measure(40, 'quintal'), Confidence.HIGH, 1)
  state.claimed.crop_state.update(CropState.HARVESTED, Confidence.HIGH, 1)
  state.claimed.location.update('farm gate', Confidence.HIGH, 1)
  # price still missing

  fake = ConversationOutput(
    updates=[ExtractedField(field='price', value=MeasureValue(value=2450, unit='₹/quintal'), confidence='high')],
    reply='Thanks — let me check that for you.',
  )
  with _mock_llm(fake):
    result = await conversation('2450 per quintal', state)

  assert result['state'].qualification.is_decided() is True


async def test_turn_does_not_requalify_once_decided():
  # a qualification already exists; a later turn should not overwrite it
  state = ConversationState()
  state.claimed.crop.update('wheat', Confidence.HIGH, 1)
  state.claimed.quantity.update(Measure(40, 'quintal'), Confidence.HIGH, 1)
  state.claimed.crop_state.update(CropState.HARVESTED, Confidence.HIGH, 1)
  state.claimed.location.update('farm gate', Confidence.HIGH, 1)
  state.claimed.price.update(Measure(2450, '₹/quintal'), Confidence.HIGH, 1)
  from services.procurement.schema import Verdict

  state.qualification.decide(Verdict.NEGOTIATE, 'already decided earlier')

  fake = ConversationOutput(updates=[], reply='anything else?')
  with _mock_llm(fake):
    await conversation('ok thanks', state)

  assert state.qualification.reason == 'already decided earlier'


def test_render_refdata_graded_crop():
  refdata = {'crops': {'onion': {'grades': {'mota': 2000}}}}
  text = _render_refdata(refdata)
  assert 'onion' in text and 'mota' in text and '2000' in text


def test_render_refdata_ungraded_crop():
  refdata = {'crops': {'wheat': {'price': 2450}}}
  text = _render_refdata(refdata)
  assert 'wheat' in text and '2450' in text and 'ungraded' in text


def test_render_verdict_includes_target_price():
  state = ConversationState()
  state.qualification.decide(Verdict.NEGOTIATE, 'in band', price=Measure(2450, '₹/quintal'))
  text = _render_verdict(state)
  assert 'negotiate' in text.lower()
  assert '2450' in text
