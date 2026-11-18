from unittest.mock import patch

from services.agent import _clean_reply


def test_strips_malformed_trailing_json_tail():
  dirty = 'कोई बात नहीं, धन्यवाद!"}'
  assert _clean_reply(dirty) == 'कोई बात नहीं, धन्यवाद!'


def test_leaves_normal_devanagari_sentence_untouched():
  clean = 'ठीक है, 25 क्विंटल, सही है?'
  assert _clean_reply(clean) == clean


def test_leaves_normal_english_sentence_untouched():
  clean = 'Okay, thanks for confirming.'
  assert _clean_reply(clean) == clean


def test_strips_only_trailing_json_syntax_not_mid_sentence_punctuation():
  # a comma mid-sentence must survive untouched - only a trailing run of
  # pure JSON-syntax characters at the very end should be stripped
  dirty = 'सुपर, मोटा, मीडियम या गोल्टा?"}'
  assert _clean_reply(dirty) == 'सुपर, मोटा, मीडियम या गोल्टा?'


def test_interior_brace_is_flagged_not_stripped():
  # a brace surviving anywhere other than the trailing position is
  # unexpected (see the docstring) - log it for visibility, but don't
  # mutate text that might turn out to be legitimate.
  suspicious = 'कीमत {2400} रुपये है'
  with patch('services.agent.logger') as mock_logger:
    result = _clean_reply(suspicious)

  assert result == suspicious
  mock_logger.warning.assert_called_once_with('reply.suspicious_syntax', reply=suspicious)
