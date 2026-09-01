from ..prompt import build_system_prompt


def test_voice_channel_context_included():
  prompt = build_system_prompt('voice', refdata_context='', verdict_context='')
  assert 'phone call' in prompt


def test_messaging_channel_context_included():
  prompt = build_system_prompt('messaging', refdata_context='', verdict_context='')
  assert 'messaging' in prompt.lower()


def test_refdata_context_is_embedded():
  prompt = build_system_prompt('voice', refdata_context='- wheat: ₹2450/qtl', verdict_context='')
  assert 'wheat: ₹2450/qtl' in prompt


def test_empty_verdict_context_shows_placeholder():
  prompt = build_system_prompt('voice', refdata_context='', verdict_context='')
  assert 'no decision yet' in prompt.lower()


def test_verdict_context_is_embedded_when_present():
  prompt = build_system_prompt('voice', refdata_context='', verdict_context='VERDICT: negotiate')
  assert 'VERDICT: negotiate' in prompt


def test_json_braces_in_output_format_survive_formatting():
  # regression guard: the {{ }} escaping in the template must render as { }
  prompt = build_system_prompt('voice', refdata_context='', verdict_context='')
  assert '"updates"' in prompt
  assert '{{' not in prompt  # should have been un-escaped by .format()
