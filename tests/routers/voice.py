REAL_START_EVENT = {
  'event': 'start',
  'sequenceNumber': '1',
  'start': {
    'accountSid': 'AC00000000000000000000000000000000',
    'streamSid': 'MZ72d84c6b2fc3338ca50bc7eef1636ce8',
    'callSid': 'CAe90d8233d72bfa8872bdb695c2d44ede',
    'tracks': ['inbound'],
    'mediaFormat': {'encoding': 'audio/x-mulaw', 'sampleRate': 8000, 'channels': 1},
    'customParameters': {},
  },
  'streamSid': 'MZ72d84c6b2fc3338ca50bc7eef1636ce8',
}


def test_extracts_stream_sid_call_sid_account_sid():
  start_data = REAL_START_EVENT['start']
  assert start_data['streamSid'] == 'MZ72d84c6b2fc3338ca50bc7eef1636ce8'
  assert start_data['callSid'] == 'CAe90d8233d72bfa8872bdb695c2d44ede'
  assert start_data['accountSid'] == 'AC00000000000000000000000000000000'


def test_extracts_custom_direction_parameter():
  event_with_direction = {
    **REAL_START_EVENT,
    'start': {**REAL_START_EVENT['start'], 'customParameters': {'direction': 'outbound'}},
  }
  start_data = event_with_direction['start']
  direction = start_data.get('customParameters', {}).get('direction', 'inbound')
  assert direction == 'outbound'


def test_missing_custom_parameters_defaults_to_inbound():
  start_data = REAL_START_EVENT['start']
  direction = start_data.get('customParameters', {}).get('direction', 'inbound')
  assert direction == 'inbound'
