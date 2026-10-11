import json

from config import settings
from utils import LLMCallFailed, get_llm_response, get_logger

from .contract import ConversationOutput, ExtractionOutput, ReplyOutput
from .extraction import apply_updates
from .prompt import CLOSING_INSTRUCTION, build_crop_confirmation_prompt, build_extraction_prompt, build_grade_confirmation_prompt, build_system_prompt
from .qualification import qualify
from .refdata import crop_config as config
from .refdata import load_refdata
from .schema import ConversationHistory, ConversationInitiator, ConversationState, Role
from .tools import TOOLS
from .validation import is_completed, is_done, unconfirmed

logger = get_logger(__name__)


def build_conversation_state(direction: str) -> ConversationState:
  """Build the initial state for one call, given who initiated it ('inbound' or 'outbound')."""
  state = ConversationState()
  state.meta.initiated_by = ConversationInitiator.US if direction == 'outbound' else ConversationInitiator.THEM
  return state


def _execute_tool(name: str, args: dict, refdata: dict) -> str:
  return f'Unknown tool: {name}'


async def _resolve_tool_calls(message, messages: list[dict], refdata: dict, state: ConversationState, turn_num: int, output_cls: type = ReplyOutput):
  """
  Execute the tool(s) the model requested. Only the tool's result gets persisted to state.history, as plain content.
  """
  for tool_call in message.tool_calls:
    args = json.loads(tool_call.function.arguments)
    result_txt = _execute_tool(tool_call.function.name, args, refdata)

    logger.info(f'Turn {turn_num} tool call: {tool_call.function.name}({tool_call.function.arguments}) -> {result_txt}')

    messages.append({'role': 'assistant', 'tool_calls': [{'id': tool_call.id, 'type': 'function', 'function': {'name': tool_call.function.name, 'arguments': tool_call.function.arguments}}]})
    messages.append({'role': 'tool', 'tool_call_id': tool_call.id, 'content': result_txt})
    state.history.append(ConversationHistory(role=Role.TOOL, content=result_txt))

  result = await get_llm_response(messages, output_cls, tools=TOOLS or None, model=settings.PROCUREMENT_MODEL)
  if not isinstance(result, output_cls):
    raise LLMCallFailed('Model requested a second tool call in one conversation turn - not supported yet.')
  return result


