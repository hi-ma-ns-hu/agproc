from config import settings

from .language import VoiceLanguage


def _voice_language():
  from pipecat.transcriptions.language import Language

  return VoiceLanguage(Language(settings.VOICE_LANGUAGE)).value


def get_stt_service():
  from pipecat.services.sarvam.stt import SarvamSTTService

  return SarvamSTTService(api_key=settings.SARVAM_API_KEY, model=settings.STT_MODEL, language=_voice_language(), mode='transcribe')


def get_tts_service():
  from pipecat.services.sarvam.tts import SarvamTTSService

  return SarvamTTSService(
    api_key=settings.SARVAM_API_KEY,
    settings=SarvamTTSService.Settings(model=settings.TTS_MODEL, language=_voice_language()),
  )
