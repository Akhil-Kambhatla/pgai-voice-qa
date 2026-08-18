import json
import os
import time

from src import config

AUDIO_PAYLOAD_EVENTS = {"input_audio_buffer.append", "response.output_audio.delta"}
ELIDED_FIELDS = ("audio", "delta")


class EventRecorder:
    def __init__(self, call_id: str):
        self._path = os.path.join(config.CALLS_DIR, call_id, "events.jsonl")
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        self._start = time.monotonic()
        self._elided_counts = {}

    def write_artifact(self, name: str, text: str):
        with open(os.path.join(os.path.dirname(self._path), name), "w") as f:
            f.write(text)

    def record(self, source: str, payload):
        event_type = payload.get("type") if isinstance(payload, dict) else None
        if event_type in AUDIO_PAYLOAD_EVENTS:
            key = f"{source}:{event_type}"
            self._elided_counts[key] = self._elided_counts.get(key, 0) + 1
            if self._elided_counts[key] % 200 != 1:
                return
            payload = {k: v for k, v in payload.items() if k not in ELIDED_FIELDS}
            payload["elided_payload_count"] = self._elided_counts[key]
        line = {
            "t": round(time.monotonic() - self._start, 4),
            "source": source,
            "type": event_type,
            "event": payload,
        }
        with open(self._path, "a") as f:
            f.write(json.dumps(line) + "\n")


class TappedWebsocket:
    def __init__(self, inner, recorder: EventRecorder):
        self._inner = inner
        self._recorder = recorder

    def __getattr__(self, name):
        return getattr(self._inner, name)

    async def send(self, message):
        self._recorder.record("client", _safe_parse(message))
        return await self._inner.send(message)

    async def __aiter__(self):
        async for message in self._inner:
            self._recorder.record("server", _safe_parse(message))
            yield message


def _safe_parse(message):
    try:
        return json.loads(message)
    except (TypeError, ValueError):
        return {"unparsed": str(message)[:500]}
