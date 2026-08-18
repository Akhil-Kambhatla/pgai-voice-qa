from loguru import logger
from pipecat.services.openai.realtime.llm import OpenAIRealtimeLLMService

from src.event_tap import EventRecorder, TappedWebsocket


class SingleOwnerRealtimeLLMService(OpenAIRealtimeLLMService):
    def __init__(self, *, recorder: EventRecorder, **kwargs):
        super().__init__(**kwargs)
        self._recorder = recorder
        self._last_response_spoke = True
        self._response_permitted = False
        self._commentary_item_ids = set()

    async def _receive_task_handler(self):
        if self._websocket is not None and not isinstance(self._websocket, TappedWebsocket):
            self._websocket = TappedWebsocket(self._websocket, self._recorder, self._note_server_event)
        await super()._receive_task_handler()

    def _note_server_event(self, payload):
        if not isinstance(payload, dict):
            return
        item = payload.get("item")
        if isinstance(item, dict) and item.get("phase") == "commentary" and item.get("id"):
            self._commentary_item_ids.add(item["id"])
        elif (
            payload.get("type") == "response.output_audio_transcript.done"
            and payload.get("item_id") in self._commentary_item_ids
        ):
            transcript = payload.get("transcript", "")
            self._recorder.record(
                "filter",
                {
                    "type": "suppressed.commentary",
                    "item_id": payload["item_id"],
                    "transcript": transcript,
                },
            )
            logger.info(f"suppressed reasoning commentary: {transcript!r}")

    async def _handle_evt_audio_delta(self, evt):
        if evt.item_id in self._commentary_item_ids:
            return
        await super()._handle_evt_audio_delta(evt)

    async def _handle_evt_audio_transcript_delta(self, evt):
        if evt.item_id in self._commentary_item_ids:
            return
        await super()._handle_evt_audio_transcript_delta(evt)

    async def _handle_evt_response_done(self, evt):
        self._last_response_spoke = any(
            item.type == "message" and item.id not in self._commentary_item_ids
            for item in (evt.response.output or [])
        )
        await super()._handle_evt_response_done(evt)

    async def _create_response(self):
        if self._response_permitted:
            await super()._create_response()
            return
        logger.debug(f"{self} suppressed client-side response.create; server turn detection owns turns")
        self._llm_needs_conversation_setup = False
        self._run_llm_when_api_session_ready = False

    async def _process_completed_function_calls(self, send_new_results: bool):
        self._response_permitted = send_new_results and not self._last_response_spoke
        try:
            await super()._process_completed_function_calls(send_new_results)
        finally:
            self._response_permitted = False
