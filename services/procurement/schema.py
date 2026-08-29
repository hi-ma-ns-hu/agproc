from dataclasses import dataclass, field
from enum import Enum
from typing import Any

# INFORMATION GATHERING


class Confidence(Enum):
  """
  How sure we are about a field value.
  States:
    UNKNOWN - not asked / not mentioned yet
    LOW - inferred, mumbled, unconfirmed, might need confirmation
    HIGH - stated clearly / confirmed
  """

  UNKNOWN = 'unknown'
  LOW = 'low'
  HIGH = 'high'


class CropState(Enum):
  """
  Whether the lot physically exists.
  States:
    HARVESTED - already harvested and available now.
    HARVESTING - harvest underway.
    STANDING - still in field, not yet harvested, available in future
  """

  HARVESTED = 'harvested'
  HARVESTING = 'harvesting'
  STANDING = 'standing'


@dataclass
class Reading:
  """
  One field of the record: value + confidence + provenance.
  This wrapper makes record revisable.
  """

  value: Any = None
  confidence: Confidence = Confidence.UNKNOWN
  turn: int | None = None

  def update(self, value: Any, confidence: Confidence, turn: int):
    """
    Helps to update / revise the existing values,
    'actually 40, not 30' three turns later just calls update() again.
    """
    self.value = value
    self.confidence = confidence
    self.turn = turn

  def is_known(self) -> bool:
    """
    Field either has confidence of HIGH/LOW, but is not UNKNOWN.
    """
    return self.confidence != Confidence.UNKNOWN

  def needs_confirmation(self) -> bool:
    """
    Field has LOW confidence and needs confirmation.
    """
    return self.confidence == Confidence.LOW


@dataclass
class Measure:
  """
  An amount paired with its unit - the two are meaningless apart.
  """

  value: float | None = None
  unit: str | None = None


@dataclass
class ClaimedRecord:
  """
  The crop as *claimed* by the farmer over initial conversation - not yet verified.
  """

  # Facts
  crop: Reading = field(default_factory=Reading)
  variety: Reading = field(default_factory=Reading)
  quantity: Reading = field(default_factory=lambda: Reading(value=Measure()))
  grade: Reading = field(default_factory=Reading)
  crop_state: Reading = field(default_factory=Reading)  # CropState
  location: Reading = field(default_factory=Reading)

  # TERMS (negotiable positions)
  price: Reading = field(default_factory=lambda: Reading(value=Measure()))
  payment_terms: Reading = field(default_factory=Reading)
  handover: Reading = field(default_factory=Reading)  # pickup / drop
  transport: Reading = field(default_factory=Reading)  # who bears it

  contact: Reading = field(default_factory=Reading)


# QUALIFICATION


class Verdict(Enum):
  """
  The outcome the agent reaches about a lot by the end of a call.
  States:
    NEGOTIATE - facts acceptable and asking price is within market band (reference + margin). Every qualified lot lands here — price is always provisional, fixed only after grading at intake. Compare record.price to target_price for how close the ask was.
    FORWARD - not yet available (standing/harvesting crop). Yes-but-revisit-at-harvest.
    DECLINE - a FACT disqualifies it (wrong crop, too small, unusable grade, uneconomic location). Firm no. Note: price never causes DECLINE — an over-ask is NEGOTIATE, not a no.
    INCOMPLETE - no decision could be reached (farmer evasive, call dropped, a required fact never obtained). Not a decision about the lot.
  """

  NEGOTIATE = 'negotiate'
  FORWARD = 'forward'
  DECLINE = 'decline'
  INCOMPLETE = 'incomplete'


@dataclass
class Qualification:
  """
  The decision what the agent concluded about the claimed lot.
  """

  verdict: Verdict = Verdict.INCOMPLETE
  reason: str | None = None
  price: Measure | None = None  # for NEGOTIATE / FORWARD

  def decide(self, verdict: Verdict, reason: str, price: Measure | None = None):
    """
    Record a verdict with its justification.
    """
    if not reason or not reason.strip():
      raise ValueError('A verdict must have a reason!')

    self.verdict = verdict
    self.reason = reason
    self.price = price

  def is_decided(self) -> bool:
    """
    Whether a real verdict has been reached. Anything except INCOMPLETE
    """
    return self.verdict != Verdict.INCOMPLETE


# CallState


class ConversationChannel(Enum):
  """Which medium the conversation is happening over"""

  VOICE = 'voice'


class ConversationInitiator(Enum):
  """Who initiated the conversation?"""

  US = 'us'
  THEM = 'them'


@dataclass
class ConversationMeta:
  """
  Channel agnostic conversation metadata
  """

  channel: ConversationChannel = ConversationChannel.VOICE
  initiated_by: ConversationInitiator = ConversationInitiator.US
  turn_count: int = 0


@dataclass
class CallMeta(ConversationMeta):
  """
  Call level metadata. Extends ConversationMeta
  """


@dataclass
class ConversationState:
  """
  The full state of one procurement conversation, carried turn to turn.
  """

  claimed: ClaimedRecord = field(default_factory=ClaimedRecord)
  qualification: Qualification = field(default_factory=Qualification)
  meta: ConversationMeta = field(default_factory=CallMeta)
