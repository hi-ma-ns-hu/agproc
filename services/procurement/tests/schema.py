import pytest

from ..schema import Confidence, Measure, Qualification, Reading, Verdict

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
  q.decide(Verdict.PROCURE, 'clean lot at reference price')
  assert q.is_decided() is True
  assert q.verdict is Verdict.PROCURE
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
  q.decide(Verdict.PROCURE, 'asking above reference', price=band)
  assert q.price is band
