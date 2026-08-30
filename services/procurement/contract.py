from typing import Literal

from pydantic import BaseModel, Field

FIELD_NAMES = Literal[
  'crop',
  'variety',
  'quantity',
  'grade',
  'crop_state',
  'location',
  'price',
  'payment_terms',
  'handover',
  'transport',
  'contact',
]


class MeasureValue(BaseModel):
  """An amount paired with its unit - the two are meaningless apart."""

  value: float
  unit: str


class ExtractedField(BaseModel):
  """One fact that farmer stated, to be written to the record."""

  field: FIELD_NAMES
  value: str | MeasureValue
  confidence: Literal['low', 'high']


class TurnOutput(BaseModel):
  """Everything turn() needs back from one LLM call."""

  updates: list[ExtractedField] = Field(default_factory=list)
  reply: str
