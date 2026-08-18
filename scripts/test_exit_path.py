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


async def test_hangup_is_granted_past_the_time_override():
    from src.bot_tools import HANGUP_OVERRIDE_SECONDS, build_tools

    class FakeLogger:
        def __init__(self, elapsed):
            self.elapsed = elapsed
            self.calls = []

        def elapsed_seconds(self):
            return self.elapsed

        def log_tool_call(self, name, arguments, result):
            self.calls.append((name, result))

    class FakeTracker:
        def __init__(self):
            self.decisions = []

        def hangup_decision(self, granted, reason, missing, elapsed, forced):
            self.decisions.append((granted, forced))

    class FakeParams:
        def __init__(self):
            self.arguments = {"reason": "done"}
            self.results = []
            self.llm = self

        async def result_callback(self, result):
            self.results.append(result)

        async def push_frame(self, frame, direction):
            self.results.append(type(frame).__name__)

    scenario = {"facts_to_elicit": ["hours", "closed_days"], "claims_to_verify": []}
    for elapsed, expect_granted in (
        (10.0, False),
        (config.MAX_CALL_SECONDS - HANGUP_OVERRIDE_SECONDS + 1, True),
    ):
        turn_logger, tracker, params = FakeLogger(elapsed), FakeTracker(), FakeParams()
        tools = build_tools(CALL_ID, turn_logger, scenario, tracker)
        await next(t for t in tools if t.name == "hang_up").handler(params)
        granted = params.results[0] == {"hangup": "ok"}
        assert granted is expect_granted, (elapsed, params.results)
        if not granted:
            assert params.results[0] == {"hangup": "denied", "missing": ["hours", "closed_days"]}
        else:
            assert "EndWorkerFrame" in params.results, params.results
        print(f"  at {elapsed:.0f}s with facts missing -> {params.results[0]}")
    print("  PASS denial carries the missing slots; the time override grants regardless")


async def main():
    print("=== exit path ===")
    await test_serializer_terminates_on_end_and_cancel()
    await test_hangup_is_granted_past_the_time_override()


asyncio.run(main())
