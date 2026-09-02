import json

from config import settings
from shared import LLMCallFailed, get_llm_response, get_logger

from .contract import ConversationOutput
from .extraction import apply_updates
from .prompt import build_system_prompt
from .qualification import qualify
from .refdata import crop_config as config
from .refdata import load_refdata
from .schema import ConversationHistory, ConversationState, Role
from .tools import TOOLS
from .validation import is_completed, is_done

logger = get_logger(__name__)


def _render_refdata(refdata: dict) -> str:
  """Render refdata as plain text for the prompt."""
  lines = list()
  for crop, crop_config in refdata.get('crops', {}).items():
    if 'grades' in crop_config:
      grades = ', '.join(f'{g} (₹{p}/qtl)' for g, p in crop_config['grades'].items())
      lines.append(f'- {crop}: graded - {grades}')
    else:
      lines.append(f'- {crop}: ₹{crop_config["price"]}/qtl (ungraded)')
  return '\n'.join(lines)


def _render_verdict(state: ConversationState) -> str:
  """Render the current qualification as VERDICT/REASON/TARGET PRICE text."""
  qualification = state.qualification
  target_price = f'{qualification.price.value} {qualification.price.unit}' if qualification.price else 'Not applicable'
  return f'VERDICT: {qualification.verdict.value}\nREASON: {qualification.reason}\nTARGET PRICE: {target_price}'


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


async def conversation(input: str, state: ConversationState, channel: str = 'voice') -> dict:
  """One turn of the conversation: extract, update memory, qualify and respond."""
  refdata = load_refdata()
  turn_num = state.meta.turn_count + 1

  verdict_context = _render_verdict(state) if state.qualification.is_decided() else ''
  system_prompt = build_system_prompt(channel=channel, refdata_context=_render_refdata(refdata), verdict_context=verdict_context)

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
  updates = apply_updates(state.claimed, output.updates, turn_num)
  logger.info(f'Turn {turn_num} applied {updates}/{len(output.updates)} updates.')

  # update state history
  state.history.append(ConversationHistory(role=Role.USER, content=input))
  state.history.append(ConversationHistory(role=Role.ASSISTANT, content=output.reply))
  state.meta.turn_count = turn_num

  # resolve crop
  crop = state.claimed.crop.value
  crop_config = config(crop, refdata) if crop else None

  # qualify
  if crop_config is not None and not state.qualification.is_decided() and is_completed(state.claimed, crop_config):
    state.qualification = qualify(state.claimed, refdata)
    logger.info(f'Turn {turn_num} qualified: {state.qualification.verdict} - {state.qualification.reason}')

  done = crop_config is not None and is_done(state, crop_config)

  return {'reply': output.reply, 'state': state, 'done': done}
