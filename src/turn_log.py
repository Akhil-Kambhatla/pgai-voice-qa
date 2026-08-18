import json
import os
import re
import time

from loguru import logger
from pipecat.frames.frames import Frame, TranscriptionFrame, TTSStoppedFrame, TTSTextFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from src import config, oracle

_GOODBYE_RE = re.compile(r"\b(good\s?-?\s?bye|bye+|bye\s?now)\b", re.IGNORECASE)


def _content_words(text):
    return set(re.findall(r"[a-z]{4,}", text.lower()))


def _specifics(texts):
    found = set()
    for text in texts:
        categories = oracle._category_tokens(text)
        for name in ("time", "weekday", "month", "number"):
            found |= {f"{name}:{token}" for token in categories[name]}
    return found


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

    def stalled(self, window: int = 2, min_words_to_judge: int = 8, new_ratio: float = 0.45) -> bool:
        agent_turns = [t["text"] for t in self.turns if t["speaker"] == "agent"]
        if len(agent_turns) <= window:
            return False
        earlier, recent = agent_turns[:-window], agent_turns[-window:]
        earlier_words = set().union(*(_content_words(t) for t in earlier))
        recent_words = set().union(*(_content_words(t) for t in recent))
        if len(recent_words) < min_words_to_judge:
            return False
        if _specifics(recent) - _specifics(earlier):
            return False
        return len(recent_words - earlier_words) / len(recent_words) < new_ratio

    def log_tool_call(self, name: str, arguments, result):
        self._write("tool", json.dumps({"name": name, "arguments": dict(arguments), "result": result}))

    def record_agent_turn(self, text: str):
        self._write("agent", text)

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, TTSTextFrame):
            self._bot_turn_text += frame.text
        elif isinstance(frame, TTSStoppedFrame):
            if self._bot_turn_text.strip():
                self._write("bot", self._bot_turn_text.strip())
            self._bot_turn_text = ""
        await self.push_frame(frame, direction)


class TranscriptTap(FrameProcessor):
    def __init__(self, turn_logger: TurnLogger):
        super().__init__()
        self._turn_logger = turn_logger

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, TranscriptionFrame):
            text = frame.text.strip()
            if text:
                self._turn_logger.record_agent_turn(text)
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
