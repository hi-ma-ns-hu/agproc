from .refdata import crop_config as config
from .schema import ClaimedRecord, CropState, Measure, Qualification, Verdict


def _reference_price(record: ClaimedRecord, crop_config: dict) -> float | None:
  """
  Resolve the reference market price for this claimed crop lot.
  """
  if 'grades' in crop_config:
    grade = record.grade.value
    return crop_config['grades'].get(grade)
  return crop_config.get('price')


def qualify(record: ClaimedRecord, refdata: dict) -> Qualification:
  """
  Return a verdict for a complete claimed lot.
  """
  qualification = Qualification()
  crop = record.crop.value
  crop_config = config(crop, refdata)
  crop_defaults = refdata.get('defaults', {})

  # facts first: any of these disqualify
  # check for crop first
  if crop_config is None:
    qualification.decide(Verdict.DECLINE, f"We don't procure {crop!r}")
    return qualification

  # check for minimum quantity
  min_qty = crop_config.get('min_quantity', crop_defaults.get('min_quantity', 0))
  qty = record.quantity.value
  if qty is None or qty.value is None or qty.value < min_qty:
    qualification.decide(Verdict.DECLINE, f'Quantity below our minimum ({min_qty} {crop_defaults.get("quantity_unit", "")})')
    return qualification

  # crop state
  crop_state = record.crop_state.value
  if crop_state in (CropState.STANDING, CropState.HARVESTING):
    qualification.decide(Verdict.FORWARD, f'Crop not yet available ({crop_state.value}); worth pursuing once harvested')
    return qualification

  # price band
  reference_price = _reference_price(record, crop_config)
  if reference_price is None:
    qualification.decide(Verdict.INCOMPLETE, 'No reference market price available for the claimed grade.')
    return qualification

  negotiable_margin_pct = crop_config.get('negotiate_margin_pct', crop_defaults.get('negotiate_margin_pct', 0))
  ceiling = reference_price * (1 + negotiable_margin_pct / 100)

  ask_price = record.price.value
  target = Measure(reference_price, crop_defaults.get('price_unit'))

  if ask_price is None or ask_price.value is None:
    qualification.decide(Verdict.INCOMPLETE, 'No asking price stated.')
    return qualification

  if ask_price.value <= ceiling:
    qualification.decide(Verdict.NEGOTIATE, 'Within market band, worth pursuing, price finalized after looking and grading product', price=target)
  else:
    qualification.decide(Verdict.DECLINE, f'Asking price beyond market band (> {ceiling:.0f} {target.unit})')
  return qualification
