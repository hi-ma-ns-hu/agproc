from utils import get_logger

from .contract import ExtractedField, MeasureValue
from .schema import ClaimedRecord, Confidence, CropState, Measure, Reading
from .unit import to_quintal_price, to_quintal_weight

logger = get_logger(__name__)

_CONFIDENCE = {'low': Confidence.LOW, 'high': Confidence.HIGH}


def _validate_text(raw) -> str | None:
  """Accept any non-empty string, stripped of surrounding whitespace."""
  if not isinstance(raw, str):
    return None
  raw = raw.strip()
  return raw or None


def _validate_measure(raw, field: str) -> Measure | None:
  """Convert a MeasureValue into our Measure type."""
  if not isinstance(raw, MeasureValue):
    return None

  unit = (raw.unit or '').strip()
  if field == 'price':
    per_unit = unit.split('/', 1)[1] if '/' in unit else unit
    if not per_unit:
      return None
    result = to_quintal_price(raw.value, per_unit)
  else:
    if not unit:
      return None
    result = to_quintal_weight(raw.value, unit)

  if result is None:
    return None
  value, unit = result
  return Measure(value, unit)


def _validate_crop_state(raw) -> CropState | None:
  """Parse raw text into a real CropState, rejecting anything outside the three known states."""
  if not isinstance(raw, str):
    return None
  try:
    return CropState(raw.strip().lower())
  except ValueError:
    return None


def apply_update(record: ClaimedRecord, update: ExtractedField, turn: int, crop_config: dict | None = None) -> bool:
  """Validate and apply one extracted field update to the record."""
  if update.field == 'grade' and crop_config is not None and 'grades' not in crop_config:
    logger.warning('Update rejected: grade not allowed for ungraded crop.')
    return False

  if update.field in ('quantity', 'price'):
    value = _validate_measure(update.value, update.field)
  elif update.field == 'crop_state':
    value = _validate_crop_state(update.value)
  else:
    value = _validate_text(update.value)

  if value is None:
    logger.warning(f'Update rejected: {update.field} -> {update.value} invalid.')
    return False

  field: Reading = getattr(record, update.field)
  field.update(value, _CONFIDENCE[update.confidence], turn)
  return True


def apply_updates(record: ClaimedRecord, updates: list[ExtractedField], turn: int, crop_config: dict | None = None) -> int:
  """Apply a batch of updates, return how many were actually applied"""
  return sum(apply_update(record, update, turn, crop_config) for update in updates)
