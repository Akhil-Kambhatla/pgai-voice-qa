import asyncio
import json

from loguru import logger
from openai import AsyncOpenAI

from src import config, store

JUDGE_TIMEOUT_SECONDS = 6
SPOKEN_SPEAKERS = ("bot", "agent")
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


async def call_outcome(goal: str, turns) -> tuple[str, str]:
    transcript = _transcript(turns)
    if not transcript:
        return "not_yet", "nothing said yet"
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
        outcome = str(verdict.get("outcome", "not_yet"))
        return outcome, str(verdict.get("why", ""))
    except Exception as error:
        logger.warning(f"goal judge failed ({error}); granting hang_up rather than trapping the call")
        return "goal_met", "judge unavailable, failing open"
