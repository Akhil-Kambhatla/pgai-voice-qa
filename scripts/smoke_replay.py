import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import config
from src.realtime_llm import SingleOwnerRealtimeLLMService

FIXTURES = ("roleplay/call-11", "campaign/call-01")


class CollectingRecorder:
    def __init__(self):
        self.suppressed = []

    def record(self, source, payload):
        if payload.get("type") == "suppressed.commentary":
            self.suppressed.append(payload["item_id"])


def events_for(qualified_id):
    tree, _, call_id = qualified_id.partition("/")
    path = os.path.join(config.CALL_TREES[tree][0], call_id, "events.jsonl")
    with open(path) as handle:
        return [json.loads(line) for line in handle if line.strip()]


def tagged_commentary_ids(events):
    found = set()
    for record in events:
        item = (record.get("event") or {}).get("item")
        if isinstance(item, dict) and item.get("phase") == "commentary" and item.get("id"):
            found.add(item["id"])
    return found


def replay(qualified_id):
    events = events_for(qualified_id)
    expected = tagged_commentary_ids(events)

    service = SingleOwnerRealtimeLLMService.__new__(SingleOwnerRealtimeLLMService)
    recorder = CollectingRecorder()
    service._recorder = recorder
    service._commentary_item_ids = set()
    for record in events:
        if record.get("source") == "server":
            service._note_server_event(record.get("event") or {})

    caught = service._commentary_item_ids
    transcripts = [
        record["event"]
        for record in events
        if record.get("type") == "response.output_audio_transcript.done"
    ]
    spoken = [event["item_id"] for event in transcripts if event.get("item_id") not in expected]
    wrongly_suppressed = [item_id for item_id in recorder.suppressed if item_id not in expected]

    assert caught == expected, f"{qualified_id}: caught {caught}, tagged {expected}"
    assert not wrongly_suppressed, f"{qualified_id}: suppressed untagged items {wrongly_suppressed}"
    return len(expected), len(spoken)


def commentary_filter():
    for qualified_id in FIXTURES:
        caught, spoken = replay(qualified_id)
        assert caught or spoken, f"{qualified_id}: fixture has no transcripts at all"


def main():
    for qualified_id in FIXTURES:
        caught, spoken = replay(qualified_id)
        print(f"  {qualified_id:22} commentary suppressed: {caught}   speech passed through: {spoken}")
    print("  PASS the phase filter catches exactly the tagged items and nothing else")


if __name__ == "__main__":
    main()
