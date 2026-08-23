from openai import AsyncOpenAI

from config import settings

_llm_client = None


def get_llm_client() -> AsyncOpenAI:
  global _llm_client
  if _llm_client is None:
    _llm_client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
  return _llm_client
