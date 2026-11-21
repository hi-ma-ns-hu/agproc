from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import EndFrame, LLMFullResponseEndFrame, LLMFullResponseStartFrame, TextFrame, TranscriptionFrame
from pipecat.observers.error_observer import ErrorObserver
from pipecat.observers.startup_timing_observer import StartupTimingObserver
from pipecat.observers.user_bot_latency_observer import UserBotLatencyObserver
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.workers.runner import WorkerRunner

from utils import get_logger, get_meter, get_tracer

from .provider import get_stt_service, get_tts_service

logger = get_logger(__name__)
tracer = get_tracer(__name__)
meter = get_meter(__name__)

_ttff_histogram = meter.create_histogram('voice.ttff', unit='ms', description='Farmer-stops-speaking to bot-starts-speaking latency (end-to-end TTFF)')
_service_ttfb_histogram = meter.create_histogram('voice.service_ttfb', unit='ms', description='Per-service time-to-first-byte within a user-to-bot cycle (STT/TTS latency)')
_turn_duration_histogram = meter.create_histogram('voice.turn_duration', unit='ms', description='Full conversational turn duration, user-stopped-speaking to bot-stopped-speaking')
_call_setup_histogram = meter.create_histogram('voice.call_setup', unit='ms', description='WebSocket connect to ClientConnectedFrame latency')
_first_bot_speech_histogram = meter.create_histogram('voice.first_bot_speech_latency', unit='ms', description='Client-connected to first bot speech latency')
_service_error_counter = meter.create_counter('voice.service_errors', description='Pipeline service errors - STT/TTS reconnect failures, transport/connectivity issues')


def _clean_processor_name(name: str) -> str:
  """Strip pipecat's '#<instance index>' suffix so the name is a bounded label, not one unique value per call."""
  return name.split('#', 1)[0]


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

  error_observer = ErrorObserver()
  startup_observer = StartupTimingObserver()
  latency_observer = UserBotLatencyObserver()

  task = PipelineWorker(
    pipeline,
    params=PipelineParams(vad_analyzer=SileroVADAnalyzer(), enable_metrics=True),
    conversation_id=conversation_id,
    enable_tracing=True,
    observers=[error_observer, startup_observer, latency_observer],
  )

  @error_observer.event_handler('on_error')
  async def on_error(observer, event):
    processor = _clean_processor_name(event.processor)
    log = logger.warning if event.processor_usable else logger.error
    log('voice.service_error', message=event.message, category=event.category.value, exception_type=event.exception_type, processor=event.processor, processor_usable=event.processor_usable)
    _service_error_counter.add(1, {'category': event.category.value, 'processor': processor, 'processor_usable': event.processor_usable, 'direction': direction})

  @startup_observer.event_handler('on_startup_timing_report')
  async def on_startup_timing_report(observer, report):
    logger.info('voice.startup_timing', total_ms=round(report.total_duration_secs * 1000), setup_ms=round(report.setup_phase_secs * 1000), start_ms=round(report.start_phase_secs * 1000), processors=[{'name': t.processor_name, 'duration_ms': round(t.duration_secs * 1000)} for t in report.processor_timings])

  @startup_observer.event_handler('on_transport_timing_report')
  async def on_transport_timing_report(observer, report):
    logger.info('voice.call_setup', client_connected_ms=round(report.client_connected_secs * 1000) if report.client_connected_secs is not None else None, bot_connected_ms=round(report.bot_connected_secs * 1000) if report.bot_connected_secs is not None else None)
    if report.client_connected_secs is not None:
      _call_setup_histogram.record(report.client_connected_secs * 1000, {'direction': direction})

  @latency_observer.event_handler('on_latency_measured')
  async def on_latency_measured(observer, latency_seconds):
    logger.info('voice.ttff', latency_ms=round(latency_seconds * 1000))
    _ttff_histogram.record(latency_seconds * 1000, {'direction': direction})

  @latency_observer.event_handler('on_latency_breakdown')
  async def on_latency_breakdown(observer, breakdown):
    # breakdown.ttfb is each service's own reported TTFB, independent of the derived
    # `contributions` timeline below - contributions relies on LLMTextFrame/FIRST_TEXT
    # markers this pipeline never emits (ConversationBridge calls conversation()
    # directly, bypassing pipecat's own LLMService frames), so STT/TTS stages can end
    # up folded into a generic "pipeline" bucket there. ttfb has no such dependency.
    logger.info('voice.turn_latency_breakdown', total_ms=round(breakdown.total_secs * 1000), measured_from=breakdown.measured_from.value if breakdown.measured_from else None, ttfb=[{'processor': t.processor, 'duration_ms': round(t.duration_secs * 1000)} for t in breakdown.ttfb], contributions=[{'key': c.key, 'owner': c.owner, 'duration_ms': round(c.duration_secs * 1000)} for c in breakdown.contributions])
    for t in breakdown.ttfb:
      _service_ttfb_histogram.record(t.duration_secs * 1000, {'service': _clean_processor_name(t.processor)})

  @latency_observer.event_handler('on_first_bot_speech_latency')
  async def on_first_bot_speech_latency(observer, latency_seconds):
    logger.info('voice.first_bot_speech_latency', latency_ms=round(latency_seconds * 1000))
    _first_bot_speech_histogram.record(latency_seconds * 1000, {'direction': direction})

  if task.turn_tracking_observer:
    @task.turn_tracking_observer.event_handler('on_turn_ended')
    async def on_turn_ended(observer, turn_number, duration_secs, was_interrupted):
      logger.info('voice.turn_ended', turn=turn_number, duration_ms=round(duration_secs * 1000), interrupted=was_interrupted)
      _turn_duration_histogram.record(duration_secs * 1000, {'interrupted': was_interrupted, 'direction': direction})

  @transport.event_handler('on_client_connected')
  async def on_client_connected(transport, client):
    if direction == 'outbound':
      await bridge.speak_outbound_opening()

  @transport.event_handler('on_client_disconnected')
  async def on_client_disconnected(transport, client):
    logger.info('call.disconnected')
    await task.cancel()

  runner = WorkerRunner()
  await runner.add_workers(task)
  await runner.run()
