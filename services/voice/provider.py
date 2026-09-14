from config import settings


def get_stt_service():
  from pipecat.services.sarvam.stt import SarvamSTTService

  return SarvamSTTService(api_key=settings.SARVAM_API_KEY, model=settings.STT_MODEL, language=settings.VOICE_LANGUAGE, mode='transcribe')


def get_tts_service():
  from pipecat.services.sarvam.tts import SarvamTTSService

  return SarvamTTSService(
    api_key=settings.SARVAM_API_KEY,
    settings=SarvamTTSService.Settings(model=settings.TTS_MODEL, language=settings.VOICE_LANGUAGE),
  )
