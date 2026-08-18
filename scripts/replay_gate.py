import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipecat.services.openai.realtime.llm import OpenAIRealtimeLLMService

from src import config
from src.event_tap import EventRecorder
from src.realtime_llm import SingleOwnerRealtimeLLMService

created = []


async def fake_create_response(self):
    created.append(True)


async def fake_process(self, send_new_results: bool):
    if send_new_results:
        await self._create_response()


class Evt:
    def __init__(self, output_types):
        self.response = type("R", (), {"output": [type("I", (), {"type": t})() for t in output_types]})()


async def fake_response_done(self, evt):
    pass


def build_service():
    OpenAIRealtimeLLMService._create_response = fake_create_response
    OpenAIRealtimeLLMService._process_completed_function_calls = fake_process
    OpenAIRealtimeLLMService._handle_evt_response_done = fake_response_done
    recorder = EventRecorder("replay-scratch")
    return SingleOwnerRealtimeLLMService(recorder=recorder, api_key="replay")


async def replay(call_id):
    import asyncio

    events = [json.loads(line) for line in open(os.path.join(config.CALLS_DIR, call_id, "events.jsonl"))]
    service = build_service()
    first_context_seen = False
    spoken_turns = 0
    log = []
    for e in events:
        if e["type"] == "response.done" and e["source"] == "server":
            output = [o.get("type") for o in (e["event"].get("response") or {}).get("output", [])]
            if "message" in output:
                spoken_turns += 1
            await service._handle_evt_response_done(Evt(output))
        elif e["source"] == "client" and e["type"] == "conversation.item.create":
            item = e["event"].get("item") or {}
            before = len(created)
            if item.get("type") == "function_call_output":
                await service._process_completed_function_calls(True)
                log.append((e["t"], "tool result", len(created) > before))
            elif not first_context_seen:
                first_context_seen = True
                await service._process_completed_function_calls(False)
                await service._create_response()
                log.append((e["t"], "first context", len(created) > before))
    return log, spoken_turns, len(created)


def main():
    import asyncio

    call_id = sys.argv[1]
    log, spoken_turns, total = asyncio.run(replay(call_id))
    print(f"=== replaying {call_id} through the new response gate ===")
    for t, kind, fired in log:
        print(f"  t={t:.2f} {kind:14s} -> client response.create: {fired}")
    print(f"client-side response.create under old code: {len(log)}")
    print(f"client-side response.create under new gate: {total}")
    print(f"spoken bot turns in the recording:          {spoken_turns}")


main()
