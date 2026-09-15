from unittest.mock import patch

from services import get_stt_service, get_tts_service


def test_stt_service_uses_configured_language():
  with patch('pipecat.services.sarvam.stt.SarvamSTTService') as mock_stt:
    with patch('services.voice.provider.settings') as mock_settings:
      mock_settings.VOICE_LANGUAGE = 'hi-IN'
      mock_settings.SARVAM_API_KEY = 'fake-key'
      mock_settings.STT_MODEL = 'saaras:v3'
      get_stt_service()

  _, kwargs = mock_stt.call_args
  assert kwargs['language'] == 'hi-IN'


def test_tts_service_configures_language_via_settings():
  with patch('pipecat.services.sarvam.tts.SarvamTTSService') as mock_tts:
    with patch('services.voice.provider.settings') as mock_settings:
      mock_settings.VOICE_LANGUAGE = 'hi-IN'
      mock_settings.SARVAM_API_KEY = 'fake-key'
      mock_settings.TTS_MODEL = 'bulbul:v3'
      get_tts_service()

  _, call_kwargs = mock_tts.call_args
  assert 'target_language_code' not in call_kwargs

  _, settings_kwargs = mock_tts.Settings.call_args
  assert settings_kwargs['language'] == 'hi-IN'


def test_stt_and_tts_use_same_configured_language():
  with patch('pipecat.services.sarvam.stt.SarvamSTTService') as mock_stt, patch('pipecat.services.sarvam.tts.SarvamTTSService') as mock_tts, patch('services.voice.provider.settings') as mock_settings:
    mock_settings.VOICE_LANGUAGE = 'hi-IN'
    mock_settings.SARVAM_API_KEY = 'fake-key'
    mock_settings.STT_MODEL = 'saaras:v3'
    mock_settings.TTS_MODEL = 'bulbul:v3'
    get_stt_service()
    get_tts_service()

  stt_lang = mock_stt.call_args.kwargs['language']
  tts_lang = mock_tts.Settings.call_args.kwargs['language']
  assert stt_lang == tts_lang == 'hi-IN'
