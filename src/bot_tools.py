import json
import os

from loguru import logger
from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.frames.frames import EndWorkerFrame, InterruptionWorkerFrame
from pipecat.processors.frame_processor import FrameDirection

from src import call_exit, config, goal_judge, oracle

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


def build_tools(call_id: str, turn_logger, scenario: dict, exit_tracker, retry):
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
        if retry.exhausted:
            return "nudged_twice"
        if turn_logger.stalled():
            return "stalled"
        outcome, why = await goal_judge.call_outcome(scenario["goal"], turn_logger.turns, exit_tracker)
        return f"{outcome}: {why}" if outcome in goal_judge.GRANTING_OUTCOMES else ""

    async def handle_hang_up(params):
        reason = params.arguments.get("reason", "")
        elapsed = turn_logger.elapsed_seconds()
        retry.note_attempt()
        missing = unmet_goals()
        condition = await grant_condition(missing, elapsed)
        if not condition:
            still_want = call_exit.as_caller_wants(missing)
            result = {"hangup": "denied", "still_want": still_want}
            exit_tracker.hangup_decision(False, reason, missing, elapsed, "")
            turn_logger.log_tool_call("hang_up", params.arguments, result)
            await params.result_callback(result)
            retry.note_denial(still_want)
            return
        exit_tracker.hangup_decision(True, reason, missing, elapsed, condition)
        turn_logger.log_tool_call("hang_up", params.arguments, {"hangup": "ok"})
        await params.result_callback({"hangup": "ok"})
        await params.llm.push_frame(InterruptionWorkerFrame(), FrameDirection.UPSTREAM)
        await params.llm.push_frame(EndWorkerFrame(reason=reason), FrameDirection.DOWNSTREAM)

    return [
        FunctionSchema(
            name="silent_compare",
            description="Records one checkable fact the receptionist has just asserted about this clinic: an opening or closing time, a day they are open or closed, a date, a provider's name, a location, a price, a policy, an appointment they have just made. Use it on the first such fact of the call too, when there is nothing yet to set it against, because holding on to it is half of what this does. One fact per use, never two joined together. Nothing else goes through here: not greetings, not questions they ask you, not requests for your details, not acknowledgements, not anything you said yourself. If their sentence could not turn out to be false, it is not for this.",
            properties={"claim": {"type": "string", "description": "The single fact the receptionist just asserted, close to their own words."}},
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
