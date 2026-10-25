from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import EndFrame, LLMFullResponseEndFrame, LLMFullResponseStartFrame, TextFrame, TranscriptionFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from utils import get_logger, get_tracer

from .provider import get_stt_service, get_tts_service

logger = get_logger(__name__)
tracer = get_tracer(__name__)


class ConversationBridge(FrameProcessor):
  """Bridges pipecat frames to a domain's conversation turn function, so this same voice pipeline can be reused across domains."""

  def __init__(self, conversation, build_state, conversation_id: str, direction: str = 'inbound'):
    super().__init__()
    self.conversation = conversation
    self.state = build_state(conversation_id, direction)
    self.direction = direction

  async def speak_outbound_opening(self):
    """Called explicitly once, from on_client_connected, for outbound calls."""
    with tracer.start_as_current_span('voice.turn', attributes={'opening': True}):
      response = await self.conversation('', self.state, channel='voice', is_opening_turn=True)

    self.state = response['state']
    await self.push_frame(LLMFullResponseStartFrame(), FrameDirection.DOWNSTREAM)
    await self.push_frame(TextFrame(response['reply']), FrameDirection.DOWNSTREAM)
    await self.push_frame(LLMFullResponseEndFrame(), FrameDirection.DOWNSTREAM)

  async def process_frame(self, frame, direction: FrameDirection):
    await super().process_frame(frame, direction)

    if isinstance(frame, TranscriptionFrame):
      with tracer.start_as_current_span('voice.turn', attributes={'opening': False}):
        response = await self.conversation(frame.text, self.state, channel='voice')

      self.state = response['state']
      await self.push_frame(LLMFullResponseStartFrame(), direction)
      await self.push_frame(TextFrame(response['reply']), direction)
      await self.push_frame(LLMFullResponseEndFrame(), direction)

      if response['done']:
        await self.push_frame(EndFrame(), direction)
    else:
      await self.push_frame(frame, direction)


async def run_conversation_pipeline(transport, conversation, build_state, conversation_id: str, direction: str = 'inbound'):
  stt = get_stt_service()
  tts = get_tts_service()
  bridge = ConversationBridge(conversation, build_state, conversation_id, direction)

  pipeline = Pipeline([transport.input(), stt, bridge, tts, transport.output()])

  task = PipelineTask(pipeline, params=PipelineParams(vad_analyzer=SileroVADAnalyzer()))

  @transport.event_handler('on_client_connected')
  async def on_client_connected(transport, client):
    if direction == 'outbound':
      await bridge.speak_outbound_opening()

  @transport.event_handler('on_client_disconnected')
  async def on_client_disconnected(transport, client):
    logger.info('call.disconnected')
    await task.cancel()

  runner = PipelineRunner()
  await runner.run(task)
