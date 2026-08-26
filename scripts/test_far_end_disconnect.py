import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import call_exit, store

FIXTURES = ("campaign/call-08", "campaign/call-11")
LEAK_MARKERS = ("part of the test", "routed somewhere else")

failures = []


def check(condition, passed, failed):
    if condition:
        print(f"  PASS {passed}")
    else:
        failures.append(failed)


class CollectingRecorder:
    def __init__(self):
        self.records = []

    def record(self, source, payload):
        self.records.append((source, payload))


def stored(call_id):
    path = os.path.join(store.resolve_call_dir(call_id), "events.jsonl")
    with open(path) as handle:
        return [json.loads(line) for line in handle if line.strip()]


def leak_and_disconnect(events):
    leak = next(
        (e["t"] for e in events
         if e.get("type") == "response.output_audio_transcript.done"
         and any(m in (e["event"].get("transcript") or "").lower() for m in LEAK_MARKERS)),
        None,
    )
    heard = next(
        (e["t"] for e in events
         if e.get("type") == "conversation.item.input_audio_transcription.completed"
         and "test line" in (e["event"].get("transcript") or "").lower()),
        None,
    )
    disconnect = next(
        (e["t"] for e in events
         if (e.get("event") or {}).get("type") in ("exit.stream_disconnected", "exit.far_end_disconnected")),
        None,
    )
    return heard, leak, disconnect


def test_recorded_timing():
    print("--- what the stored calls actually show")
    for call_id in FIXTURES:
        heard, leak, disconnect = leak_and_disconnect(stored(call_id))
        print(f"  {call_id}: far end said goodbye t={heard:.2f}, bot leaked t={leak:.2f}, "
              f"disconnect observed t={disconnect:.2f}")
        check(disconnect > leak,
              f"{call_id}: the disconnect arrives {disconnect - leak:.1f}s AFTER the leak",
              f"{call_id}: disconnect at {disconnect} did not follow the leak at {leak}")


def make_serializer(recorder, torn_down):
    async def on_stop():
        torn_down.append("telnyx_stop")

    return call_exit.RecordedTelnyxSerializer(
        recorder=recorder, on_far_end_stop=on_stop, stream_id="s", call_control_id="cc",
        outbound_encoding="PCMU", inbound_encoding="PCMU", api_key="key",
    )


async def feed(serializer, messages):
    for message in messages:
        await serializer.deserialize(message)


def test_stop_tears_down():
    print("\n--- a Telnyx stop event tears the call down")
    recorder, torn_down = CollectingRecorder(), []
    serializer = make_serializer(recorder, torn_down)
    asyncio.run(feed(serializer, [
        json.dumps({"event": "connected"}),
        json.dumps({"event": "start", "start": {}}),
        json.dumps({"event": "stop"}),
    ]))
    check(torn_down == ["telnyx_stop"], "stop triggers exactly one teardown",
          f"teardowns fired: {torn_down}")
    lifecycle = [p for s, p in recorder.records if s == "lifecycle"]
    check(any(p["type"] == "exit.far_end_stop" for p in lifecycle),
          "and records exit.far_end_stop distinctly", f"lifecycle recorded: {lifecycle}")
    observed = [p["type"] for s, p in recorder.records if s == "telnyx"]
    check("telnyx.connected" in observed and "telnyx.start" in observed,
          f"inbound Telnyx events are now recorded: {observed}",
          f"inbound events not captured: {observed}")

    recorder, torn_down = CollectingRecorder(), []
    serializer = make_serializer(recorder, torn_down)
    asyncio.run(feed(serializer, [json.dumps({"event": "stop"}), json.dumps({"event": "stop"})]))
    check(len(torn_down) == 1, "a repeated stop does not tear down twice",
          f"teardowns fired: {torn_down}")

    recorder, torn_down = CollectingRecorder(), []
    serializer = make_serializer(recorder, torn_down)
    asyncio.run(feed(serializer, [json.dumps({"event": "dtmf", "dtmf": {"digit": "1"}})]))
    media_event = call_exit._telnyx_event_name(json.dumps({"event": "media", "media": {}}))
    check(not torn_down and media_event == "media",
          "dtmf and media never tear down, so a slow turn is untouched",
          f"a non-stop event tore the call down: {torn_down} media_event={media_event}")
    check(call_exit._telnyx_event_name(b"\x00\x01") is None,
          "raw binary frames are ignored rather than crashing the parse",
          "binary frames were not handled")


def main():
    test_recorded_timing()
    test_stop_tears_down()
    print()
    if failures:
        print("FAILED")
        for failure in failures:
            print("  " + failure)
        return 1
    print("ALL VERIFICATIONS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
