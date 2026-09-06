from services import to_quintal_price, to_quintal_weight


def test_kg_converts_to_quintal():
  amount, unit = to_quintal_weight(100, 'kg')
  assert amount == 1.0
  assert unit == 'quintal'


def test_quintal_stays_quintal():
  amount, unit = to_quintal_weight(50, 'quintal')
  assert amount == 50.0
  assert unit == 'quintal'


def test_tonne_converts_to_quintal():
  amount, unit = to_quintal_weight(2, 'tonne')
  assert amount == 20.0  # 2 tonnes = 20 quintals


def test_price_per_kg_converts_to_price_per_quintal():
  amount, unit = to_quintal_price(25, 'kg')
  assert amount == 2500.0
  assert unit == '₹/quintal'


def test_price_per_tonne_converts_to_price_per_quintal():
  amount, unit = to_quintal_price(24500, 'tonne')
  assert amount == 2450.0  # ₹24500/tonne = ₹2450/quintal
  assert unit == '₹/quintal'


def test_unrecognized_weight_unit_returns_none():
  assert to_quintal_weight(40, 'bags') is None


def test_unrecognized_price_unit_returns_none():
  assert to_quintal_price(25, 'bags') is None
