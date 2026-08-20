import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipecat.services.openai.realtime.llm import OpenAIRealtimeLLMService

from src import config, store
from src.event_tap import EventRecorder
from src.realtime_llm import SingleOwnerRealtimeLLMService

CALL_ID = "commentary-filter-test"
SOURCE_CALL = "call-10"

passed_through = {"audio": 0, "transcript": 0}


async def count_audio(self, evt):
    passed_through["audio"] += 1


async def count_transcript(self, evt):
    passed_through["transcript"] += 1


async def noop_response_done(self, evt):
    pass


class Evt:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def build_service():
    OpenAIRealtimeLLMService._handle_evt_audio_delta = count_audio
    OpenAIRealtimeLLMService._handle_evt_audio_transcript_delta = count_transcript
    OpenAIRealtimeLLMService._handle_evt_response_done = noop_response_done
    return SingleOwnerRealtimeLLMService(recorder=EventRecorder(CALL_ID), api_key="replay")


async def main():
    events = [json.loads(line) for line in
              open(os.path.join(store.resolve_call_dir(SOURCE_CALL), "events.jsonl")) if line.strip()]
    service = build_service()

    commentary_audio = commentary_transcript = 0
    for record in events:
        if record["source"] != "server":
            continue
        payload = record["event"]
        service._note_server_event(payload)
        item_id = payload.get("item_id")
        if payload.get("type") == "response.output_audio.delta":
            commentary_audio += item_id in service._commentary_item_ids
            await service._handle_evt_audio_delta(Evt(item_id=item_id))
        elif payload.get("type") == "response.output_audio_transcript.delta":
            commentary_transcript += item_id in service._commentary_item_ids
            await service._handle_evt_audio_transcript_delta(Evt(item_id=item_id, delta=payload.get("delta")))

    print(f"=== replaying {SOURCE_CALL} through the commentary filter ===")
    print(f"  commentary items detected: {len(service._commentary_item_ids)}")
    assert service._commentary_item_ids, "no commentary item found in the source call"

    suppressed = [json.loads(line)["event"] for line in
                  open(os.path.join(config.CALLS_DIR, CALL_ID, "events.jsonl"))
                  if '"suppressed.commentary"' in line]
    for entry in suppressed:
        print(f"  suppressed: {entry['transcript']!r}")
    assert suppressed, "filter fired but nothing was logged as suppressed.commentary"
    print(f"  audio deltas belonging to commentary: {commentary_audio} (all blocked)")
    print(f"  transcript deltas belonging to commentary: {commentary_transcript} (all blocked)")
    print(f"  deltas passed through to the transport: {passed_through}")

    assert len(suppressed) == len(service._commentary_item_ids), (suppressed, service._commentary_item_ids)
    assert commentary_transcript > 0, "no commentary transcript deltas were seen at all"
    print("  PASS commentary never reaches the transport and is logged instead")

    spoke = any(
        item["type"] == "message" and item["id"] not in service._commentary_item_ids
        for record in events if record["event"].get("type") == "response.done"
        and abs(record["t"] - 14.31) < 0.5
        for item in record["event"]["response"]["output"]
    )
    assert not spoke, "commentary-only response would still count as a spoken turn"
    print("  PASS a commentary-only response no longer counts as speech, so the bot still replies")


asyncio.run(main())
