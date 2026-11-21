from unittest.mock import AsyncMock, MagicMock, patch

from services import CLOSING_INSTRUCTION, TOOLS, Confidence, ConversationOutput, ConversationState, CropState, ExtractedField, Measure, MeasureValue, Role, Verdict, conversation
from services.contract import ExtractionOutput, ReplyOutput
from utils import LLMCallFailed

# conversation() makes two LLM calls per normal turn: a narrow extraction call
# (ExtractionOutput: just `updates`) and a reply call (ReplyOutput: just `reply`).
# The crop/grade confirmation branches short-circuit the reply call and return a
# single ConversationOutput (updates always empty there) instead. There is no
# longer a separate "closing call" - once qualification completes and the record
# is done, the SAME reply call's prompt just gets CLOSING_INSTRUCTION appended.


def _ext(*updates: ExtractedField) -> ExtractionOutput:
  return ExtractionOutput(updates=list(updates))


def _reply(text: str) -> ReplyOutput:
  return ReplyOutput(reply=text)


def _confirm(text: str) -> ConversationOutput:
  return ConversationOutput(updates=[], reply=text)


def _mock_llm(*side_effect):
  """Patch get_llm_response with a fixed sequence of return values, one per call."""
  return patch('services.agent.get_llm_response', new=AsyncMock(side_effect=list(side_effect)))


def _ready_wheat_state() -> ConversationState:
  """A wheat record with every field but price already confirmed - one more
  extraction away from is_completed()."""
  state = ConversationState()
  state.claimed.crop.update('wheat', Confidence.HIGH, 1)
  state.claimed.quantity.update(Measure(40, 'quintal'), Confidence.HIGH, 1)
  state.claimed.crop_state.update(CropState.HARVESTED, Confidence.HIGH, 1)
  state.claimed.location.update('farm gate', Confidence.HIGH, 1)
  return state


# --- Basic turn mechanics -----------------------------------------------------


async def test_turn_applies_extracted_updates():
  with _mock_llm(_ext(ExtractedField(field='crop', value='wheat', confidence='high')), _reply('Got it - wheat. How much do you have?')):
    state = ConversationState()
    result = await conversation('I have wheat to sell', state)

  assert result['state'].claimed.crop.value == 'wheat'
  assert result['state'].claimed.crop.confidence is Confidence.HIGH
  assert result['reply'] == 'Got it - wheat. How much do you have?'


async def test_turn_appends_to_history():
  with _mock_llm(_ext(), _reply('Sure, tell me more.')):
    state = ConversationState()
    result = await conversation('hello', state)

  history = result['state'].history
  assert len(history) == 2
  assert history[0].role is Role.USER
  assert history[0].content == 'hello'
  assert history[1].role is Role.ASSISTANT
  assert history[1].content == 'Sure, tell me more.'


async def test_turn_increments_turn_count():
  with _mock_llm(_ext(), _reply('ok'), _ext(), _reply('ok again')):
    state = ConversationState()
    await conversation('first', state)
    result = await conversation('second', state)

  assert result['state'].meta.turn_count == 2


async def test_opening_turn_skips_extraction_call():
  # is_opening_turn=True means the farmer hasn't spoken yet - there's nothing to
  # extract, so only the reply call happens.
  mock_call = AsyncMock(return_value=_reply('Namaste! Calling about produce you may have to sell.'))
  with patch('services.agent.get_llm_response', new=mock_call):
    state = ConversationState()
    result = await conversation('', state, is_opening_turn=True)

  assert mock_call.call_count == 1
  assert result['reply'] == 'Namaste! Calling about produce you may have to sell.'


async def test_turn_rejects_bad_extraction_without_crashing():
  with _mock_llm(_ext(ExtractedField(field='quantity', value='a lot', confidence='high')), _reply('How much roughly?')):
    state = ConversationState()
    result = await conversation('I have a lot of wheat', state)

  assert result['state'].claimed.quantity.is_known() is False  # rejected, didn't crash
  assert result['reply'] == 'How much roughly?'


async def test_rejected_field_is_tracked_on_extras():
  with _mock_llm(_ext(ExtractedField(field='quantity', value='a lot', confidence='high')), _reply('How much roughly?')):
    state = ConversationState()
    result = await conversation('I have a lot of wheat', state)

  rejected_fields = [field for field, _reason in result['state'].extras.rejected_fields]
  assert rejected_fields == ['quantity']


async def test_turn_returns_apology_when_extraction_call_fails():
  with patch('services.agent.get_llm_response', new=AsyncMock(side_effect=LLMCallFailed('boom'))):
    state = ConversationState()
    result = await conversation('hello', state)

  assert 'having trouble' in result['reply'].lower()
  assert result['done'] is False
  assert len(result['state'].history) == 0  # failed before history was touched


