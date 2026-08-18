import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipecat.frames.frames import CancelFrame, EndFrame
from pipecat.serializers.telnyx import TelnyxFrameSerializer

from src import config
from src.call_exit import RecordedTelnyxSerializer
from src.event_tap import EventRecorder

CALL_ID = "exit-path-test"


async def test_serializer_terminates_on_end_and_cancel():
    hangup_calls = []

    async def stub(self):
        hangup_calls.append(self._call_control_id)

    TelnyxFrameSerializer._hang_up_call = stub
    recorder = EventRecorder(CALL_ID)
    for frame in (EndFrame(), CancelFrame()):
        serializer = RecordedTelnyxSerializer(
            recorder=recorder,
            stream_id="stream-1",
            call_control_id="cc-1",
            outbound_encoding="PCMU",
            inbound_encoding="PCMU",
            api_key="key",
        )
        await serializer.serialize(frame)
    assert hangup_calls == ["cc-1", "cc-1"], hangup_calls
    print(f"  telnyx hangup issued for: {hangup_calls}")

    path = os.path.join(config.CALLS_DIR, CALL_ID, "events.jsonl")
    types = [json.loads(line)["event"]["type"] for line in open(path)]
    for expected in ("exit.frame_reached_serializer", "exit.telnyx_hangup_requested",
                     "exit.telnyx_hangup_returned"):
        assert expected in types, (expected, types)
    print(f"  lifecycle recorded: {sorted(set(types))}")
    print("  PASS EndFrame and CancelFrame each terminate the Telnyx call")


class FakeLogger:
    def __init__(self, elapsed, stalled=False, turns=()):
        self.elapsed = elapsed
        self._stalled = stalled
        self.turns = list(turns)
        self.calls = []

    def elapsed_seconds(self):
        return self.elapsed

    def stalled(self):
        return self._stalled

    def log_tool_call(self, name, arguments, result):
        self.calls.append((name, result))


class FakeTracker:
    def __init__(self):
        self.decisions = []

    def hangup_decision(self, granted, reason, missing, elapsed, condition):
        self.decisions.append((granted, condition))

    def nudged(self, still_want, count):
        pass


class FakeRetry:
    def __init__(self, exhausted=False):
        self.exhausted = exhausted
        self.denials = []

    def note_attempt(self):
        pass

    def note_denial(self, still_want):
        self.denials.append(still_want)


class FakeParams:
    def __init__(self):
        self.arguments = {"reason": "done"}
        self.results = []
        self.llm = self

    async def result_callback(self, result):
        self.results.append(result)

    async def push_frame(self, frame, direction):
        self.results.append(type(frame).__name__)


async def run_hangup(scenario, turn_logger, retry, judge_verdict=(False, "not done")):
    from src import goal_judge
    from src.bot_tools import build_tools

    async def stub(goal, turns):
        return judge_verdict

    goal_judge.goal_achieved = stub
    tracker, params = FakeTracker(), FakeParams()
    tools = build_tools(CALL_ID, turn_logger, scenario, tracker, retry)
    await next(t for t in tools if t.name == "hang_up").handler(params)
    return params, tracker, retry


async def test_grant_conditions():
    from src.bot_tools import HANGUP_OVERRIDE_SECONDS

    scenario = {
        "facts_to_elicit": ["hours", "closed_days"],
        "claims_to_verify": [],
        "goal": "You either have an appointment booked, or you know when to call back.",
    }
    booked = [{"speaker": "agent", "text": "Booked for August 25th at 4pm", "elapsed_seconds": 100}]
    cases = [
        ("facts missing, goal not met", FakeLogger(10.0), FakeRetry(), (False, "no"), False, ""),
        ("goal achieved early", FakeLogger(125.7, turns=booked), FakeRetry(), (True, "appointment booked"), True, "goal_achieved"),
        ("conversation stalled", FakeLogger(90.0, stalled=True), FakeRetry(), (False, "no"), True, "stalled"),
        ("nudged twice", FakeLogger(90.0), FakeRetry(exhausted=True), (False, "no"), True, "nudged_twice"),
        ("past time override", FakeLogger(config.MAX_CALL_SECONDS - HANGUP_OVERRIDE_SECONDS + 1), FakeRetry(), (False, "no"), True, "time_override"),
    ]
    for label, logger_, retry, verdict, expect_granted, expect_condition in cases:
        params, tracker, retry = await run_hangup(scenario, logger_, retry, verdict)
        granted = params.results[0] == {"hangup": "ok"}
        assert granted is expect_granted, (label, params.results)
        condition = tracker.decisions[0][1]
        assert expect_condition in condition, (label, condition)
        if granted:
            assert "EndWorkerFrame" in params.results, (label, params.results)
        else:
            assert params.results[0]["still_want"] == [
                "what time they open and close", "which days they are closed"
            ], params.results
            assert retry.denials, "denial did not schedule a retry nudge"
        print(f"  {label:28s} -> granted={granted} condition={condition!r}")
    print("  PASS grant fires on goal, stall, nudges, or time; denial schedules a retry")


async def test_facts_complete_skips_the_judge():
    scenario = {"facts_to_elicit": [], "claims_to_verify": [], "goal": "irrelevant"}
    params, tracker, _ = await run_hangup(scenario, FakeLogger(10.0), FakeRetry(), (False, "no"))
    assert params.results[0] == {"hangup": "ok"}, params.results
    assert tracker.decisions[0][1] == "facts_complete", tracker.decisions
    print("  PASS all facts collected still grants without consulting the judge")


async def test_stall_detection():
    from src.turn_log import TurnLogger

    def logger_with(agent_lines):
        turn_logger = TurnLogger(CALL_ID)
        for line in agent_lines:
            turn_logger._write("agent", line)
        return turn_logger

    progressing = logger_with([
        "We open at nine in the morning",
        "Doctor Kutty has Tuesday afternoon free",
        "That slot is four fifteen exactly",
    ])
    assert not progressing.stalled(), progressing.turns
    repeating = logger_with([
        "We open at nine in the morning",
        "Like I said we open at nine",
        "Nine in the morning, yes",
    ])
    assert repeating.stalled(), repeating.turns
    print("  PASS stall fires only when the last two agent turns add nothing new")


async def main():
    print("=== exit path ===")
    await test_serializer_terminates_on_end_and_cancel()
    await test_grant_conditions()
    await test_facts_complete_skips_the_judge()
    await test_stall_detection()


asyncio.run(main())
