import pytest

from services import ClaimedRecord, Confidence, Measure, Qualification, Reading, Verdict

# Reading: Provenance


def test_fresh_reading_is_unknown():
  r = Reading()
  assert r.is_known() is False
  assert r.needs_confirmation() is False


def test_high_confidence_is_known_and_needs_no_confirmation():
  r = Reading()
  r.update('wheat', Confidence.HIGH, turn=1)
  assert r.is_known() is True
  assert r.needs_confirmation() is False


def test_low_confidence_is_known_but_needs_confirmation():
  r = Reading()
  r.update('wheat', Confidence.LOW, turn=1)
  assert r.is_known() is True
  assert r.needs_confirmation() is True


# Reading: update + provenance


def test_update_sets_value_confidence_and_turn():
  r = Reading()
  r.update('wheat', Confidence.HIGH, turn=3)
  assert r.value == 'wheat'
  assert r.confidence is Confidence.HIGH
  assert r.turn == 3


def test_update_revises_previous_value():
  r = Reading()
  r.update(Measure(30, 'quintal'), Confidence.HIGH, turn=1)
  r.update(Measure(40, 'quintal'), Confidence.HIGH, turn=4)
  assert r.value.value == 40
  assert r.turn == 4


# Qualification: decide guard
def test_decide_sets_verdict_and_reason():
  q = Qualification()
  q.decide(Verdict.NEGOTIATE, 'clean lot at reference price')
  assert q.is_decided() is True
  assert q.verdict is Verdict.NEGOTIATE
  assert q.reason == 'clean lot at reference price'


def test_fresh_qualification_is_not_decided():
  assert Qualification().is_decided() is False


def test_decide_rejects_empty_reason():
  q = Qualification()
  with pytest.raises(ValueError):
    q.decide(Verdict.DECLINE, '')


def test_decide_rejects_whitespace_only_reason():
  q = Qualification()
  with pytest.raises(ValueError):
    q.decide(Verdict.DECLINE, '     ')


def test_decide_carries_optional_price():
  q = Qualification()
  band = Measure(2200, '₹/quintal')
  q.decide(Verdict.NEGOTIATE, 'asking above reference', price=band)
  assert q.price is band

def test_reset_wipes_stale_fields_from_the_old_crop():
  record = ClaimedRecord()
  record.quantity.update(Measure(30, 'quintal'), Confidence.HIGH, turn=2)
  record.grade.update('A', Confidence.HIGH, turn=2)
  record.crop_state.update('harvested', Confidence.HIGH, turn=2)
  record.price.update(Measure(2000, '₹/quintal'), Confidence.HIGH, turn=2)

  record.reset_crop_dependent_fields(keep_turn=5)

  assert record.quantity.is_known() is False
  assert record.grade.is_known() is False
  assert record.crop_state.is_known() is False
  assert record.price.is_known() is False


def test_reset_keeps_fields_stated_in_the_same_turn_as_the_crop_change():
  # farmer says "actually it's wheat, 50 quintals, harvested" all in one turn -
  # the new crop and its facts are set together and must survive the reset.
  record = ClaimedRecord()
  record.quantity.update(Measure(50, 'quintal'), Confidence.HIGH, turn=5)
  record.crop_state.update('harvested', Confidence.HIGH, turn=5)

  record.reset_crop_dependent_fields(keep_turn=5)

  assert record.quantity.value.value == 50
  assert record.crop_state.value == 'harvested'


def test_reset_wipes_old_fields_but_keeps_only_the_ones_from_this_turn():
  # a mix: price carried over from the old crop (stale), quantity just restated
  # this turn alongside the new crop - only the stale one should be cleared.
  record = ClaimedRecord()
  record.price.update(Measure(2000, '₹/quintal'), Confidence.HIGH, turn=2)
  record.quantity.update(Measure(50, 'quintal'), Confidence.HIGH, turn=5)

  record.reset_crop_dependent_fields(keep_turn=5)

  assert record.price.is_known() is False
  assert record.quantity.value.value == 50
