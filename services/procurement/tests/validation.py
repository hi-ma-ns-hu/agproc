import pytest

from ..schema import ClaimedRecord, Confidence, ConversationState, CropState, Measure, Verdict
from ..validation import is_completed, is_done, missing, required_fields, unconfirmed

WHEAT_CONFIG = {'price': 2450, 'min_quantity': 20}
ONION_CONFIG = {
  'grades': {'super': 2200, 'mota': 2000, 'medium': 1800, 'golta': 1600},
  'negotiate_margin_pct': 5,
}


@pytest.fixture
def record():
  """A record with every BASE required field filled at HIGH confidence (no grade)."""
  rec = ClaimedRecord()
  rec.crop.update('wheat', Confidence.HIGH, 1)
  rec.quantity.update(Measure(40, 'quintal'), Confidence.HIGH, 1)
  rec.crop_state.update(CropState.HARVESTED, Confidence.HIGH, 1)
  rec.location.update('farm gate', Confidence.HIGH, 1)
  rec.price.update(Measure(2450, '₹/quintal'), Confidence.HIGH, 1)
  return rec


# required fields


def test_ungraded_crop_excludes_grade():
  assert 'grade' not in required_fields(WHEAT_CONFIG)


def test_graded_crop_includes_grade():
  assert 'grade' in required_fields(ONION_CONFIG)


def test_base_fields_always_present():
  base = ('crop', 'quantity', 'crop_state', 'location', 'price')
  for config in (WHEAT_CONFIG, ONION_CONFIG):
    assert set(base).issubset(required_fields(config))


def test_required_fields_does_not_leak_grade_accross_calls():
  before = required_fields(WHEAT_CONFIG)
  required_fields(ONION_CONFIG)
  after = required_fields(WHEAT_CONFIG)
  assert before == after
  assert 'grade' not in after


# missing


def test_empty_record_missing_base_fields():
  miss = missing(ClaimedRecord(), WHEAT_CONFIG)
  assert 'crop' in miss and 'price' in miss


def test_filled_base_missing_nothing_when_ungraded(record):
  assert missing(record, WHEAT_CONFIG) == []


def test_filled_base_missing_grade_when_ungraded(record):
  assert missing(record, ONION_CONFIG) == ['grade']


# is_completed


def test_empty_not_completed():
  assert is_completed(ClaimedRecord(), WHEAT_CONFIG) is False


def test_ungraded_completed_without_grade(record):
  assert is_completed(record, WHEAT_CONFIG) is True


def test_graded_not_completed_without_grade(record):
  assert is_completed(record, ONION_CONFIG) is False


def test_graded_completed_with_grade(record):
  record.grade.update('mota', Confidence.HIGH, 2)
  assert is_completed(record, ONION_CONFIG) is True


# unconfirmed
def test_no_unconfirmed_when_all_high(record):
  assert unconfirmed(record, WHEAT_CONFIG) == []


def test_low_confidence_required_field_is_unconfirmed(record):
  record.price.update(Measure(2450, '₹/quintal'), Confidence.LOW, 3)
  assert 'price' in unconfirmed(record, WHEAT_CONFIG)


def test_unconfirmed_ignores_non_required_fields(record):
  record.variety.update('some variety', Confidence.LOW, 3)
  assert unconfirmed(record, WHEAT_CONFIG) == []


# is_done


def test_not_done_when_incomplete(record):
  # onion needs grade, which record doesn't have
  state = ConversationState()
  state.claimed = record
  state.qualification.decide(Verdict.NEGOTIATE, 'clean lot')
  assert is_done(state, ONION_CONFIG) is False


def test_not_done_when_no_verdict(record):
  # complete for wheat, but no verdict decided
  state = ConversationState()
  state.claimed = record
  assert is_done(state, WHEAT_CONFIG) is False


def test_not_done_when_required_field_unconfirmed(record):
  record.price.update(Measure(2450, '₹/quintal'), Confidence.LOW, 3)
  state = ConversationState()
  state.claimed = record
  state.qualification.decide(Verdict.NEGOTIATE, 'clean lot')
  assert is_done(state, WHEAT_CONFIG) is False


def test_done_when_complete_decided_and_confirmed(record):
  state = ConversationState()
  state.claimed = record
  state.qualification.decide(Verdict.NEGOTIATE, 'clean lot at reference')
  assert is_done(state, WHEAT_CONFIG) is True
