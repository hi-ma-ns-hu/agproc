from services.voice.language import LANGUAGE_NAMES, VoiceLanguage


def test_every_voice_language_has_a_display_name():
  # catches the real failure mode: adding a language to the enum without
  # adding its entry in LANGUAGE_NAMES, which would KeyError at prompt-build
  # time for just that one language, in production, mid-call.
  for language in VoiceLanguage:
    assert language in LANGUAGE_NAMES, f'{language} has no display name in LANGUAGE_NAMES'


def test_language_names_has_no_entries_for_unknown_languages():
  assert set(LANGUAGE_NAMES.keys()) == set(VoiceLanguage)


def test_display_names_are_distinct_non_empty_strings():
  names = list(LANGUAGE_NAMES.values())
  assert all(isinstance(name, str) and name.strip() for name in names)
  assert len(names) == len(set(names))
