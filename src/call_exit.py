import asyncio
import json
import time

from loguru import logger
from pipecat.frames.frames import CancelFrame, EndFrame
from pipecat.serializers.telnyx import TelnyxFrameSerializer
from pipecat.services.openai.realtime import events as realtime_events

from src.event_tap import EventRecorder

UNMET_CLAIM = "claim"
UNMET_GOAL = "goal"


class RecordedTelnyxSerializer(TelnyxFrameSerializer):
    def __init__(self, *, recorder: EventRecorder, **kwargs):
        super().__init__(**kwargs)
        self._recorder = recorder

    async def serialize(self, frame):
        if isinstance(frame, (EndFrame, CancelFrame)):
            self._recorder.record(
                "lifecycle",
                {
                    "type": "exit.frame_reached_serializer",
                    "frame": type(frame).__name__,
                    "hangup_already_attempted": self._hangup_attempted,
                },
            )
        return await super().serialize(frame)

    async def _hang_up_call(self):
        started = time.monotonic()
        self._recorder.record("lifecycle", {"type": "exit.telnyx_hangup_requested"})
        await super()._hang_up_call()
        self._recorder.record(
            "lifecycle",
            {
                "type": "exit.telnyx_hangup_returned",
                "seconds": round(time.monotonic() - started, 3),
            },
        )


class ExitTracker:
    def __init__(self, recorder: EventRecorder):
        self._recorder = recorder

    def hangup_decision(self, granted: bool, reason: str, missing, elapsed: float, condition: str):
        self._recorder.record(
            "lifecycle",
            {
                "type": "exit.hangup_granted" if granted else "exit.hangup_denied",
                "reason": reason,
                "missing": missing,
                "elapsed_seconds": round(elapsed, 1),
                "grant_condition": condition,
            },
        )
        verdict = f"granted ({condition})" if granted else "denied"
        logger.info(f"hang_up {verdict} at {elapsed:.1f}s missing={missing}")

    def judge_round_trip(self, elapsed: float, outcome: str, source: str):
        self._recorder.record(
            "lifecycle",
            {"type": "judge.round_trip", "elapsed_seconds": round(elapsed, 3), "outcome": outcome, "source": source},
        )

    def watchdog_fired(self, limit: int):
        self._recorder.record("lifecycle", {"type": "exit.watchdog_terminated", "limit_seconds": limit})

    def stream_disconnected(self):
        self._recorder.record("lifecycle", {"type": "exit.stream_disconnected"})

    def nudged(self, unmet, count):
        self._recorder.record(
            "lifecycle", {"type": "exit.nudge_injected", "unmet": unmet, "count": count}
        )


class HangupRetry:
    def __init__(self, tracker: ExitTracker, delay_seconds: int = 45, max_nudges: int = 2):
        self._tracker = tracker
        self._delay = delay_seconds
        self._max_nudges = max_nudges
        self._llm = None
        self._timer = None
        self.nudges_fired = 0

    def attach(self, llm):
        self._llm = llm

    @property
    def exhausted(self) -> bool:
        return self.nudges_fired >= self._max_nudges

    def note_attempt(self):
        if self._timer:
            self._timer.cancel()
            self._timer = None

    def note_denial(self, unmet):
        self.note_attempt()
        self._timer = asyncio.create_task(self._nudge_later(unmet))

    async def _nudge_later(self, unmet):
        try:
            await asyncio.sleep(self._delay)
        except asyncio.CancelledError:
            return
        self.nudges_fired += 1
        payload = json.dumps({"unmet": unmet, "nudge": self.nudges_fired})
        await self._llm.send_client_event(
            realtime_events.ConversationItemCreateEvent(
                item=realtime_events.ConversationItem(
                    type="message",
                    role="system",
                    content=[realtime_events.ItemContent(type="input_text", text=payload)],
                )
            )
        )
        self._tracker.nudged(unmet, self.nudges_fired)
        logger.info(f"exit nudge {self.nudges_fired} injected: {payload}")
        self._timer = asyncio.create_task(self._nudge_later(unmet))