async def conversation(input: str, state: ConversationState, channel: str = 'voice', is_opening_turn: bool = False) -> dict:
  """
  One turn of the conversation, split into two calls with different inputs:
    - NLU (extraction): sees only the current record snapshot + the last thing we said + this one message. It decides `updates`. Deliberately NOT given the full transcript, so it can't silently re-derive/re-judge a field's confidence by re-reading old turns it wasn't asked about this turn - it only has this turn's message to go on.
    - NLG (reply): sees the full transcript (as before) + the record already updated by NLU, and
      decides only what to say next.
  """
  refdata = load_refdata()
  turn_num = state.meta.turn_count + 1
  logger.info(f'Turn {turn_num} input: {input}')

  crop_value = state.claimed.crop.value
  crop_config = config(crop_value, refdata) if crop_value else None

  # --- NLU: narrow extraction call, scoped to this one message ---
  if is_opening_turn:
    extracted_updates = list()
  else:
    last_question = state.history[-1].content if state.history else None
    extraction_prompt = build_extraction_prompt(channel=channel, refdata=refdata, record=state.claimed, last_question=last_question, farmer_input=input)
    extraction_messages = [{'role': 'system', 'content': extraction_prompt}, {'role': 'user', 'content': input}]

    try:
      extraction_result = await get_llm_response(extraction_messages, ExtractionOutput, model=settings.PROCUREMENT_MODEL)
    except LLMCallFailed:
      logger.error(f'Turn {turn_num} extraction call failed.')
      return {'reply': "Sorry, I'm having trouble right now - could you say that again?", 'state': state, 'done': False}

    extracted_updates = extraction_result.updates

  logger.info(f'Turn {turn_num} extracted: {[u.model_dump() for u in extracted_updates]}')

  # apply extracted updates
  updates, rejected_fields = apply_updates(state.claimed, extracted_updates, turn_num, crop_config=crop_config)
  logger.info(f'Turn {turn_num} applied {updates}/{len(extracted_updates)} updates, rejected: {rejected_fields}')
  state.rejected_fields = rejected_fields

  # qualify (re-resolve crop config: this turn's updates may have just supplied the crop)
  crop_value = state.claimed.crop.value
  crop_config = config(crop_value, refdata) if crop_value else None

  if crop_value and crop_config is None and not state.qualification.is_decided() and state.claimed.crop.confirmation_asked != crop_value:
    state.claimed.crop.confirmation_asked = crop_value
    confirm_prompt = build_crop_confirmation_prompt(channel=channel, crop=crop_value, farmer_input=input)
    confirm_messages = [{'role': 'system', 'content': confirm_prompt}]
    confirm_output = await get_llm_response(confirm_messages, ConversationOutput, model=settings.PROCUREMENT_MODEL)

    state.history.append(ConversationHistory(role=Role.USER, content=input))
    state.history.append(ConversationHistory(role=Role.ASSISTANT, content=confirm_output.reply))
    state.meta.turn_count = turn_num
    return {'reply': confirm_output.reply, 'state': state, 'done': False}

  grade_value = state.claimed.grade.value
  if grade_value and crop_config is not None and 'grades' in crop_config and grade_value not in crop_config['grades'] and not state.qualification.is_decided() and state.claimed.grade.confirmation_asked != grade_value:
    state.claimed.grade.confirmation_asked = grade_value
    confirm_prompt = build_grade_confirmation_prompt(channel=channel, crop=crop_value, grade=grade_value, valid_grades=list(crop_config['grades']), farmer_input=input)
    confirm_messages = [{'role': 'system', 'content': confirm_prompt}]
    confirm_output = await get_llm_response(confirm_messages, ConversationOutput, model=settings.PROCUREMENT_MODEL)

    state.history.append(ConversationHistory(role=Role.USER, content=input))
    state.history.append(ConversationHistory(role=Role.ASSISTANT, content=confirm_output.reply))
    state.meta.turn_count = turn_num
    return {'reply': confirm_output.reply, 'state': state, 'done': False}

  qualified = False
  if crop_value and not state.qualification.is_decided() and (crop_config is None or is_completed(state.claimed, crop_config)):
    state.qualification = qualify(state.claimed, refdata)
    qualified = True
    logger.info(f'Turn {turn_num} qualified: {state.qualification.verdict} - {state.qualification.reason}')

  done = state.qualification.is_decided() and (crop_config is None or is_done(state, crop_config))

  # --- NLG: reply generation, full transcript, record already updated above ---
  unconfirmed_fields = unconfirmed(state.claimed, crop_config) if crop_config else list()
  reply_prompt = build_system_prompt(channel=channel, refdata=refdata, state=state, unconfirmed_fields=unconfirmed_fields, is_opening_turn=is_opening_turn)
  if qualified and done:
    reply_prompt += CLOSING_INSTRUCTION

  reply_messages = [{'role': 'system', 'content': reply_prompt}]
  reply_messages += [{'role': history.role.value, 'content': history.content} for history in state.history]
  reply_messages.append({'role': 'user', 'content': input})

  try:
    reply_result = await get_llm_response(reply_messages, ReplyOutput, tools=TOOLS or None, model=settings.PROCUREMENT_MODEL)

    if not isinstance(reply_result, ReplyOutput):
      reply_output = await _resolve_tool_calls(reply_result, reply_messages, refdata, state, turn_num, ReplyOutput)
    else:
      reply_output = reply_result

  except LLMCallFailed:
    logger.error(f'Turn {turn_num} reply call failed.')
    return {'reply': "Sorry, I'm having trouble right now - could you say that again?", 'state': state, 'done': False}

  logger.info(f'Turn {turn_num} reply output: {reply_output.model_dump_json()}')

  # update state history - append-only, never rewritten
  state.history.append(ConversationHistory(role=Role.USER, content=input))
  state.history.append(ConversationHistory(role=Role.ASSISTANT, content=reply_output.reply))
  state.meta.turn_count = turn_num

  return {'reply': reply_output.reply, 'state': state, 'done': done}
