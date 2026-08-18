from loguru import logger
from pipecat.services.openai.realtime.llm import OpenAIRealtimeLLMService

from src.event_tap import EventRecorder, TappedWebsocket


class SingleOwnerRealtimeLLMService(OpenAIRealtimeLLMService):
    def __init__(self, *, recorder: EventRecorder, **kwargs):
        super().__init__(**kwargs)
        self._recorder = recorder
        self._last_response_spoke = True
        self._response_permitted = False

    async def _receive_task_handler(self):
        if self._websocket is not None and not isinstance(self._websocket, TappedWebsocket):
            self._websocket = TappedWebsocket(self._websocket, self._recorder)
        await super()._receive_task_handler()

    async def _handle_evt_response_done(self, evt):
        output_types = [item.type for item in (evt.response.output or [])]
        self._last_response_spoke = "message" in output_types
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
