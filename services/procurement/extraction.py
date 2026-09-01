from shared import get_logger

from .contract import ExtractedField, MeasureValue
from .schema import ClaimedRecord, Confidence, CropState, Measure, Reading

logger = get_logger(__name__)

_CONFIDENCE = {'low': Confidence.LOW, 'high': Confidence.HIGH}


def _validate_text(raw) -> str | None:
  """Accept any non-empty string, stripped of surrounding whitespace."""
  if not isinstance(raw, str):
    return None
  raw = raw.strip()
  return raw or None


def _validate_measure(raw) -> Measure | None:
  """Convert a MeasureValue into our Measure type."""
  if not isinstance(raw, MeasureValue):
    return None
  return Measure(raw.value, raw.unit)


def _validate_crop_state(raw) -> CropState | None:
  """Parse raw text into a real CropState, rejecting anything outside the three known states."""
  if not isinstance(raw, str):
    return None
  try:
    return CropState(raw.strip().lower())
  except ValueError:
    return None


_VALIDATORS = {
  'quantity': _validate_measure,
  'price': _validate_measure,
  'crop_state': _validate_crop_state,
}


def apply_update(record: ClaimedRecord, update: ExtractedField, turn: int) -> bool:
  """Validate and apply one extracted field update to the record."""
  validator = _VALIDATORS.get(update.field, _validate_text)
  value = validator(update.value)
  if value is None:
    logger.warning('Update rejected: {update.field} -> {update.value} invalid.')
    return False

  field: Reading = getattr(record, update.field)
  field.update(value, _CONFIDENCE[update.confidence], turn)
  return True


def apply_updates(record: ClaimedRecord, updates: list[ExtractedField], turn: int) -> int:
  """Apply a batch of updates, return how many were actually applied"""
  return sum(apply_update(record, update, turn) for update in updates)
