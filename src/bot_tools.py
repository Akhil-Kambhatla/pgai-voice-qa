import json
import os

from loguru import logger
from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.frames.frames import EndWorkerFrame, InterruptionWorkerFrame
from pipecat.processors.frame_processor import FrameDirection

from src import config, goal_judge, oracle

HANGUP_OVERRIDE_SECONDS = 30

VERDICTS = {
    "invalid": {"verdict": "split"},
    "already_asked": {"verdict": "repeat"},
    "already_confirmed": {"verdict": "repeat"},
    "unknown": {"verdict": "none"},
    "consistent": {"verdict": "none"},
}


def _verdict(result):
    if result["status"] in VERDICTS:
        return VERDICTS[result["status"]]
    return {"verdict": "conflict", "heard_earlier": result.get("rule")}


def build_tools(call_id: str, turn_logger, scenario: dict, exit_tracker):
    observations_path = os.path.join(config.CALLS_DIR, call_id, "observations.jsonl")
    os.makedirs(os.path.dirname(observations_path), exist_ok=True)
    required_slots = scenario.get("facts_to_elicit", [])

    def unmet_goals():
        elicited = oracle.topics_checked(call_id)
        missing = [fact for fact in required_slots if fact not in elicited]
        for target in scenario.get("claims_to_verify", []):
            if not oracle.claim_addressed(call_id, target):
                missing.append(target)
        return missing

    async def handle_silent_compare(params):
        claim = params.arguments.get("claim", "")
        result = oracle.check_fact(claim, call_id, required_slots=required_slots)
        verdict = _verdict(result)
        turn_logger.log_tool_call("silent_compare", params.arguments, result)
        await params.result_callback(verdict)

    async def handle_silent_note(params):
        with open(observations_path, "a") as f:
            f.write(json.dumps(dict(params.arguments)) + "\n")
        turn_logger.log_tool_call("silent_note", params.arguments, {"verdict": "ok"})
        await params.result_callback({"verdict": "ok"})

    async def grant_condition(missing, elapsed):
        if not missing:
            return "facts_complete"
        if elapsed >= config.MAX_CALL_SECONDS - HANGUP_OVERRIDE_SECONDS:
            return "time_override"
        if turn_logger.stalled():
            return "stalled"
        achieved, why = await goal_judge.goal_achieved(scenario["goal"], turn_logger.turns)
        return f"goal_achieved: {why}" if achieved else ""

    async def handle_hang_up(params):
        reason = params.arguments.get("reason", "")
        elapsed = turn_logger.elapsed_seconds()
        missing = unmet_goals()
        condition = await grant_condition(missing, elapsed)
        if not condition:
            result = {"hangup": "denied", "missing": missing}
            exit_tracker.hangup_decision(False, reason, missing, elapsed, "")
            turn_logger.log_tool_call("hang_up", params.arguments, result)
            await params.result_callback(result)
            return
        exit_tracker.hangup_decision(True, reason, missing, elapsed, condition)
        turn_logger.log_tool_call("hang_up", params.arguments, {"hangup": "ok"})
        await params.result_callback({"hangup": "ok"})
        await params.llm.push_frame(InterruptionWorkerFrame(), FrameDirection.UPSTREAM)
        await params.llm.push_frame(EndWorkerFrame(reason=reason), FrameDirection.DOWNSTREAM)

    return [
        FunctionSchema(
            name="silent_compare",
            description="Runs the instant the receptionist states anything concrete about this clinic: a time, a day, a name, a price, a policy, whether they are open. Use it on the first such statement of the call too, when there is nothing yet to set it against, because holding on to it is half of what this does. One statement per use, never two joined together.",
            properties={"claim": {"type": "string", "description": "The single thing the receptionist just said, close to their own words."}},
            required=["claim"],
            handler=handle_silent_compare,
        ),
        FunctionSchema(
            name="silent_note",
            description="Private thought. Sets aside something that felt wrong, so the call can carry on without chasing it.",
            properties={"observation": {"type": "string", "description": "What felt wrong."}},
            required=["observation"],
            handler=handle_silent_note,
        ),
        FunctionSchema(
            name="hang_up",
            description="End the phone call. Use it once you have what you called for, or the conversation has stalled.",
            properties={"reason": {"type": "string", "description": "Why the call is over."}},
            required=["reason"],
            handler=handle_hang_up,
        ),
    ]
