from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from openai import APITimeoutError, RateLimitError
from pydantic import BaseModel

from ..client import LLMCallFailed, get_llm_response


class DummyOutput(BaseModel):
  """A minimal Pydantic model standing in for ConversationState in these tests."""

  reply: str


def _fake_response(parsed):
  """Build a fake OpenAI response object shaped like what .parse() returns."""
  message = MagicMock()
  message.parsed = parsed
  choice = MagicMock()
  choice.message = message
  response = MagicMock()
  response.choices = [choice]
  return response


async def test_succeeds_on_first_attempt_no_retry_needed():
  fake_client = AsyncMock()
  fake_client.beta.chat.completions.parse = AsyncMock(return_value=_fake_response(DummyOutput(reply='hi')))
  with patch('shared.llm.client.get_llm_client', return_value=fake_client):
    result = await get_llm_response([{'role': 'user', 'content': 'hi'}], DummyOutput)

  assert result.reply == 'hi'
  assert fake_client.beta.chat.completions.parse.call_count == 1


async def test_retries_after_transient_error_then_succeeds():
  fake_client = AsyncMock()
  fake_client.beta.chat.completions.parse = AsyncMock(
    side_effect=[
      APITimeoutError(request=MagicMock()),  # fails once
      _fake_response(DummyOutput(reply='recovered')),  # succeeds on retry
    ]
  )
  with patch('shared.llm.client.get_llm_client', return_value=fake_client):
    with patch('asyncio.sleep', new=AsyncMock()):  # skip real backoff delay in tests
      result = await get_llm_response([{'role': 'user', 'content': 'hi'}], DummyOutput)

  assert result.reply == 'recovered'
  assert fake_client.beta.chat.completions.parse.call_count == 2


async def test_raises_llm_call_failed_after_exhausting_retries():
  fake_client = AsyncMock()
  fake_client.beta.chat.completions.parse = AsyncMock(side_effect=RateLimitError(message='rate limited', response=MagicMock(), body=None))
  with patch('shared.llm.client.get_llm_client', return_value=fake_client):
    with patch('asyncio.sleep', new=AsyncMock()):
      with pytest.raises(LLMCallFailed):
        await get_llm_response([{'role': 'user', 'content': 'hi'}], DummyOutput, max_retries=2)

  # max_retries=2 -> 3 total attempts
  assert fake_client.beta.chat.completions.parse.call_count == 3


async def test_retries_on_empty_parsed_response():
  # simulates the model returning something that didn't validate into the model
  fake_client = AsyncMock()
  fake_client.beta.chat.completions.parse = AsyncMock(
    side_effect=[
      _fake_response(None),  # empty/invalid first
      _fake_response(DummyOutput(reply='ok now')),  # good second attempt
    ]
  )
  with patch('shared.llm.client.get_llm_client', return_value=fake_client):
    with patch('asyncio.sleep', new=AsyncMock()):
      result = await get_llm_response([{'role': 'user', 'content': 'hi'}], DummyOutput)

  assert result.reply == 'ok now'
  assert fake_client.beta.chat.completions.parse.call_count == 2


async def test_backoff_is_called_between_retries():
  fake_client = AsyncMock()
  fake_client.beta.chat.completions.parse = AsyncMock(
    side_effect=[
      APITimeoutError(request=MagicMock()),
      _fake_response(DummyOutput(reply='ok')),
    ]
  )
  with patch('shared.llm.client.get_llm_client', return_value=fake_client):
    with patch('asyncio.sleep', new=AsyncMock()) as mock_sleep:
      await get_llm_response([{'role': 'user', 'content': 'hi'}], DummyOutput)

  mock_sleep.assert_called_once()
