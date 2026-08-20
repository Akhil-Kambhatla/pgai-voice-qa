import asyncio
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx
from openai import APIConnectionError

from src import goal_judge

TURNS = [
    {"speaker": "bot", "text": "Can I be seen this week?", "elapsed_seconds": 4.0},
    {"speaker": "agent", "text": "We can book you Thursday at two.", "elapsed_seconds": 9.0},
]


class RecordingTracker:
    def __init__(self):
        self.round_trips = []

    def judge_round_trip(self, elapsed, outcome, source):
        self.round_trips.append((round(elapsed, 1), outcome, source))


def client_returning(content):
    class Completions:
        async def create(self, **kwargs):
            message = type("Message", (), {"content": content})
            choice = type("Choice", (), {"message": message})
            return type("Response", (), {"choices": [choice]})

    return type("Client", (), {"chat": type("Chat", (), {"completions": Completions()})})


def client_sleeping(seconds):
    class Completions:
        async def create(self, **kwargs):
            await asyncio.sleep(seconds)
            raise AssertionError("the timeout should have cancelled this request")

    return type("Client", (), {"chat": type("Chat", (), {"completions": Completions()})})


def client_failing():
    class Completions:
        async def create(self, **kwargs):
            raise APIConnectionError(request=httpx.Request("POST", "https://api.openai.com/v1"))

    return type("Client", (), {"chat": type("Chat", (), {"completions": Completions()})})


async def main():
    assert goal_judge.JUDGE_TIMEOUT_SECONDS == 2, goal_judge.JUDGE_TIMEOUT_SECONDS

    goal_judge._client = client_returning(json.dumps({"outcome": "goal_met", "why": "booked"}))
    tracker = RecordingTracker()
    outcome, why = await goal_judge.call_outcome("book something", TURNS, tracker)
    assert outcome == "goal_met", (outcome, why)
    assert tracker.round_trips[0][2] == "model", tracker.round_trips
    print(f"  valid verdict          -> {outcome!r} from {tracker.round_trips[0][2]}")

    goal_judge._client = client_sleeping(5)
    tracker = RecordingTracker()
    started = time.monotonic()
    outcome, why = await goal_judge.call_outcome("book something", TURNS, tracker)
    elapsed = time.monotonic() - started
    assert outcome not in goal_judge.GRANTING_OUTCOMES, outcome
    assert 1.5 <= elapsed <= 3.0, elapsed
    assert tracker.round_trips[0][2] == "exception", tracker.round_trips
    print(f"  slow judge             -> {outcome!r} after {elapsed:.2f}s, fails closed")

    goal_judge._client = client_failing()
    tracker = RecordingTracker()
    outcome, why = await goal_judge.call_outcome("book something", TURNS, tracker)
    assert outcome not in goal_judge.GRANTING_OUTCOMES, outcome
    assert tracker.round_trips[0][2] == "exception", tracker.round_trips
    print(f"  connection error       -> {outcome!r}, fails closed")

    print("  PASS judge fails closed on timeout and transport error, and records every round trip")


asyncio.run(main())
