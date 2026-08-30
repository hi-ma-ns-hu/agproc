from ..pricing import crop_price
from ..schema import Measure

REFDATA = {
  'defaults': {'price_unit': '₹/quintal'},
  'crops': {
    'wheat': {'price': 2450},
    'onion': {'grades': {'super': 2200, 'mota': 2000, 'medium': 1800, 'golta': 1600}},
  },
}


def test_unlisted_crop_returns_none():
  assert crop_price('dragonfruit', REFDATA) is None


def test_ungraded_crop_returns_single_price():
  result = crop_price('wheat', REFDATA)
  assert isinstance(result, Measure)
  assert result.value == 2450


def test_graded_crop_with_grade_returns_single_price():
  result = crop_price('onion', REFDATA, grade='mota')
  assert isinstance(result, Measure)
  assert result.value == 2000


def test_graded_crop_without_grade_returns_all_grades():
  result = crop_price('onion', REFDATA)
  assert isinstance(result, dict)
  assert set(result.keys()) == {'super', 'mota', 'medium', 'golta'}
  assert result['super'].value == 2200


def test_graded_crop_unknown_grade_returns_all_grades():
  # farmer named a grade we don't recognize -> treat like no grade given
  result = crop_price('onion', REFDATA, grade='not_a_real_grade')
  assert isinstance(result, dict)


def test_price_unit_is_applied():
  result = crop_price('wheat', REFDATA)
  assert result.unit == '₹/quintal'


def test_crop_specific_price_unit_overrides_default():
  refdata = {
    'defaults': {'price_unit': '₹/quintal'},
    'crops': {'onion': {'price': 2000, 'price_unit': '₹/kg'}},
  }
  result = crop_price('onion', refdata)
  assert result.unit == '₹/kg'
