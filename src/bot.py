"""Minimal speech-to-speech bot for the scaffold: asks about office hours and hangs up."""

import asyncio

from fastapi import WebSocket
from loguru import logger
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair
from pipecat.runner.utils import parse_telephony_websocket
from pipecat.serializers.telnyx import TelnyxFrameSerializer
from pipecat.services.openai.realtime.llm import OpenAIRealtimeLLMService
from pipecat.transports.websocket.fastapi import (
    FastAPIWebsocketParams,
    FastAPIWebsocketTransport,
)
from pipecat.workers.runner import WorkerRunner

import re

from pipecat.frames.frames import Frame, TTSStoppedFrame, TTSTextFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from src import config

_GOODBYE_RE = re.compile(r"\b(good\s?-?\s?bye|bye+|bye\s?now)\b", re.IGNORECASE)


class GoodbyeWatcher(FrameProcessor):
    """Ends the call once the bot finishes a turn in which it said goodbye.

    Sits after the realtime LLM, accumulates the bot's spoken-transcript
    TTSTextFrames per turn; when the turn ends (TTSStoppedFrame) and the text
    matches a goodbye, invokes the callback (worker.stop_when_done -> EndFrame
    -> serializer auto-hangup).
    """

    def __init__(self):
        super().__init__()
        self._turn_text = ""
        self.on_goodbye = None

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, TTSTextFrame):
            self._turn_text += frame.text
        elif isinstance(frame, TTSStoppedFrame):
            if _GOODBYE_RE.search(self._turn_text) and self.on_goodbye:
                logger.info(f"Bot said goodbye ({self._turn_text!r}); ending call")
                await self.on_goodbye()
            self._turn_text = ""
        await self.push_frame(frame, direction)


INSTRUCTIONS = """You are a person calling a medical office. Say hello, ask what their office hours
are, thank them, and say goodbye. Keep it short. Speak naturally."""


async def run_bot(websocket: WebSocket):
    """Handle one Telnyx media-stream websocket: run the realtime agent until hangup."""
    transport_type, call_data = await parse_telephony_websocket(websocket)
    logger.info(f"Telephony handshake: type={transport_type} call_data={dict(call_data)}")

    serializer = TelnyxFrameSerializer(
        stream_id=call_data["stream_id"],
        call_control_id=call_data["call_id"],
        outbound_encoding=call_data["outbound_encoding"],
        inbound_encoding="PCMU",
        api_key=config.TELNYX_API_KEY,
    )

    transport = FastAPIWebsocketTransport(
        websocket=websocket,
        params=FastAPIWebsocketParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            add_wav_header=False,
            serializer=serializer,
        ),
    )

    llm = OpenAIRealtimeLLMService(
        api_key=config.OPENAI_API_KEY,
        settings=OpenAIRealtimeLLMService.Settings(
            model=config.REALTIME_MODEL,
            system_instruction=INSTRUCTIONS,
        ),
    )

    goodbye_watcher = GoodbyeWatcher()

    context = LLMContext()
    user_aggregator, assistant_aggregator = LLMContextAggregatorPair(context)

    pipeline = Pipeline(
        [
            transport.input(),
            user_aggregator,
            llm,
            goodbye_watcher,
            transport.output(),
            assistant_aggregator,
        ]
    )

    worker = PipelineWorker(
        pipeline,
        # The OpenAI realtime service sends/receives pipeline audio verbatim and the
        # API requires PCM16 @ 24kHz, so the pipeline runs at 24k. TelnyxFrameSerializer
        # resamples both directions between the 8kHz PCMU wire format and this rate.
        # (8k here == 3x-slowed audio at OpenAI: VAD never fires and the bot stays silent.)
        params=PipelineParams(
            audio_in_sample_rate=24000,
            audio_out_sample_rate=24000,
        ),
    )

    # Hard call-duration cap, enforced in code. Cancelling the worker pushes a
    # CancelFrame through the serializer, which auto-hangs-up the Telnyx call.
    async def enforce_max_duration():
        await asyncio.sleep(config.MAX_CALL_SECONDS)
        logger.warning(f"MAX_CALL_SECONDS ({config.MAX_CALL_SECONDS}) reached; ending call")
        await worker.cancel()

    watchdog = asyncio.create_task(enforce_max_duration())

    async def end_call_on_goodbye():
        await worker.stop_when_done()

    goodbye_watcher.on_goodbye = end_call_on_goodbye

    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client):
        logger.info("Telnyx media stream connected")

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        logger.info("Telnyx media stream disconnected")
        await worker.cancel()

    runner = WorkerRunner(handle_sigint=False)
    await runner.add_workers(worker)
    try:
        await runner.run()
    finally:
        watchdog.cancel()
