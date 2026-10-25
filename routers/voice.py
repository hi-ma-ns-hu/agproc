from fastapi import APIRouter, WebSocket
from fastapi.responses import Response
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.serializers.twilio import TwilioFrameSerializer
from pipecat.transports.websocket.fastapi import FastAPIWebsocketParams, FastAPIWebsocketTransport

from config import settings
from services import build_conversation_state, conversation, run_conversation_pipeline
from utils import bind_context, clear_context, get_logger, get_tracer

router = APIRouter()
logger = get_logger(__name__)
tracer = get_tracer(__name__)


@router.post('/voice/incoming')
async def incoming_call():
  twiml = """<?xml version="1.0" encoding="UTF-8"?>
    <Response>
      <Connect>
        <Stream url="wss://8563-2401-4900-1cd7-2305-32b-edce-bfe7-25c0.ngrok-free.app/api/voice/stream"/>
      </Connect>
    </Response>"""
  return Response(content=twiml, media_type='application/xml')


@router.post('/voice/outgoing')
async def outgoing_call():
  twiml = """<?xml version="1.0" encoding="UTF-8"?>
    <Response>
      <Connect>
        <Stream url="wss://8563-2401-4900-1cd7-2305-32b-edce-bfe7-25c0.ngrok-free.app/api/voice/stream">
          <Parameter name="direction" value="outbound"/>
        </Stream>
      </Connect>
    </Response>"""
  return Response(content=twiml, media_type='application/xml')


@router.websocket('/voice/stream')
async def voice_stream(websocket: WebSocket):
  await websocket.accept()
  await websocket.receive_json()
  start_data = await websocket.receive_json()
  start_data = start_data['start']
  call_sid = start_data['callSid']
  direction = start_data.get('customParameters', {}).get('direction', 'inbound')
  
  transport = FastAPIWebsocketTransport(websocket, params=FastAPIWebsocketParams(audio_in_enabled=True, audio_out_enabled=True, vad_analyzer=SileroVADAnalyzer(), serializer=TwilioFrameSerializer(stream_sid=start_data['streamSid'], call_sid=call_sid, account_sid=start_data['accountSid'], auth_token=settings.TWILIO_AUTH_TOKEN)))

  bind_context(conversation_id=call_sid, channel='voice', direction=direction)
  logger.info('call.start', conversation_id=call_sid, direction=direction)

  try:
    with tracer.start_as_current_span('call', attributes={'conversation_id': call_sid, 'direction': direction}):
      await run_conversation_pipeline(transport, conversation, build_conversation_state, call_sid, direction)
  finally:
    logger.info('call.end', conversation_id=call_sid)
    clear_context()
