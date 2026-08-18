import json
import os

from loguru import logger
from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.frames.frames import EndWorkerFrame, InterruptionWorkerFrame
from pipecat.processors.frame_processor import FrameDirection

from src import config, oracle

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


def build_tools(call_id: str, turn_logger, scenario: dict):
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

    async def handle_hang_up(params):
        reason = params.arguments.get("reason", "")
        missing = unmet_goals()
        past_override = turn_logger.elapsed_seconds() >= config.MAX_CALL_SECONDS - HANGUP_OVERRIDE_SECONDS
        if missing and not past_override:
            logger.info(f"hang_up denied, still unmet: {missing}")
            turn_logger.log_tool_call("hang_up", params.arguments, {"hangup": "denied", "unmet": missing})
            await params.result_callback({"hangup": "denied"})
            return
        logger.info(f"hang_up accepted: {reason}")
        turn_logger.log_tool_call("hang_up", params.arguments, {"hangup": "ok"})
        await params.result_callback({"hangup": "ok"})
        await params.llm.push_frame(InterruptionWorkerFrame(), FrameDirection.UPSTREAM)
        await params.llm.push_frame(EndWorkerFrame(reason=reason), FrameDirection.UPSTREAM)

    return [
        FunctionSchema(
            name="silent_compare",
            description="Private thought. Sets one thing the receptionist just said about this clinic against what you were already told on this call. One statement at a time.",
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