async def test_turn_returns_apology_when_reply_call_fails():
  # extraction succeeds; the second (reply) call is the one that fails this time.
  with _mock_llm(_ext(), LLMCallFailed('boom')):
    state = ConversationState()
    result = await conversation('hello', state)

  assert 'having trouble' in result['reply'].lower()
  assert result['done'] is False
  assert len(result['state'].history) == 0


# --- Qualification gating -----------------------------------------------------


async def test_turn_does_not_qualify_when_record_incomplete():
  with _mock_llm(_ext(ExtractedField(field='crop', value='wheat', confidence='high')), _reply('How much do you have?')):
    state = ConversationState()
    result = await conversation('wheat', state)

  assert result['state'].qualification.is_decided() is False
  assert result['done'] is False


async def test_turn_qualifies_once_record_becomes_complete():
  state = _ready_wheat_state()

  with _mock_llm(_ext(ExtractedField(field='price', value=MeasureValue(value=2450, unit='quintal'), confidence='high')), _reply("Great, we'll follow up soon. Thanks!")):
    result = await conversation('2450 per quintal', state)

  assert result['state'].qualification.is_decided() is True
  assert result['state'].qualification.verdict == Verdict.NEGOTIATE
  assert result['reply'] == "Great, we'll follow up soon. Thanks!"
  assert result['done'] is True


async def test_qualification_is_recomputed_every_turn_the_record_is_complete():
  # there's no "don't requalify once decided" guard - qualify() reruns whenever
  # crop is set and the record is complete, every turn. Harmless, since the
  # verdict it (re)computes from the same unchanged record is identical.
  state = _ready_wheat_state()
  state.claimed.price.update(Measure(2450, '₹/quintal'), Confidence.HIGH, 1)
  state.qualification.decide(Verdict.NEGOTIATE, 'Within market band, worth pursuing, price finalized after looking and grading product', price=Measure(2450, '₹/quintal'))

  with _mock_llm(_ext(), _reply('anything else?')):
    result = await conversation('ok thanks', state)

  assert result['state'].qualification.verdict == Verdict.NEGOTIATE
  assert result['state'].qualification.reason == 'Within market band, worth pursuing, price finalized after looking and grading product'


async def test_forward_verdict_still_requires_price_to_even_qualify():
  # qualify()'s FORWARD branch doesn't look at price at all, but is_completed()
  # (the gate before qualify() is even called) still requires it - so a standing
  # crop with no price given never reaches qualify().
  state = ConversationState()
  state.claimed.crop.update('wheat', Confidence.HIGH, 1)
  state.claimed.quantity.update(Measure(40, 'quintal'), Confidence.HIGH, 1)
  state.claimed.crop_state.update(CropState.STANDING, Confidence.HIGH, 1)
  state.claimed.location.update('farm gate', Confidence.HIGH, 1)

  with _mock_llm(_ext(), _reply('and your asking price?')):
    result = await conversation('still standing in the field', state)

  assert result['state'].qualification.is_decided() is False

  with _mock_llm(_ext(ExtractedField(field='price', value=MeasureValue(value=2450, unit='quintal'), confidence='high')), _reply("We'll revisit once it's harvested.")):
    result = await conversation('2450 per quintal', result['state'])

  assert result['state'].qualification.verdict == Verdict.FORWARD
  assert result['done'] is True


# --- Crop-change reset (changed by #30: reset now happens AFTER apply_updates,
# keyed on `keep_turn`, so same-turn fields survive) ---------------------------


async def test_crop_change_in_same_turn_keeps_that_turns_other_fields():
  state = ConversationState()
  with _mock_llm(
    _ext(
      ExtractedField(field='crop', value='onion', confidence='high'),
      ExtractedField(field='quantity', value=MeasureValue(value=30, unit='quintal'), confidence='high'),
      ExtractedField(field='crop_state', value='harvested', confidence='high'),
      ExtractedField(field='price', value=MeasureValue(value=2000, unit='quintal'), confidence='high'),
    ),
    _reply('okay, tell me more'),
  ):
    result = await conversation('I have onion, 30 quintal, harvested, 2000 per quintal', state)

  # sanity check: onion's details landed before the crop switch below.
  assert result['state'].claimed.quantity.value.value == 30

  # next turn: farmer switches to a different crop, stating its own
  # quantity/crop_state/price in the SAME turn - these must survive the
  # crop-dependent reset, not get wiped back to blank right after being set.
  with _mock_llm(
    _ext(
      ExtractedField(field='crop', value='wheat', confidence='high'),
      ExtractedField(field='quantity', value=MeasureValue(value=25, unit='quintal'), confidence='high'),
      ExtractedField(field='crop_state', value='standing', confidence='high'),
      ExtractedField(field='price', value=MeasureValue(value=2400, unit='quintal'), confidence='high'),
    ),
    _reply('got it, wheat instead'),
  ):
    result = await conversation('actually, wheat - 25 quintal, standing, 2400 per quintal', result['state'])

  claimed = result['state'].claimed
  assert claimed.crop.value == 'wheat'
  assert claimed.quantity.value.value == 25
  assert claimed.quantity.confidence is Confidence.HIGH
  assert claimed.crop_state.value == CropState.STANDING
  assert claimed.price.value.value == 2400


