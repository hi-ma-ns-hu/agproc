from enum import Enum

from pipecat.transcriptions.language import Language


class VoiceLanguage(Enum):
  """The languages this app supports, expressed as pipecat's own canonical Language values."""

  BENGALI = Language.BN_IN
  ENGLISH = Language.EN_IN
  GUJARATI = Language.GU_IN
  HINDI = Language.HI_IN
  KANNADA = Language.KN_IN
  MALAYALAM = Language.ML_IN
  MARATHI = Language.MR_IN
  ODIA = Language.OR_IN
  PUNJABI = Language.PA_IN
  TAMIL = Language.TA_IN
  TELUGU = Language.TE_IN


LANGUAGE_NAMES: dict[VoiceLanguage, str] = {
  VoiceLanguage.BENGALI: 'Bengali',
  VoiceLanguage.ENGLISH: 'English',
  VoiceLanguage.GUJARATI: 'Gujarati',
  VoiceLanguage.HINDI: 'Hindi',
  VoiceLanguage.KANNADA: 'Kannada',
  VoiceLanguage.MALAYALAM: 'Malayalam',
  VoiceLanguage.MARATHI: 'Marathi',
  VoiceLanguage.ODIA: 'Odia',
  VoiceLanguage.PUNJABI: 'Punjabi',
  VoiceLanguage.TAMIL: 'Tamil',
  VoiceLanguage.TELUGU: 'Telugu',
}
