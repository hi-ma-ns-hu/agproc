from services import ClaimedRecord, Confidence, CropState, ExtractedField, Measure, MeasureValue, apply_update, apply_updates, render_rejected


# ---------- apply_update: text fields (default validator) ----------
def test_apply_update_text_field_applies():
  rec = ClaimedRecord()
  ok, reason = apply_update(rec, ExtractedField(field='crop', value='wheat', confidence='high'), turn=1)
  assert ok is True
  assert reason is None
  assert rec.crop.value == 'wheat'
  assert rec.crop.confidence is Confidence.HIGH
  assert rec.crop.turn == 1


def test_apply_update_text_field_strips_whitespace():
  rec = ClaimedRecord()
  apply_update(rec, ExtractedField(field='location', value='  farm gate  ', confidence='high'), turn=1)
  assert rec.location.value == 'farm gate'


def test_apply_update_empty_text_rejected():
  rec = ClaimedRecord()
  ok, reason = apply_update(rec, ExtractedField(field='location', value='   ', confidence='high'), turn=1)
  assert ok is False
  assert reason == 'The value is empty or None.'
  assert rec.location.is_known() is False


def test_apply_update_low_confidence_maps_correctly():
  rec = ClaimedRecord()
  apply_update(rec, ExtractedField(field='grade', value='mota', confidence='low'), turn=2)
  assert rec.grade.confidence is Confidence.LOW
  assert rec.grade.needs_confirmation() is True


# ---------- apply_update: measure fields (quantity, price) ----------
def test_apply_update_measure_field_applies():
  rec = ClaimedRecord()
  ok, reason = apply_update(
    rec,
    ExtractedField(field='quantity', value=MeasureValue(value=40, unit='quintal'), confidence='high'),
    turn=1,
  )
  assert ok is True
  assert reason is None
  assert isinstance(rec.quantity.value, Measure)
  assert rec.quantity.value.value == 40
  assert rec.quantity.value.unit == 'quintal'


def test_apply_update_price_field_applies():
  rec = ClaimedRecord()
  ok, reason = apply_update(
    rec,
    ExtractedField(field='price', value=MeasureValue(value=2450, unit='₹/quintal'), confidence='high'),
    turn=1,
  )
  assert ok is True
  assert reason is None
  assert rec.price.value.value == 2450


def test_apply_update_measure_field_rejects_plain_string():
  rec = ClaimedRecord()
  ok, reason = apply_update(rec, ExtractedField(field='quantity', value='a lot', confidence='high'), turn=1)
  assert ok is False
  assert reason == 'The unit is not recognized or not supported.'
  assert rec.quantity.is_known() is False


# ---------- apply_update: crop_state (constrained vocabulary) ----------
def test_apply_update_valid_crop_state_applies():
  rec = ClaimedRecord()
  ok, reason = apply_update(rec, ExtractedField(field='crop_state', value='standing', confidence='high'), turn=1)
  assert ok is True
  assert reason is None
  assert rec.crop_state.value is CropState.STANDING


def test_apply_update_crop_state_normalizes_case_and_whitespace():
  rec = ClaimedRecord()
  apply_update(rec, ExtractedField(field='crop_state', value='  HARVESTED  ', confidence='high'), turn=1)
  assert rec.crop_state.value is CropState.HARVESTED


def test_apply_update_invalid_crop_state_rejected():
  rec = ClaimedRecord()
  ok, reason = apply_update(rec, ExtractedField(field='crop_state', value='somewhat ready', confidence='high'), turn=1)
  assert ok is False
  assert reason == 'The crop state is not recognized or not supported. Valid states are: Harvested, Harvesting, or Standing.'
  assert rec.crop_state.is_known() is False


# ---------- apply_update: revision (calling update twice) ----------
def test_apply_update_revises_existing_value():
  rec = ClaimedRecord()
  apply_update(rec, ExtractedField(field='quantity', value=MeasureValue(value=30, unit='quintal'), confidence='high'), turn=1)
  apply_update(rec, ExtractedField(field='quantity', value=MeasureValue(value=40, unit='quintal'), confidence='high'), turn=3)
  assert rec.quantity.value.value == 40
  assert rec.quantity.turn == 3


# ---------- apply_updates: batch behavior ----------
def test_apply_updates_returns_count_not_bool():
  rec = ClaimedRecord()
  updates = [
    ExtractedField(field='crop', value='onion', confidence='high'),
    ExtractedField(field='location', value='farm gate', confidence='high'),
  ]
  count, rejected = apply_updates(rec, updates, turn=1)
  assert count == 2
  assert type(count) is int
  assert rejected == []


def test_apply_updates_all_rejected_returns_zero():
  rec = ClaimedRecord()
  updates = [
    ExtractedField(field='quantity', value='a lot', confidence='high'),
    ExtractedField(field='crop_state', value='sort of ready', confidence='high'),
  ]
  count, rejected = apply_updates(rec, updates, turn=1)
  assert count == 0
  assert [field for field, _ in rejected] == ['quantity', 'crop_state']


def test_apply_updates_partial_success_counts_correctly():
  rec = ClaimedRecord()
  updates = [
    ExtractedField(field='crop', value='wheat', confidence='high'),
    ExtractedField(field='quantity', value='not numeric', confidence='high'),
    ExtractedField(field='location', value='farm gate', confidence='high'),
  ]
  count, rejected = apply_updates(rec, updates, turn=1)
  assert count == 2
  assert [field for field, _ in rejected] == ['quantity']