async def test_crop_change_still_wipes_fields_not_restated_that_turn():
  state = ConversationState()
  with _mock_llm(
    _ext(
      ExtractedField(field='crop', value='onion', confidence='high'),
      ExtractedField(field='quantity', value=MeasureValue(value=30, unit='quintal'), confidence='high'),
      ExtractedField(field='price', value=MeasureValue(value=2000, unit='quintal'), confidence='high'),
    ),
    _reply('okay, tell me more'),
  ):
    result = await conversation('onion, 30 quintal, 2000 per quintal', state)

  # this turn only restates quantity for the new crop - price is carried over
  # from onion and must be wiped, not kept pointing at the wrong crop's price.
  with _mock_llm(
    _ext(
      ExtractedField(field='crop', value='wheat', confidence='high'),
      ExtractedField(field='quantity', value=MeasureValue(value=25, unit='quintal'), confidence='high'),
    ),
    _reply('got it, wheat instead'),
  ):
    result = await conversation('actually, wheat - 25 quintal', result['state'])

  claimed = result['state'].claimed
  assert claimed.quantity.value.value == 25  # restated this turn - kept
  assert claimed.price.is_known() is False  # stale from onion - wiped


# --- Closing instruction -------------------------------------------------------


async def test_closing_instruction_included_in_reply_prompt_when_done():
  state = _ready_wheat_state()
  mock_call = AsyncMock(side_effect=[_ext(ExtractedField(field='price', value=MeasureValue(value=2450, unit='quintal'), confidence='high')), _reply('closing message')])

  with patch('services.agent.get_llm_response', new=mock_call):
    result = await conversation('2450 per quintal', state)

  assert mock_call.call_count == 2  # still just extraction + reply, no extra call
  assert result['done'] is True
  reply_messages = mock_call.call_args_list[1].args[0]
  system_prompt = reply_messages[0]['content']
  assert CLOSING_INSTRUCTION.strip() in system_prompt


async def test_no_closing_instruction_when_record_still_incomplete():
  mock_call = AsyncMock(side_effect=[_ext(ExtractedField(field='crop', value='wheat', confidence='high')), _reply('how much do you have?')])

  with patch('services.agent.get_llm_response', new=mock_call):
    state = ConversationState()
    await conversation('I have wheat', state)

  reply_messages = mock_call.call_args_list[1].args[0]
  system_prompt = reply_messages[0]['content']
  assert CLOSING_INSTRUCTION.strip() not in system_prompt


# --- Tool-call resolution ------------------------------------------------------


async def test_turn_takes_simple_path_when_no_tools_active():
  assert TOOLS == []
  with _mock_llm(_ext(), _reply('ok')):
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

  with patch('services.agent.TOOLS', [{'type': 'function', 'function': {'name': 'get_commodity_price'}}]):
    with _mock_llm(_ext(), fake_message, _reply('Let me check that for you.')):
      state = ConversationState()
      result = await conversation("what's wheat going for?", state)

  assert result['reply'] == 'Let me check that for you.'
  tool_turns = [t for t in result['state'].history if t.role.value == 'tool']
  assert len(tool_turns) == 1
  assert tool_turns[0].content == 'Unknown tool: get_commodity_price'


# --- Crop confirmation -> decline-offer flow (changed by #13) -----------------


async def test_unrecognized_crop_asks_to_confirm_before_declining():
  state = ConversationState()

  with _mock_llm(_ext(ExtractedField(field='crop', value='mango', confidence='high')), _confirm('Just to confirm, did you say mango, or something else?')):
    result = await conversation('I have mango to sell', state)

  # not declined yet - this turn is only the crop-name confirmation.
  assert result['state'].qualification.is_decided() is False
  assert result['done'] is False
  assert result['reply'] == 'Just to confirm, did you say mango, or something else?'
  assert result['state'].claimed.crop.confirmation_asked == 'mango'


