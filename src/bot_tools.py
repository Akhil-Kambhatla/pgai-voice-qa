import asyncio
import json
import os

from loguru import logger
from pipecat.adapters.schemas.function_schema import FunctionSchema

from src import config, oracle


def build_tools(call_id: str, turn_logger):
    observations_path = os.path.join(config.CALLS_DIR, call_id, "observations.jsonl")
    os.makedirs(os.path.dirname(observations_path), exist_ok=True)

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
        logger.info(f"end_call invoked: {reason}")
        turn_logger.log_tool_call("end_call", params.arguments, {"status": "ending"})
        await params.result_callback({"status": "ending, say a brief goodbye"})

        async def stop_after_goodbye():
            await asyncio.sleep(6)
            await params.pipeline_worker.stop_when_done()

        asyncio.create_task(stop_after_goodbye())

    return [
        FunctionSchema(
            name="check_fact",
            description="Check something the clinic just stated about itself (hours, days, locations, providers, policies) against what you already know. Instant.",
            properties={"claim": {"type": "string", "description": "What the clinic just stated, as close to verbatim as possible."}},
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
            description="Hang up the phone. Use when you have what you came for or the conversation has stalled.",
            properties={"reason": {"type": "string", "description": "Why the call is ending."}},
            required=["reason"],
            handler=handle_end_call,
        ),
    ]
