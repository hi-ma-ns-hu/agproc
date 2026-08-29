import pytest

from ..qualification import qualify
from ..schema import ClaimedRecord, Confidence, CropState, Measure, Verdict

REFDATA = {
  'defaults': {
    'quantity_unit': 'quintal',
    'price_unit': '₹/quintal',
    'min_quantity': 10,
    'negotiate_margin_pct': 2,
  },
  'crops': {
    'wheat': {'price': 2450, 'min_quantity': 20},
    'onion': {
      'grades': {'super': 2200, 'mota': 2000, 'medium': 1800, 'golta': 1600},
      'negotiate_margin_pct': 5,
    },
  },
}


def create_record(crop='wheat', quantity=40, quantity_unit='quintal', grade=None, crop_state=CropState.HARVESTED, price=2450, price_unit='₹/quintal'):
  """'
  Build a complete ClaimedRecord for a given scenario.
  """
  rec = ClaimedRecord()
  rec.crop.update(crop, Confidence.HIGH, 1)
  rec.quantity.update(Measure(quantity, quantity_unit), Confidence.HIGH, 1)
  rec.crop_state.update(crop_state, Confidence.HIGH, 1)
  rec.location.update('farm gate', Confidence.HIGH, 1)
  rec.price.update(Measure(price, price_unit), Confidence.HIGH, 1)
  if grade is not None:
    rec.grade.update(grade, Confidence.HIGH, 1)
  return rec


# ---------- facts: crop not bought ----------
def test_unlisted_crop_declines():
  rec = create_record(crop='dragonfruit', price=1)
  q = qualify(rec, REFDATA)
  assert q.verdict is Verdict.DECLINE
  assert 'dragonfruit' in q.reason


# ---------- facts: quantity below minimum ----------
def test_quantity_below_crop_minimum_declines():
  rec = create_record(crop='wheat', quantity=15)
  q = qualify(rec, REFDATA)
  assert q.verdict is Verdict.DECLINE
  assert 'minimum' in q.reason


def test_quantity_below_default_minimum_declines():
  rec = create_record(crop='onion', quantity=5, grade='mota', price=2000)
  q = qualify(rec, REFDATA)
  assert q.verdict is Verdict.DECLINE


def test_quantity_at_minimum_does_not_decline_on_quantity():
  rec = create_record(crop='wheat', quantity=20, price=2450)
  q = qualify(rec, REFDATA)
  assert q.verdict != Verdict.DECLINE or 'minimum' not in (q.reason or '')


# ---------- facts: not yet available ----------


def test_standing_crop_is_forward():
  rec = create_record(crop='wheat', crop_state=CropState.STANDING)
  q = qualify(rec, REFDATA)
  assert q.verdict is Verdict.FORWARD
  assert 'standing' in q.reason


def test_harvesting_crop_is_forward():
  rec = create_record(crop='wheat', crop_state=CropState.HARVESTING)
  q = qualify(rec, REFDATA)
  assert q.verdict is Verdict.FORWARD


# ---------- price band: ungraded crop ----------
def test_ungraded_crop_ask_at_reference_negotiates():
  rec = create_record(crop='wheat', price=2450)
  q = qualify(rec, REFDATA)
  assert q.verdict is Verdict.NEGOTIATE
  assert q.price.value == 2450


def test_ungraded_crop_ask_within_margin_negotiates():
  rec = create_record(crop='wheat', price=2490)
  q = qualify(rec, REFDATA)
  assert q.verdict is Verdict.NEGOTIATE


def test_ungraded_crop_ask_beyond_margin_declines():
  rec = create_record(crop='wheat', price=2600)
  q = qualify(rec, REFDATA)
  assert q.verdict is Verdict.DECLINE
  assert 'market band' in q.reason


# ---------- price band: graded crop ----------
def test_graded_crop_ask_at_grade_reference_negotiates():
  rec = create_record(crop='onion', grade='mota', price=2000)
  q = qualify(rec, REFDATA)
  assert q.verdict is Verdict.NEGOTIATE
  assert q.price.value == 2000


def test_graded_crop_ask_beyond_grade_margin_declines():
  rec = create_record(crop='onion', grade='mota', price=2200)
  q = qualify(rec, REFDATA)
  assert q.verdict is Verdict.DECLINE


def test_graded_crop_different_grades_use_different_reference_prices():
  rec_super = create_record(crop='onion', grade='super', price=2200)
  rec_golta = create_record(crop='onion', grade='golta', price=2200)  # too high for golta
  assert qualify(rec_super, REFDATA).verdict is Verdict.NEGOTIATE
  assert qualify(rec_golta, REFDATA).verdict is Verdict.DECLINE


# ---------- defensive fallbacks ----------
def test_unrecognized_grade_is_incomplete_not_declined():
  rec = create_record(crop='onion', grade='not_a_real_grade', price=2000)
  q = qualify(rec, REFDATA)
  assert q.verdict is Verdict.INCOMPLETE


def test_missing_price_is_incomplete():
  rec = create_record(crop='wheat')
  rec.price.value = None
  q = qualify(rec, REFDATA)
  assert q.verdict is Verdict.INCOMPLETE


# ---------- always has a reason ----------


@pytest.mark.parametrize(
  'rec',
  [
    create_record(crop='dragonfruit'),
    create_record(crop='wheat', quantity=1),
    create_record(crop='wheat', crop_state=CropState.STANDING),
    create_record(crop='wheat', price=2450),
    create_record(crop='wheat', price=9999),
  ],
)
def test_every_verdict_has_a_reason(rec):
  q = qualify(rec, REFDATA)
  assert q.reason and q.reason.strip()
