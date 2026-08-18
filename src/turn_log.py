import json
import os
import re
import time

from loguru import logger
from pipecat.frames.frames import Frame, TranscriptionFrame, TTSStoppedFrame, TTSTextFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from src import config

_GOODBYE_RE = re.compile(r"\b(good\s?-?\s?bye|bye+|bye\s?now)\b", re.IGNORECASE)


def _content_words(text):
    return set(re.findall(r"[a-z]{4,}", text.lower()))


class TurnLogger(FrameProcessor):
    def __init__(self, call_id: str):
        super().__init__()
        self._path = os.path.join(config.CALLS_DIR, call_id, "turns.jsonl")
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        self._start = time.monotonic()
        self._bot_turn_text = ""
        self.turns = []

    def _write(self, speaker: str, text: str):
        line = {
            "speaker": speaker,
            "text": text,
            "elapsed_seconds": round(time.monotonic() - self._start, 1),
        }
        self.turns.append(line)
        with open(self._path, "a") as f:
            f.write(json.dumps(line) + "\n")

    def elapsed_seconds(self) -> float:
        return time.monotonic() - self._start

    def stalled(self, window: int = 2, min_new_words: int = 3) -> bool:
        agent_turns = [t["text"] for t in self.turns if t["speaker"] == "agent"]
        if len(agent_turns) <= window:
            return False
        earlier = set().union(*(_content_words(t) for t in agent_turns[:-window]))
        recent = set().union(*(_content_words(t) for t in agent_turns[-window:]))
        return len(recent - earlier) < min_new_words

    def log_tool_call(self, name: str, arguments, result):
        self._write("tool", json.dumps({"name": name, "arguments": dict(arguments), "result": result}))

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, TranscriptionFrame):
            text = frame.text.strip()
            if text:
                self._write("agent", text)
        elif isinstance(frame, TTSTextFrame):
            self._bot_turn_text += frame.text
        elif isinstance(frame, TTSStoppedFrame):
            if self._bot_turn_text.strip():
                self._write("bot", self._bot_turn_text.strip())
            self._bot_turn_text = ""
        await self.push_frame(frame, direction)


class GoodbyeWatcher(FrameProcessor):
    def __init__(self):
        super().__init__()
        self._turn_text = ""
        self.on_goodbye = None

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, TTSTextFrame):
            self._turn_text += frame.text
        elif isinstance(frame, TTSStoppedFrame):
            if _GOODBYE_RE.search(self._turn_text) and self.on_goodbye:
                logger.info(f"Goodbye backstop fired on {self._turn_text!r}; ending call")
                await self.on_goodbye()
            self._turn_text = ""
        await self.push_frame(frame, direction)