async def test_reaffirmed_unrecognized_crop_offers_alternative_instead_of_closing():
  # turn 1: crop named, confirmation asked (see test above).
  state = ConversationState()
  with _mock_llm(_ext(ExtractedField(field='crop', value='mango', confidence='high')), _confirm('Did you say mango?')):
    result = await conversation('I have mango to sell', state)

  # turn 2: farmer reaffirms - now it proceeds straight to qualify(), declines
  # (we don't buy mango), but offers an alternative instead of closing the call.
  with _mock_llm(_ext(), _reply('We currently buy wheat or onion - do you have either of those?')):
    result = await conversation('yes, mango', result['state'])

  assert result['state'].qualification.verdict == Verdict.DECLINE
  assert result['state'].extras.crop_decline_offer_made is True
  assert result['done'] is False  # not closed yet - alternative offered first


async def test_declining_the_alternative_closes_the_call():
  state = ConversationState()
  with _mock_llm(_ext(ExtractedField(field='crop', value='mango', confidence='high')), _confirm('Did you say mango?')):
    result = await conversation('I have mango to sell', state)
  with _mock_llm(_ext(), _reply('We buy wheat or onion instead - interested?')):
    result = await conversation('yes, mango', result['state'])

  # turn 3: farmer has nothing else - the offer was already made once, so this
  # time it closes instead of offering again.
  mock_call = AsyncMock(side_effect=[_ext(), _reply('No problem, thanks for calling.')])
  with patch('services.agent.get_llm_response', new=mock_call):
    result = await conversation("no, that's all", result['state'])

  assert result['done'] is True
  reply_messages = mock_call.call_args_list[1].args[0]
  assert CLOSING_INSTRUCTION.strip() in reply_messages[0]['content']


# --- Grade confirmation -> nearest-grade-offer flow ----------------------------


def _ready_onion_state() -> ConversationState:
  state = ConversationState()
  state.claimed.crop.update('onion', Confidence.HIGH, 1)
  state.claimed.quantity.update(Measure(30, 'quintal'), Confidence.HIGH, 1)
  state.claimed.crop_state.update(CropState.HARVESTED, Confidence.HIGH, 1)
  state.claimed.location.update('Karnal', Confidence.HIGH, 1)
  return state


async def test_unmatched_grade_asks_to_confirm_before_declining():
  state = _ready_onion_state()

  with _mock_llm(_ext(ExtractedField(field='grade', value='A', confidence='high'), ExtractedField(field='price', value=MeasureValue(value=2150, unit='quintal'), confidence='high')), _confirm('Is that super, mota, medium, or golta?')):
    result = await conversation('A grade, 2150 per quintal', state)

  assert result['state'].qualification.is_decided() is False
  assert result['done'] is False
  assert result['state'].claimed.grade.confirmation_asked == 'A'


async def test_reaffirmed_unmatched_grade_offers_nearest_match_by_price():
  state = _ready_onion_state()
  with _mock_llm(_ext(ExtractedField(field='grade', value='A', confidence='high'), ExtractedField(field='price', value=MeasureValue(value=2150, unit='quintal'), confidence='high')), _confirm('Is that super, mota, medium, or golta?')):
    result = await conversation('A grade, 2150 per quintal', state)

  # reaffirm the same unrecognized grade - declines (no reference price for "A"),
  # but 2150 is closest to "super" (2200) among onion's known grades, so it's
  # offered as the nearest match instead of closing.
  with _mock_llm(_ext(), _reply('A grade is not something we track - did you mean super, around ₹2200/quintal?')):
    result = await conversation('yes, still A grade', result['state'])

  assert result['state'].qualification.verdict == Verdict.DECLINE
  assert result['state'].extras.grade_nearest_offer_made is True
  assert result['done'] is False


async def test_accepting_the_nearest_grade_qualifies_and_closes():
  state = _ready_onion_state()
  with _mock_llm(_ext(ExtractedField(field='grade', value='A', confidence='high'), ExtractedField(field='price', value=MeasureValue(value=2150, unit='quintal'), confidence='high')), _confirm('Is that super, mota, medium, or golta?')):
    result = await conversation('A grade, 2150 per quintal', state)
  with _mock_llm(_ext(), _reply('Did you mean super, around ₹2200/quintal?')):
    result = await conversation('yes, still A grade', result['state'])

  # farmer accepts the offered grade - now it resolves to a real grade, price
  # is within band (2150 <= 2200*1.05), qualifies as NEGOTIATE and closes.
  with _mock_llm(_ext(ExtractedField(field='grade', value='super', confidence='high')), _reply("Great, we're interested - final price after grading.")):
    result = await conversation('yes, super is fine', result['state'])

  assert result['state'].qualification.verdict == Verdict.NEGOTIATE
  assert result['done'] is True
  assert result['reply'] == "Great, we're interested - final price after grading."
