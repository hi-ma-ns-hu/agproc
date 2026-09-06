from config import settings

_TO_QUINTAL = {
  'kg': 0.01,
  'kgs': 0.01,
  'quintal': 1,
  'quintals': 1,
  'qtl': 1,
  'qtls': 1,
  'ton': 10,
  'tonne': 10,
  'tonnes': 10,
  'mt': 10,
}


def to_quintal_weight(amount: float, unit: str) -> tuple[float, str] | None:
  """
  Convert a stated weight to the canonical unit.

  Returns (converted_amount, canonical_unit) or None if the unit isn't
  recognized — callers should treat None as a rejected/unrecognized value,
  never guess.
  """
  factor = _TO_QUINTAL.get(unit.strip().lower())
  if factor is None:
    return None
  return amount * factor, settings.WEIGHT


def to_quintal_price(amount: float, per_unit: str) -> tuple[float, str] | None:
  """
  Convert a stated price-per-unit to price-per-canonical-unit.

  E.g. ₹25/kg with canonical=quintal -> ₹2500/quintal (more rupees per
  LARGER unit, so we divide by the same factor that converts the unit
  itself).
  """
  factor = _TO_QUINTAL.get(per_unit.strip().lower())
  if factor is None:
    return None
  return amount / factor, f'{settings.CURRENCY}/{settings.WEIGHT}'
