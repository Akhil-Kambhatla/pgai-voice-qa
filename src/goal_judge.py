import asyncio
import json
import time

from loguru import logger
from openai import AsyncOpenAI

from src import config, store

JUDGE_TIMEOUT_SECONDS = 2
SPOKEN_SPEAKERS = ("bot", "agent")
UNGRANTED_OUTCOME = "not_yet"
_client = None


def _judge_client():
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=config.OPENAI_API_KEY)
    return _client


def _transcript(turns):
    lines = []
    for turn in turns:
        if turn["speaker"] not in SPOKEN_SPEAKERS:
            continue
        who = "CALLER" if turn["speaker"] == "bot" else "RECEPTIONIST"
        lines.append(f"[{turn['elapsed_seconds']}s] {who}: {turn['text']}")
    return "\n".join(lines)


GRANTING_OUTCOMES = ("goal_met", "unachievable")


async def call_outcome(goal: str, turns, tracker) -> tuple[str, str]:
    started = time.monotonic()
    transcript = _transcript(turns)
    if not transcript:
        tracker.judge_round_trip(time.monotonic() - started, UNGRANTED_OUTCOME, "skipped")
        return UNGRANTED_OUTCOME, "nothing said yet"
    user_content = f"Goal:\n{goal}\n\nTranscript so far:\n{transcript}"
    try:
        response = await asyncio.wait_for(
            _judge_client().chat.completions.create(
                model=config.PLANNER_MODEL,
                messages=[
                    {"role": "system", "content": store.load_prompt("goal_judge")},
                    {"role": "user", "content": user_content},
                ],
                response_format={"type": "json_object"},
            ),
            timeout=JUDGE_TIMEOUT_SECONDS,
        )
        verdict = json.loads(response.choices[0].message.content)
        outcome = str(verdict.get("outcome", UNGRANTED_OUTCOME))
        tracker.judge_round_trip(time.monotonic() - started, outcome, "model")
        return outcome, str(verdict.get("why", ""))
    except Exception as error:
        tracker.judge_round_trip(time.monotonic() - started, UNGRANTED_OUTCOME, "exception")
        logger.warning(
            f"goal judge failed ({type(error).__name__}: {error}); denying hang_up, "
            f"the time override still ends the call"
        )
        return UNGRANTED_OUTCOME, "judge unavailable, failing closed"
