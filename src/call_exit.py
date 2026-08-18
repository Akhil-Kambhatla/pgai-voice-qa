import time

from loguru import logger
from pipecat.frames.frames import CancelFrame, EndFrame
from pipecat.serializers.telnyx import TelnyxFrameSerializer

from src.event_tap import EventRecorder


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

    def watchdog_fired(self, limit: int):
        self._recorder.record("lifecycle", {"type": "exit.watchdog_terminated", "limit_seconds": limit})

    def stream_disconnected(self):
        self._recorder.record("lifecycle", {"type": "exit.stream_disconnected"})
