import asyncio

from fastapi import WebSocket
from loguru import logger
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair
from pipecat.runner.utils import parse_telephony_websocket
from pipecat.serializers.telnyx import TelnyxFrameSerializer
from pipecat.services.openai.realtime import events as realtime_events
from pipecat.transports.websocket.fastapi import (
    FastAPIWebsocketParams,
    FastAPIWebsocketTransport,
)
from pipecat.workers.runner import WorkerRunner

from src import config, persona, store
from src.bot_tools import build_tools
from src.event_tap import EventRecorder, TappedRealtimeLLMService
from src.turn_log import GoodbyeWatcher, TurnLogger

MAX_HISTORY_ITEMS = 40


async def run_bot(websocket: WebSocket):
    body = persona.decode_body(websocket)
    transport_type, call_data = await parse_telephony_websocket(websocket)
    logger.info(f"Telephony handshake: type={transport_type} body={body}")

    call_id = body.get("call_id", "live")
    scenario = store.load_scenario(body["scenario_id"])

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

    turn_logger = TurnLogger(call_id)
    tools = build_tools(call_id, turn_logger, scenario)

    llm = TappedRealtimeLLMService(
        recorder=EventRecorder(call_id),
        api_key=config.OPENAI_API_KEY,
        settings=TappedRealtimeLLMService.Settings(
            model=config.REALTIME_MODEL,
            system_instruction=persona.build_instructions(scenario),
            session_properties=realtime_events.SessionProperties(
                audio=realtime_events.AudioConfiguration(
                    input=realtime_events.AudioInput(
                        transcription=realtime_events.InputAudioTranscription(),
                        turn_detection=realtime_events.SemanticTurnDetection(eagerness="low"),
                    )
                )
            ),
        ),
    )

    history_item_ids = []

    @llm.event_handler("on_conversation_item_created")
    async def on_item_created(service, item_id, item):
        history_item_ids.append(item_id)
        while len(history_item_ids) > MAX_HISTORY_ITEMS:
            oldest = history_item_ids.pop(0)
            await service.send_client_event(
                realtime_events.ConversationItemDeleteEvent(item_id=oldest)
            )

    goodbye_watcher = GoodbyeWatcher()
    context = LLMContext(tools=tools)
    user_aggregator, assistant_aggregator = LLMContextAggregatorPair(context)

    pipeline = Pipeline(
        [
            transport.input(),
            user_aggregator,
            llm,
            turn_logger,
            goodbye_watcher,
            transport.output(),
            assistant_aggregator,
        ]
    )

    worker = PipelineWorker(
        pipeline,
        params=PipelineParams(
            audio_in_sample_rate=24000,
            audio_out_sample_rate=24000,
        ),
    )

    async def enforce_max_duration():
        await asyncio.sleep(config.MAX_CALL_SECONDS)
        logger.warning(f"MAX_CALL_SECONDS ({config.MAX_CALL_SECONDS}) reached; ending call")
        await worker.cancel()

    watchdog = asyncio.create_task(enforce_max_duration())

    async def end_call_backstop():
        await worker.stop_when_done()

    goodbye_watcher.on_goodbye = end_call_backstop

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
