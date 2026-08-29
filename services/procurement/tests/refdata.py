from ..refdata import clear_refdata, crop_config, load_refdata


def test_load_refdata_returns_dict():
  rd = load_refdata()
  assert isinstance(rd, dict)
  assert 'crops' in rd
  assert 'defaults' in rd


def test_known_graded_crop_returns_config_with_grades():
  rd = load_refdata()
  onion = crop_config('onion', rd)
  assert onion is not None
  assert 'grades' in onion


def test_known_ungraded_crop_has_price_not_grades():
  rd = load_refdata()
  wheat = crop_config('wheat', rd)
  assert wheat is not None
  assert 'price' in wheat
  assert 'grades' not in wheat


def test_unknown_crop_returns_none():
  rd = load_refdata()
  assert crop_config('dragonfruit', rd) is None


def test_cache_clear_forces_reload():
  rd1 = load_refdata()
  clear_refdata()
  rd2 = load_refdata()
  assert rd1 == rd2
