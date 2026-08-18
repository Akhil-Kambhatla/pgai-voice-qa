import json
import os

from loguru import logger
from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.frames.frames import EndWorkerFrame, InterruptionWorkerFrame
from pipecat.processors.frame_processor import FrameDirection

from src import config, oracle

END_CALL_OVERRIDE_SECONDS = 30


def build_tools(call_id: str, turn_logger, scenario: dict):
    observations_path = os.path.join(config.CALLS_DIR, call_id, "observations.jsonl")
    os.makedirs(os.path.dirname(observations_path), exist_ok=True)

    def unmet_goals():
        elicited = oracle.topics_checked(call_id)
        missing = [fact for fact in scenario.get("facts_to_elicit", []) if fact not in elicited]
        for target in scenario.get("claims_to_verify", []):
            if not oracle.claim_addressed(call_id, target):
                missing.append(target)
        return missing

    async def handle_check_fact(params):
        claim = params.arguments.get("claim", "")
        result = oracle.check_fact(claim, call_id)
        turn_logger.log_tool_call("check_fact", params.arguments, result)
        await params.result_callback(result)

    async def handle_note_observation(params):
        with open(observations_path, "a") as f:
            f.write(json.dumps(dict(params.arguments)) + "\n")
        turn_logger.log_tool_call("note_observation", params.arguments, {"noted": True})
        await params.result_callback({"noted": True})

    async def handle_end_call(params):
        reason = params.arguments.get("reason", "")
        missing = unmet_goals()
        past_override = turn_logger.elapsed_seconds() >= config.MAX_CALL_SECONDS - END_CALL_OVERRIDE_SECONDS
        if missing and not past_override:
            result = {
                "status": "refused",
                "reason": "still need: " + ", ".join(missing),
                "instruction": "continue the conversation naturally",
            }
            turn_logger.log_tool_call("end_call", params.arguments, result)
            await params.result_callback(result)
            return
        logger.info(f"end_call accepted: {reason}")
        turn_logger.log_tool_call("end_call", params.arguments, {"status": "ending"})
        await params.result_callback({"status": "ending"})
        await params.llm.push_frame(InterruptionWorkerFrame(), FrameDirection.UPSTREAM)
        await params.llm.push_frame(EndWorkerFrame(reason=reason), FrameDirection.UPSTREAM)

    return [
        FunctionSchema(
            name="check_fact",
            description="Check one single fact the clinic just stated about itself (hours, days, locations, providers, policies) against what you already know. One fact per call, never several combined. Instant.",
            properties={"claim": {"type": "string", "description": "The one fact the clinic just stated, as close to verbatim as possible."}},
            required=["claim"],
            handler=handle_check_fact,
        ),
        FunctionSchema(
            name="note_observation",
            description="Silently note something that seemed off without breaking the conversation flow.",
            properties={"observation": {"type": "string", "description": "What seemed off."}},
            required=["observation"],
            handler=handle_note_observation,
        ),
        FunctionSchema(
            name="end_call",
            description="Hang up the phone. Use when you have what you came for or the conversation has stalled. If it refuses, keep the conversation going naturally.",
            properties={"reason": {"type": "string", "description": "Why the call is ending."}},
            required=["reason"],
            handler=handle_end_call,
        ),
    ]
