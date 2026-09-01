import asyncio

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


async def get_llm_response(messages: list[dict], response_model: type[BaseModel], model: str | None = None, max_retries=2):
  """
  Call the LLM and get back a validated instance of response_model.
  Retries on transient errors (rate limit, timeout) and on responses that fail to parse/validate, with a short backoff. Raises LLMCallFailed if all attempts are exhausted — callers decide how to degrade gracefully (e.g. turn() can apologize and ask the farmer to repeat themselves), rather than this function
  """
  client = get_llm_client()
  error: Exception | None = None
  for attempt in range(1, max_retries + 2):
    try:
      response = await client.beta.chat.completions.parse(model=model, messages=messages, response_format=response_model)

      parsed_response = response.choices[0].message.parsed

      if parsed_response is None:
        raise ValidationError.from_exception_data('Empty structured response', [])
      return parsed_response

    except (RateLimitError, APITimeoutError, APIError) as err:
      error = err
      logger.warning(f'LLM call attempt {attempt} failed {type(err).__name__}, err')
      await asyncio.sleep(0.5 * attempt)

    except ValidationError as err:
      error = err
      logger.warning(f'LLM call attempt {attempt} returned invalid. structure: {err}')

  raise LLMCallFailed(f'LLM call failed after {max_retries + 1} attempts: {error}') from error
