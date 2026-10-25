import asyncio
import time

from openai import APIError, APITimeoutError, AsyncOpenAI, RateLimitError
from pydantic import BaseModel, ValidationError

from config import settings

from ..logging import get_logger

logger = get_logger(__name__)

_llm_client = None


def get_llm_client() -> AsyncOpenAI:
  global _llm_client
  if _llm_client is None:
    _llm_client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
  return _llm_client


class LLMCallFailed(Exception):
  """Raised when a LLM call fails."""


async def get_llm_response(messages: list[dict], response_model: type[BaseModel], tools: list[dict] | None = None, model: str | None = None, temperature: float = 0, max_retries=2):
  """
  Call the LLM and get back either:
    - a validated response_model instance (no tools requested, or tools
      given but the model didn't call one this turn), or
    - the raw message object, if tools were given and the model requested
      one (caller must check message.tool_calls and handle the round-trip).

  Retries on transient API errors and on responses that fail to validate,
  with a short backoff. Raises LLMCallFailed after exhausting attempts.
  """
  client = get_llm_client()
  error: Exception | None = None
  for attempt in range(1, max_retries + 2):
    t0 = time.perf_counter()
    try:
      kwargs = {'model': model, 'messages': messages, 'response_format': response_model, 'temperature': temperature}
      if tools:
        kwargs['tools'] = tools

      response = await client.beta.chat.completions.parse(**kwargs)

      message = response.choices[0].message
      duration_ms = round((time.perf_counter() - t0) * 1000)

      if tools and message.tool_calls:
        logger.info('llm.response', model=model, duration_ms=duration_ms, attempt=attempt, tool_call=True)
        return message

      if message.parsed is None:
        raise ValidationError.from_exception_data('Empty structured response', [])

      logger.info('llm.response', model=model, duration_ms=duration_ms, attempt=attempt, tool_call=False)
      return message.parsed

    except (RateLimitError, APITimeoutError, APIError) as err:
      error = err
      logger.warning('llm.retry', model=model, attempt=attempt, error_type=type(err).__name__, error=str(err))
      await asyncio.sleep(0.5 * attempt)

    except ValidationError as err:
      error = err
      logger.warning('llm.invalid_response', model=model, attempt=attempt, error=str(err))
      await asyncio.sleep(0.5 * attempt)

  logger.error('llm.failed', model=model, attempts=max_retries + 1, error=str(error))
  raise LLMCallFailed(f'LLM call failed after {max_retries + 1} attempts: {error}') from error
