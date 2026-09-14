import json

from config import settings
from utils import LLMCallFailed, get_llm_response, get_logger

from .contract import ConversationOutput
from .extraction import apply_updates
from .prompt import CLOSING_INSTRUCTION, build_system_prompt
from .qualification import qualify
from .refdata import crop_config as config
from .refdata import load_refdata
from .schema import ConversationHistory, ConversationState, Role
from .tools import TOOLS
from .validation import is_completed, is_done, unconfirmed

logger = get_logger(__name__)


def _execute_tool(name: str, args: dict, refdata: dict) -> str:
  return f'Unknown tool: {name}'


async def _resolve_tool_calls(message, messages: list[dict], refdata: dict, state: ConversationState, turn_num: int) -> ConversationOutput:
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

  result = await get_llm_response(messages, ConversationOutput, tools=TOOLS or None, model=settings.PROCUREMENT_MODEL)
  if not isinstance(result, ConversationOutput):
    raise LLMCallFailed('Model requested a second tool call in one conversation turn - not supported yet.')
  return result


async def conversation(input: str, state: ConversationState, channel: str = 'voice', is_opening_turn: bool = False) -> dict:
  """One turn of the conversation: extract, update memory, qualify and respond."""
  refdata = load_refdata()
  turn_num = state.meta.turn_count + 1
  logger.info(f'Turn {turn_num} input: {input}')

  crop_value = state.claimed.crop.value
  crop_config = config(crop_value, refdata) if crop_value else None

  unconfirmed_fields = unconfirmed(state.claimed, crop_config) if crop_config else []
  system_prompt = build_system_prompt(channel=channel, refdata=refdata, state=state, unconfirmed_fields=unconfirmed_fields, is_opening_turn=is_opening_turn)

  messages = [{'role': 'system', 'content': system_prompt}]
  messages += [{'role': history.role.value, 'content': history.content} for history in state.history]
  messages.append({'role': 'user', 'content': input})

  try:
    result = await get_llm_response(messages, ConversationOutput, tools=TOOLS or None, model=settings.PROCUREMENT_MODEL)

    if not isinstance(result, ConversationOutput):
      output = await _resolve_tool_calls(result, messages, refdata, state, turn_num)
    else:
      output = result

  except LLMCallFailed:
    logger.error(f'Turn {turn_num} LLM call failed.')
    return {'reply': "Sorry, I'm having trouble right now - could you say that again?", 'state': state, 'done': False}

  logger.info(f'Turn {turn_num} raw output: {output.model_dump_json()}')

  # apply extracted updates
  updates, rejected_fields = apply_updates(state.claimed, output.updates, turn_num, crop_config=crop_config)
  logger.info(f'Turn {turn_num} applied {updates}/{len(output.updates)} updates, rejected: {rejected_fields}')

  # update state history
  state.history.append(ConversationHistory(role=Role.USER, content=input))
  state.history.append(ConversationHistory(role=Role.ASSISTANT, content=output.reply))
  state.meta.turn_count = turn_num
  state.rejected_fields = rejected_fields

  # qualify (re-resolve crop config: this turn's updates may have just supplied the crop)
  crop_value = state.claimed.crop.value
  crop_config = config(crop_value, refdata) if crop_value else None

  qualified = False
  if crop_value and not state.qualification.is_decided() and (crop_config is None or is_completed(state.claimed, crop_config)):
    state.qualification = qualify(state.claimed, refdata)
    qualified = True
    logger.info(f'Turn {turn_num} qualified: {state.qualification.verdict} - {state.qualification.reason}')

  done = state.qualification.is_decided() and (crop_config is None or is_done(state, crop_config))
  if qualified and done:
    closing_prompt = build_system_prompt(channel=channel, refdata=refdata, state=state) + CLOSING_INSTRUCTION
    closing_messages = [{'role': 'system', 'content': closing_prompt}]
    closing_messages += [{'role': history.role.value, 'content': history.content} for history in state.history]
    closing_output = await get_llm_response(closing_messages, ConversationOutput, model=settings.PROCUREMENT_MODEL)
    output = closing_output
    state.history[-1] = ConversationHistory(role=Role.ASSISTANT, content=output.reply)

  return {'reply': output.reply, 'state': state, 'done': done}
