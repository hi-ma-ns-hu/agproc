from .schema import ClaimedRecord, ConversationState

BASE_REQUIRED = ('crop', 'quantity', 'crop_state', 'location', 'price')


def required_fields(config: dict) -> tuple[str, ...]:
  """Resolves which fields are required for a given crop."""
  fields = BASE_REQUIRED
  if 'grades' in config:
    fields += ('grade',)
  return fields


def missing(record: ClaimedRecord, config: dict) -> list[str]:
  """
  Required fields not yet known - tells the agent what's still open to ask each.
  """
  return [name for name in required_fields(config) if not getattr(record, name).is_known()]


def unconfirmed(record: ClaimedRecord, config: dict) -> list[str]:
  """
  Known-but-low-confidence required fields - should be checked back before the agent relies on them to qualify.
  """
  return [name for name in required_fields(config) if getattr(record, name).needs_confirmation()]


def is_completed(record: ClaimedRecord, config: dict) -> bool:
  """
  The gate: True when every required field is known, otherwise False.
  """
  return not missing(record, config)


def is_done(state: ConversationState, config: dict) -> bool:
  """
  Whether the record is complete, a real verdict has been reached, and nothing required is in a low-confidence state. On voice, the channel may then end the call; other channels decide their own action.
  """
  return is_completed(state.claimed, config) and state.qualification.is_decided() and not unconfirmed(state.claimed, config)
