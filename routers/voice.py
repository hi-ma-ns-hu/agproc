from fastapi import APIRouter, WebSocket
from fastapi.responses import Response
from pipecat.transports.websocket.fastapi import FastAPIWebsocketParams, FastAPIWebsocketTransport
from pipecat.serializers.twilio import TwilioFrameSerializer
from pipecat.audio.vad.silero import SileroVADAnalyzer

from config import settings
from services import run_conversation_pipeline

router = APIRouter()


@router.post('/voice/incoming')
async def incoming_call():
  twiml = """<?xml version="1.0" encoding="UTF-8"?>
    <Response>
      <Connect>
        <Stream url="wss://2064-2401-4900-88eb-e2f6-e01f-4511-9504-f15d.ngrok-free.app/api/voice/stream"/>
      </Connect>
    </Response>"""
  return Response(content=twiml, media_type='application/xml')


@router.post('/voice/outgoing')
async def outgoing_call():
  twiml = """<?xml version="1.0" encoding="UTF-8"?>
    <Response>
      <Connect>
        <Stream url="wss://2064-2401-4900-88eb-e2f6-e01f-4511-9504-f15d.ngrok-free.app/api/voice/stream">
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
  start_data = start_data["start"]
  direction = start_data.get("customParameters", {}).get("direction", "inbound")
  transport = FastAPIWebsocketTransport(websocket, params=FastAPIWebsocketParams(audio_in_enabled=True, audio_out_enabled=True, vad_analyzer=SileroVADAnalyzer(),  serializer=TwilioFrameSerializer(stream_sid=start_data["streamSid"], call_sid=start_data['callSid'], account_sid=start_data['accountSid'], auth_token=settings.TWILIO_AUTH_TOKEN)))
  await run_conversation_pipeline(transport, direction)
