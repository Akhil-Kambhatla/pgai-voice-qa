import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipecat.frames.frames import InterruptionWorkerFrame, TranscriptionFrame
from pipecat.processors.frame_processor import FrameDirection

from src import store
from src.turn_log import FarEndFarewellWatcher

LEAKING = ("campaign/call-08", "campaign/call-11")
CONTINUED = "campaign/call-07"

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


def stored(call_id, name):
    path = os.path.join(store.resolve_call_dir(call_id), name)
    with open(path) as handle:
        return [json.loads(line) for line in handle if line.strip()]


def heard_and_leak(call_id):
    events = stored(call_id, "events.jsonl")
    heard = [(e["t"], e["event"].get("transcript") or "") for e in events
             if e.get("type") == "conversation.item.input_audio_transcription.completed"]
    first_audio = [e["t"] for e in events if e.get("type") == "response.output_audio_transcript.delta"]
    farewell = next((t for t, text in heard if "test line" in text.lower()), None)
    leak_audio = next((t for t in sorted(first_audio) if t > farewell), None)
    return heard, farewell, leak_audio


async def replay(transcripts, recorder):
    watcher = FarEndFarewellWatcher(recorder)
    pushed = []

    async def capture(frame, direction=FrameDirection.DOWNSTREAM):
        pushed.append((type(frame).__name__, direction))

    watcher.push_frame = capture
    for text in transcripts:
        await watcher.process_frame(
            TranscriptionFrame(text=text, user_id="agent", timestamp=""), FrameDirection.DOWNSTREAM
        )
    return pushed


def test_fires_inside_the_window():
    print("--- the two calls that leaked")
    for call_id in LEAKING:
        heard, farewell, leak_audio = heard_and_leak(call_id)
        recorder = CollectingRecorder()
        pushed = asyncio.run(replay([text for _, text in heard], recorder))
        interruptions = [d for name, d in pushed if name == "InterruptionWorkerFrame"]
        check(len(interruptions) == 1,
              f"{call_id}: one interruption pushed across {len(heard)} inbound turns",
              f"{call_id}: pushed {interruptions}")
        check(interruptions and interruptions[0] == FrameDirection.UPSTREAM,
              f"{call_id}: pushed upstream, which is the path the worker rebroadcasts",
              f"{call_id}: wrong direction {interruptions}")
        lifecycle = [p for s, p in recorder.records if s == "lifecycle"]
        check(len(lifecycle) == 1 and lifecycle[0]["type"] == "exit.far_end_farewell_truncated",
              f"{call_id}: logged {lifecycle[0]['type']} on {lifecycle[0]['heard'][-28:]!r}",
              f"{call_id}: lifecycle recorded {lifecycle}")
        check(farewell < leak_audio,
              f"{call_id}: farewell transcript t={farewell:.2f} precedes the leaked audio "
              f"t={leak_audio:.2f}, a {1000 * (leak_audio - farewell):.0f}ms window",
              f"{call_id}: no window: farewell {farewell} audio {leak_audio}")


def test_quiet_on_a_call_that_continued():
    print("\n--- a call where the agent said something closing-adjacent and carried on")
    turns = stored(CONTINUED, "turns.jsonl")
    agent_turns = [t for t in turns if t["speaker"] == "agent"]
    closing_adjacent = [t for t in agent_turns
                        if any(k in t["text"].lower()
                               for k in ("anything else", "have a great day", "thanks for calling"))]
    mid_call = [t for t in closing_adjacent if t["elapsed_seconds"] < 160]
    check(mid_call, f"fixture has {len(mid_call)} closing-adjacent mid-call turn(s)",
          "no closing-adjacent mid-call turn to test against")
    for turn in mid_call:
        after = [t for t in turns if t["elapsed_seconds"] > turn["elapsed_seconds"]]
        recorder = CollectingRecorder()
        pushed = asyncio.run(replay([turn["text"]], recorder))
        check(not [n for n, _ in pushed if n == "InterruptionWorkerFrame"] and not recorder.records,
              f"quiet on {turn['text'][:52]!r} which had {len(after)} turns after it",
              f"fired on a mid-call turn: {turn['text']!r}")

    recorder = CollectingRecorder()
    pushed = asyncio.run(replay([t["text"] for t in agent_turns if t["elapsed_seconds"] < 160], recorder))
    check(not recorder.records,
          f"quiet across all {len([t for t in agent_turns if t['elapsed_seconds'] < 160])} "
          f"mid-call agent turns of {CONTINUED}",
          f"fired mid-call: {recorder.records}")


def test_fires_once_only():
    print("\n--- it truncates once")
    recorder = CollectingRecorder()
    pushed = asyncio.run(replay(["Goodbye", "Goodbye", "Goodbye"], recorder))
    check(len([n for n, _ in pushed if n == "InterruptionWorkerFrame"]) == 1,
          "a repeated farewell truncates only once", f"pushed {pushed}")


def main():
    test_fires_inside_the_window()
    test_quiet_on_a_call_that_continued()
    test_fires_once_only()
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
