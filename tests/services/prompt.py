from services import CLOSING_INSTRUCTION, ConversationState, Measure, Verdict, _render_refdata, _render_verdict, build_system_prompt

EMPTY_REFDATA: dict = {}


def test_voice_channel_context_included():
  prompt = build_system_prompt('voice', refdata=EMPTY_REFDATA, state=ConversationState())
  assert 'phone call' in prompt


def test_messaging_channel_context_included():
  prompt = build_system_prompt('messaging', refdata=EMPTY_REFDATA, state=ConversationState())
  assert 'messaging' in prompt.lower()


def test_refdata_context_is_embedded():
  refdata = {'crops': {'wheat': {'price': 2450, 'price_unit': '₹/qtl'}}}
  prompt = build_system_prompt('voice', refdata=refdata, state=ConversationState())
  assert 'wheat: ₹/qtl 2450' in prompt


def test_empty_verdict_context_shows_placeholder():
  prompt = build_system_prompt('voice', refdata=EMPTY_REFDATA, state=ConversationState())
  assert 'no decision yet' in prompt.lower()


def test_verdict_context_is_embedded_when_present():
  state = ConversationState()
  state.qualification.decide(Verdict.NEGOTIATE, 'in band')
  prompt = build_system_prompt('voice', refdata=EMPTY_REFDATA, state=state)
  assert 'VERDICT: negotiate' in prompt


def test_json_braces_in_output_format_survive_formatting():
  prompt = build_system_prompt('voice', refdata=EMPTY_REFDATA, state=ConversationState())
  assert '"updates"' in prompt
  assert '{{' not in prompt


def test_prompt_instructs_grade_is_crop_conditional():
  prompt = build_system_prompt('voice', refdata=EMPTY_REFDATA, state=ConversationState())
  assert 'ONLY ASK ABOUT THIS IF THE CROP IS GRADED' in prompt


def test_prompt_instructs_confidence_reflects_how_it_was_said():
  prompt = build_system_prompt('voice', refdata=EMPTY_REFDATA, state=ConversationState())
  assert 'not how sure you FEEL' in prompt


def test_closing_instruction_forbids_new_questions():
  assert 'Do NOT ask any new questions' in CLOSING_INSTRUCTION


def test_prompt_forbids_volunteering_reference_price():
  prompt = build_system_prompt('voice', refdata=EMPTY_REFDATA, state=ConversationState())
  assert 'do NOT immediately reveal our reference price' in prompt


def test_prompt_has_measure_format_example():
  prompt = build_system_prompt('voice', refdata=EMPTY_REFDATA, state=ConversationState())
  assert '"value": 2400' in prompt


def test_prompt_specifies_exact_crop_state_values():
  prompt = build_system_prompt('voice', refdata=EMPTY_REFDATA, state=ConversationState())
  assert '"harvested", "harvesting", "standing"' in prompt


def test_prompt_forbids_crop_state_paraphrase():
  prompt = build_system_prompt('voice', refdata=EMPTY_REFDATA, state=ConversationState())
  assert 'in storage' in prompt


def test_prompt_forbids_negotiate_pushdown_language():
  prompt = build_system_prompt('voice', refdata=EMPTY_REFDATA, state=ConversationState())
  assert 'do NOT say "we will negotiate"' in prompt


def test_prompt_has_price_measure_example():
  prompt = build_system_prompt('voice', refdata=EMPTY_REFDATA, state=ConversationState())
  assert '"value": 2400' in prompt


def test_render_refdata_graded_crop():
  refdata = {'crops': {'onion': {'grades': {'mota': 2000}}}}
  text = _render_refdata(refdata)
  assert 'onion' in text and 'mota' in text and '2000' in text


def test_render_refdata_ungraded_crop():
  refdata = {'crops': {'wheat': {'price': 2450}}}
  text = _render_refdata(refdata)
  assert 'wheat' in text and '2450' in text and 'ungraded' in text


def test_render_verdict_includes_target_price():
  state = ConversationState()
  state.qualification.decide(Verdict.NEGOTIATE, 'in band', price=Measure(2450, '₹/quintal'))
  text = _render_verdict(state)
  assert 'negotiate' in text.lower()
  assert '2450' in text


def test_render_refdata_uses_default_price_unit():
  refdata = {
    'defaults': {'price_unit': '₹/quintal'},
    'crops': {'wheat': {'price': 2450}},
  }
  text = _render_refdata(refdata)
  assert '₹/quintal' in text


def test_render_refdata_uses_crop_specific_price_unit_override():
  refdata = {
    'defaults': {'price_unit': '₹/quintal'},
    'crops': {'onion': {'grades': {'mota': 2000}, 'price_unit': '₹/kg'}},
  }
  text = _render_refdata(refdata)
  assert '₹/kg' in text
  assert '₹/quintal' not in text


def test_render_refdata_graded_crop_shows_per_grade_prices_with_unit():
  refdata = {
    'defaults': {'price_unit': '₹/quintal'},
    'crops': {'onion': {'grades': {'super': 2200, 'mota': 2000}}},
  }
  text = _render_refdata(refdata)
  assert 'super' in text and '2200' in text
  assert 'mota' in text and '2000' in text
  assert '₹/quintal' in text