def test_grade_rejected_for_ungraded_crop():
  rec = ClaimedRecord()
  ungraded_cfg = {'price': 2450}
  ok, reason = apply_update(
    rec,
    ExtractedField(field='grade', value='decent quality', confidence='low'),
    turn=1,
    crop_config=ungraded_cfg,
  )
  assert ok is False
  assert reason == 'Grade not allowed for ungraded crop'
  assert rec.grade.is_known() is False


def test_grade_accepted_for_graded_crop():
  rec = ClaimedRecord()
  graded_cfg = {'grades': {'mota': 2000, 'golta': 1600}}
  ok, reason = apply_update(
    rec,
    ExtractedField(field='grade', value='mota', confidence='high'),
    turn=1,
    crop_config=graded_cfg,
  )
  assert ok is True
  assert reason is None
  assert rec.grade.value == 'mota'


def test_apply_updates_passes_crop_config_through_to_each_update():
  rec = ClaimedRecord()
  ungraded_cfg = {'price': 2450}
  updates = [
    ExtractedField(field='crop', value='wheat', confidence='high'),
    ExtractedField(field='grade', value='decent', confidence='low'),  # should be rejected
  ]
  count, rejected = apply_updates(rec, updates, turn=1, crop_config=ungraded_cfg)
  assert count == 1
  assert [field for field, _ in rejected] == ['grade']
  assert rec.crop.value == 'wheat'
  assert rec.grade.is_known() is False


def test_crop_state_accepts_exact_enum_word():
  rec = ClaimedRecord()
  ok, reason = apply_update(rec, ExtractedField(field='crop_state', value='harvested', confidence='high'), turn=1)
  assert ok is True
  assert reason is None
  assert rec.crop_state.value is CropState.HARVESTED


def test_crop_state_rejects_paraphrase():
  for bad_value in ['in storage', 'ready', 'stored', 'picked']:
    rec = ClaimedRecord()
    ok, reason = apply_update(rec, ExtractedField(field='crop_state', value=bad_value, confidence='high'), turn=1)
    assert ok is False
    assert 'Valid states are' in reason


def test_price_accepts_measure_value():
  rec = ClaimedRecord()
  ok, reason = apply_update(
    rec,
    ExtractedField(field='price', value=MeasureValue(value=2400, unit='quintal'), confidence='high'),
    turn=1,
  )
  assert ok is True
  assert reason is None
  assert rec.price.value.value == 2400


def test_price_rejects_plain_string():
  rec = ClaimedRecord()
  ok, reason = apply_update(rec, ExtractedField(field='price', value='2400 per quintal', confidence='high'), turn=1)
  assert ok is False
  assert reason == 'The unit is not recognized or not supported.'
  assert rec.price.is_known() is False


def test_price_unit_gets_currency_injected_when_quantity_unknown():
  rec = ClaimedRecord()
  ok, reason = apply_update(
    rec,
    ExtractedField(field='price', value=MeasureValue(value=2450, unit='quintal'), confidence='high'),
    turn=1,
  )
  assert ok is True
  assert reason is None
  assert rec.price.value.unit == '₹/quintal'


def test_price_unit_is_independent_of_quantity_unit():
  rec = ClaimedRecord()
  apply_update(rec, ExtractedField(field='quantity', value=MeasureValue(value=40, unit='kg'), confidence='high'), turn=1)
  ok, reason = apply_update(
    rec,
    ExtractedField(field='price', value=MeasureValue(value=50, unit='quintal'), confidence='high'),
    turn=2,
  )
  assert ok is True
  assert reason is None
  assert rec.price.value.unit == '₹/quintal'


def test_price_unit_strips_currency_prefix_if_model_included_one():
  rec = ClaimedRecord()
  ok, reason = apply_update(
    rec,
    ExtractedField(field='price', value=MeasureValue(value=2450, unit='rs/quintal'), confidence='high'),
    turn=1,
  )
  assert ok is True
  assert reason is None
  assert rec.price.value.unit == '₹/quintal'


def test_price_currency_is_always_settings_currency_regardless_of_model_output():
  rec = ClaimedRecord()
  apply_update(rec, ExtractedField(field='price', value=MeasureValue(value=2450, unit='usd/quintal'), confidence='high'), turn=1)
  assert rec.price.value.unit == '₹/quintal'


def test_price_rejected_when_no_unit_available_at_all():
  rec = ClaimedRecord()
  ok, reason = apply_update(rec, ExtractedField(field='price', value=MeasureValue(value=2450, unit=''), confidence='high'), turn=1)
  assert ok is False
  assert reason == 'The unit is not recognized or not supported.'


def test_apply_updates_returns_field_and_reason_for_rejections():
  rec = ClaimedRecord()
  updates = [
    ExtractedField(field='crop', value='wheat', confidence='high'),
    ExtractedField(field='quantity', value='not numeric', confidence='high'),
  ]
  count, rejected = apply_updates(rec, updates, turn=1)
  assert count == 1
  assert rejected == [('quantity', 'The unit is not recognized or not supported.')]


def test_render_rejected_includes_reason():
  text = render_rejected([('quantity', "the unit wasn't recognized")])
  assert 'quantity' in text
  assert "unit wasn't recognized" in text


def test_render_rejected_empty_shows_none():
  assert render_rejected([]) == '(none)'
